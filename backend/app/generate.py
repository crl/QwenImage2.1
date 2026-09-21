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
from .workflows import build_edit, build_masked_edit, build_outpaint_edit, build_seedvr2_upscale, build_t2i

jobs: dict[str, str] = {}

DISPLAY_PROMPTS = {
    "erase": "擦除标记区域",
    "outpaint": "扩图",
    "enhance": "变清晰",
}

ERASE_DEFAULT = (
    "去掉标记的红色区域中的内容，并按周围场景自然填补。未标记区域保持不变。"
)
OUTPAINT_NEGATIVE = (
    "blank bars, letterbox, pillarbox, solid color borders, red overlay, gray padding, "
    "empty margins, stretched edges, repeating stripes"
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
    if edit_mode == "enhance":
        return ENHANCE_PROMPT
    return text


def outpaint_model_prompt(prompt: str, pads: tuple[int, int, int, int] | None) -> str:
    left, top, right, bottom = pads or (0, 0, 0, 0)
    sides: list[str] = []
    if left:
        sides.append("左")
    if right:
        sides.append("右")
    if top:
        sides.append("上")
    if bottom:
        sides.append("下")
    where = "、".join(sides) or "四周"
    extra = prompt.strip()
    extra_clause = f"额外要求：{extra}。" if extra else ""
    return (
        f"把这张图向{where}方向扩展，补全画面外连续的天空、云层、环境和光影。"
        f"{extra_clause}"
        "保持人物、姿态、构图、光影和画风完全不变，主体仍在画面中心。"
        "不要出现空白、纯色色块、边框、拉伸或重复条纹。"
    )


def _upscale_multiplier(width: int, height: int, max_side: int = 2048) -> float:
    longest = max(width, height, 1)
    return max(0.25, round(min(4.0, max_side / longest), 2))


def _fit_size(width: int, height: int, max_side: int = 2048) -> tuple[int, int]:
    longest = max(width, height)
    if longest > max_side:
        scale = max_side / longest
        width = round(width * scale)
        height = round(height * scale)
    return (
        max(32, round(width / 32) * 32),
        max(32, round(height / 32) * 32),
    )


def _feather_lock_mask(size: tuple[int, int], feather: int = 40) -> Image.Image:
    width, height = size
    if feather <= 0 or width < 8 or height < 8:
        return Image.new("RGB", size, (255, 255, 255))
    feather = max(1, min(feather, width // 4, height // 4))
    inner = Image.new("L", (width, height), 0)
    white = Image.new("L", (max(1, width - 2 * feather), max(1, height - 2 * feather)), 255)
    inner.paste(white, (feather, feather))
    mask = inner.filter(ImageFilter.GaussianBlur(feather / 2))
    return Image.merge("RGB", (mask, mask, mask))


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
    fill: str = "gray",
) -> tuple[Image.Image, Image.Image]:
    width, height = source.size
    left, top, right, bottom = [max(0, (value // 32) * 32) for value in (left, top, right, bottom)]
    rgb = source.convert("RGB")
    canvas_size = (width + left + right, height + top + bottom)
    if fill == "edge":
        canvas = _edge_padded(rgb, left, top, right, bottom)
    else:
        canvas = Image.new("RGB", canvas_size, (128, 128, 128))
        canvas.paste(rgb, (left, top))
    mask = Image.new("RGB", canvas_size, (255, 255, 255))
    mask.paste(Image.new("RGB", (width, height), (0, 0, 0)), (left, top))
    if fit:
        return _fit_max_side(canvas, mask)
    return canvas, mask


def _edge_padded(rgb: Image.Image, left: int, top: int, right: int, bottom: int) -> Image.Image:
    width, height = rgb.size
    canvas = Image.new("RGB", (width + left + right, height + top + bottom))
    if left:
        canvas.paste(rgb.crop((0, 0, 1, height)).resize((left, height)), (0, top))
    if right:
        canvas.paste(rgb.crop((width - 1, 0, width, height)).resize((right, height)), (left + width, top))
    if top:
        canvas.paste(rgb.crop((0, 0, width, 1)).resize((width, top)), (left, 0))
    if bottom:
        canvas.paste(rgb.crop((0, height - 1, width, height)).resize((width, bottom)), (left, top + height))
    if left and top:
        canvas.paste(Image.new("RGB", (left, top), rgb.getpixel((0, 0))), (0, 0))
    if right and top:
        canvas.paste(Image.new("RGB", (right, top), rgb.getpixel((width - 1, 0))), (left + width, 0))
    if left and bottom:
        canvas.paste(Image.new("RGB", (left, bottom), rgb.getpixel((0, height - 1))), (0, top + height))
    if right and bottom:
        canvas.paste(Image.new("RGB", (right, bottom), rgb.getpixel((width - 1, height - 1))), (left + width, top + height))
    canvas.paste(rgb, (left, top))
    return canvas


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
        padded, _ = pad_image(source, left, top, right, bottom, fit=False, fill="gray")
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
        if edit_mode == "outpaint":
            final_prompt = outpaint_model_prompt(prompt, pads)
        else:
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
        rgb = source.convert("RGB")
        name = await client.upload_image(_png_bytes(rgb), f"{uuid.uuid4().hex}.png")
        return build_seedvr2_upscale(
            name,
            seed=seed,
            multiplier=_upscale_multiplier(*rgb.size),
        )

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
    width, height = source.size
    left, top, right, bottom = [max(0, (value // 32) * 32) for value in (left, top, right, bottom)]
    full_w, full_h = width + left + right, height + top + bottom
    canvas_w, canvas_h = _fit_size(full_w, full_h)
    scale_x = canvas_w / full_w if full_w else 1
    scale_y = canvas_h / full_h if full_h else 1
    paste_x = round(left * scale_x)
    paste_y = round(top * scale_y)
    center = source.convert("RGB").resize(
        (max(1, round(width * scale_x)), max(1, round(height * scale_y))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
    original_name = await client.upload_image(_png_bytes(center), f"{uuid.uuid4().hex}.png")
    canvas_name = await client.upload_image(_png_bytes(canvas), f"{uuid.uuid4().hex}.png")
    mask_name = await client.upload_image(_png_bytes(_feather_lock_mask(center.size)), f"{uuid.uuid4().hex}.png")
    return build_outpaint_edit(
        prompt,
        original_name=original_name,
        canvas_name=canvas_name,
        mask_name=mask_name,
        seed=seed,
        steps=steps,
        paste_x=paste_x,
        paste_y=paste_y,
        negative_prompt=OUTPAINT_NEGATIVE,
    )
