from __future__ import annotations

import base64
import random
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .comfy import ComfyClient, ComfyError, collect_output_images, new_ids
from .config import IMAGES_DIR, pixel_size, wrap_transparent
from .hub import EventHub
from .store import Store
from .workflows import build_edit, build_t2i

jobs: dict[str, str] = {}


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
) -> None:
    try:
        await hub.publish(
            conversation_id,
            {"type": "progress", "message_id": message_id, "value": 0, "max": steps},
        )
        final_prompt = wrap_transparent(prompt) if transparent else prompt
        last = store.last_output_image(conversation_id)
        image_names: list[str] = []
        for original_name, data in uploaded:
            suffix = Path(original_name).suffix or ".png"
            image_names.append(await client.upload_image(data, f"{uuid.uuid4().hex}{suffix}"))

        mode = "edit" if image_names or last else "t2i"
        if mode == "edit" and not image_names and last:
            image_path = IMAGES_DIR / last["filename"]
            image_names.append(await client.upload_image(image_path.read_bytes(), last["filename"]))

        seed = random.randint(0, 2**32 - 1)
        width, height = pixel_size(aspect, quality)
        resolution = 2048 if quality == "2k" else 1024
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
                prompt,
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
