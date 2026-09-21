from __future__ import annotations

import base64
import random
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from .comfy import ComfyClient, ComfyError, collect_output_images, new_ids
from .config import IMAGES_DIR, QUALITY_BASE, pixel_size, wrap_transparent
from .hub import EventHub
from .store import Store
from .workflows import build_edit, build_masked_edit, build_t2i

jobs: dict[str, str] = {}

DISPLAY_PROMPTS = {
    "erase": "擦除标记区域",
    "outpaint": "扩图",
    "enhance": "变清晰",
}

ERASE_DEFAULT = (
    "去掉标记的红色区域中的内容，并按周围场景自然填补。未标记区域保持不变。"
)
OUTPAINT_DEFAULT = (
    "将画面自然延伸到灰色填充的边缘区域，中心原图保持不变，匹配光影、透视和风格。"
)
ENHANCE_PROMPT = (
    "提升这张图的清晰度和细节，保持构图、人物身份、光影、颜色和内容完全不变。"
)


def display_prompt(edit_mode: str | None, prompt: str) -> str:
    text = prompt.strip()
    if text:
        return text
    if edit_mode in DISPLAY_PROMPTS:
        return DISPLAY_PROMPTS[edit_mode]
    return text


def model_prompt(edit_mode: str | None, prompt: str) -> str:
    text = prompt.strip()
    if edit_mode == "erase":
        if text:
            return f"只修改标记的红色区域：{text}。未标记区域保持不变。"
        return ERASE_DEFAULT
    if edit_mode == "outpaint":
        if text:
            return f"将画面延伸到灰色边缘：{text}。中心原图保持不变。"
        return OUTPAINT_DEFAULT
    if edit_mode == "enhance":
        return ENHANCE_PROMPT
    return text


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _open_rgb(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    return image


def annotate_mask(source: Image.Image, mask: Image.Image) -> Image.Image:
    base = source.convert("RGBA")
    mask_l = mask.convert("L").resize(base.size, Image.Resampling.BILINEAR)
    overlay = Image.new("RGBA", base.size, (255, 60, 60, 150))
    empty = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tint = Image.composite(overlay, empty, mask_l)
    return Image.alpha_composite(base, tint).convert("RGB")


def pad_image(
    source: Image.Image,
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    fit: bool = True,
) -> tuple[Image.Image, Image.Image]:
    width, height = source.size
    left, top, right, bottom = [max(0, (value // 32) * 32) for value in (left, top, right, bottom)]
    canvas = Image.new("RGB", (width + left + right, height + top + bottom), (128, 128, 128))
    rgb = source.convert("RGB")
    canvas.paste(rgb, (left, top))
    mask = Image.new("RGB", canvas.size, (255, 255, 255))
    mask.paste(Image.new("RGB", (width, height), (0, 0, 0)), (left, top))
    if fit:
        return _fit_max_side(canvas, mask)
    return canvas, mask


def edit_preview_image(
    mode: str,
    source: Image.Image,
    mask_bytes: bytes | None = None,
    pads: tuple[int, int, int, int] | None = None,
) -> Image.Image | None:
    if mode == "erase":
        if not mask_bytes:
            return None
        return annotate_mask(source, _open_rgb(mask_bytes))
    if mode == "outpaint":
        left, top, right, bottom = pads or (0, 0, 0, 0)
        if left + top + right + bottom <= 0:
            return None
        padded, _ = pad_image(source, left, top, right, bottom, fit=False)
        return padded
    return None


def _fit_max_side(image: Image.Image, mask: Image.Image, max_side: int = 2048) -> tuple[Image.Image, Image.Image]:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image, mask
    scale = max_side / longest
    next_w = max(32, round(width * scale / 32) * 32)
    next_h = max(32, round(height * scale / 32) * 32)
    return (
        image.resize((next_w, next_h), Image.Resampling.LANCZOS),
        mask.resize((next_w, next_h), Image.Resampling.NEAREST),
    )


def mask_has_paint(mask: Image.Image) -> bool:
    extrema = mask.convert("L").getextrema()
    return bool(extrema and extrema[1] > 16)


async def run_generation(
    *,
    store: Store,
    hub: EventHub,
    client: ComfyClient,
    conversation_id: str,
    message_id: str,
    prompt: str,
    aspect: str,
    quality: str,
    transparent: bool,
    steps: int,
    uploaded: list[tuple[str, bytes]],
    edit_mode: str | None = None,
    source_image: dict[str, Any] | None = None,
    mask_bytes: bytes | None = None,
    pads: tuple[int, int, int, int] | None = None,
) -> None:
    try:
        await hub.publish(
            conversation_id,
            {"type": "progress", "message_id": message_id, "value": 0, "max": steps},
        )
        final_prompt = model_prompt(edit_mode, prompt)
        if transparent:
            final_prompt = wrap_transparent(final_prompt)

        seed = random.randint(0, 2**32 - 1)
        source_wh = None
        if aspect == "auto":
            if uploaded:
                try:
                    with Image.open(BytesIO(uploaded[0][1])) as probe:
                        source_wh = probe.size
                except Exception:
                    source_wh = None
            if source_wh is None:
                last_for_ratio = store.last_output_image(conversation_id)
                if last_for_ratio and last_for_ratio.get("width") and last_for_ratio.get("height"):
                    source_wh = (int(last_for_ratio["width"]), int(last_for_ratio["height"]))
        width, height = pixel_size(aspect, quality, source_wh)
        resolution = QUALITY_BASE.get(quality, 1024)

        if edit_mode in {"erase", "outpaint", "enhance"}:
            if not source_image:
                raise ComfyError("找不到要编辑的图片")
            source_path = IMAGES_DIR / source_image["filename"]
            if not source_path.exists():
                raise ComfyError("源图片文件不存在")
            source = _open_rgb(source_path.read_bytes())
            workflow = await _tool_workflow(
                client=client,
                edit_mode=edit_mode,
                prompt=final_prompt,
                source=source,
                mask_bytes=mask_bytes,
                pads=pads,
                seed=seed,
                steps=steps,
            )
        else:
            image_names: list[str] = []
            for original_name, data in uploaded:
                suffix = Path(original_name).suffix or ".png"
                image_names.append(await client.upload_image(data, f"{uuid.uuid4().hex}{suffix}"))
            last = store.last_output_image(conversation_id)
            mode = "edit" if image_names or last else "t2i"
            if mode == "edit" and not image_names and last:
                image_path = IMAGES_DIR / last["filename"]
                image_names.append(await client.upload_image(image_path.read_bytes(), last["filename"]))
            if mode == "edit":
                workflow = build_edit(
                    final_prompt,
                    image_names,
                    seed=seed,
                    steps=steps,
                    resolution=resolution,
                )
            else:
                workflow = build_t2i(
                    final_prompt,
                    width=width,
                    height=height,
                    seed=seed,
                    steps=steps,
                )

        client_id, prompt_id = new_ids()
        jobs[conversation_id] = prompt_id
        await client.queue_prompt(workflow, client_id, prompt_id)

        async def on_progress(value: int, maximum: int) -> None:
            store.update_message(message_id, status="generating", progress=value, progress_max=maximum)
            await hub.publish(
                conversation_id,
                {
                    "type": "progress",
                    "message_id": message_id,
                    "value": value,
                    "max": maximum,
                },
            )

        async def on_preview(data: bytes) -> None:
            b64 = base64.b64encode(data).decode("ascii")
            mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            data_url = f"data:{mime};base64,{b64}"
            store.update_message(message_id, preview=data_url)
            await hub.publish(
                conversation_id,
                {"type": "preview", "message_id": message_id, "data_url": data_url},
            )

        await client.wait_for_prompt(client_id, prompt_id, on_progress, on_preview)
        outputs = await collect_output_images(client, prompt_id)
        if not outputs:
            raise ComfyError("没有收到生成图片")

        image_ids: list[str] = []
        saved_images: list[dict[str, Any]] = []
        shown_prompt = display_prompt(edit_mode, prompt)
        for raw in outputs:
            filename = f"{uuid.uuid4().hex}.png"
            path = IMAGES_DIR / filename
            width_out = height_out = None
            try:
                img = Image.open(BytesIO(raw))
                width_out, height_out = img.size
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if transparent else "RGB")
                img.save(path, format="PNG")
            except Exception:
                path.write_bytes(raw)
            record = store.add_image(
                conversation_id,
                message_id,
                filename,
                shown_prompt,
                width_out,
                height_out,
            )
            image_ids.append(record["id"])
            saved_images.append(record)

        message = store.update_message(
            message_id,
            status="done",
            progress=steps,
            progress_max=steps,
            preview=None,
            image_ids=image_ids,
            error=None,
        )
        jobs.pop(conversation_id, None)
        await hub.publish(
            conversation_id,
            {"type": "done", "message": message, "images": saved_images},
        )
    except Exception as exc:
        jobs.pop(conversation_id, None)
        message = store.update_message(
            message_id,
            status="error",
            error=str(exc),
            preview=None,
        )
        await hub.publish(
            conversation_id,
            {"type": "error", "message_id": message_id, "error": str(exc), "message": message},
        )


async def _tool_workflow(
    *,
    client: ComfyClient,
    edit_mode: str,
    prompt: str,
    source: Image.Image,
    mask_bytes: bytes | None,
    pads: tuple[int, int, int, int] | None,
    seed: int,
    steps: int,
) -> dict[str, Any]:
    if edit_mode == "enhance":
        name = await client.upload_image(_png_bytes(source.convert("RGB")), f"{uuid.uuid4().hex}.png")
        return build_edit(prompt, [name], seed=seed, steps=steps, resolution=2048)

    if edit_mode == "erase":
        if not mask_bytes:
            raise ComfyError("请先涂抹要修改的区域")
        mask = _open_rgb(mask_bytes).resize(source.size, Image.Resampling.BILINEAR)
        if not mask_has_paint(mask):
            raise ComfyError("请先涂抹要修改的区域")
        soft = mask.convert("L").filter(ImageFilter.GaussianBlur(2))
        mask_rgb = Image.merge("RGB", (soft, soft, soft))
        vision = annotate_mask(source, mask_rgb)
        original_name = await client.upload_image(_png_bytes(source.convert("RGB")), f"{uuid.uuid4().hex}.png")
        vision_name = await client.upload_image(_png_bytes(vision), f"{uuid.uuid4().hex}.png")
        mask_name = await client.upload_image(_png_bytes(mask_rgb), f"{uuid.uuid4().hex}.png")
        return build_masked_edit(
            prompt,
            vision_name=vision_name,
            original_name=original_name,
            mask_name=mask_name,
            seed=seed,
            steps=steps,
            resolution=0,
        )

    left, top, right, bottom = pads or (0, 0, 0, 0)
    if left + top + right + bottom <= 0:
        raise ComfyError("请先扩展画布")
    padded, mask_rgb = pad_image(source, left, top, right, bottom)
    padded_name = await client.upload_image(_png_bytes(padded), f"{uuid.uuid4().hex}.png")
    mask_name = await client.upload_image(_png_bytes(mask_rgb), f"{uuid.uuid4().hex}.png")
    return build_masked_edit(
        prompt,
        vision_name=padded_name,
        original_name=padded_name,
        mask_name=mask_name,
        seed=seed,
        steps=steps,
        resolution=0,
    )
