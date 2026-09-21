from __future__ import annotations

import asyncio
import json
import struct
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets

from .config import COMFY_URL

PREVIEW_IMAGE = 1
PREVIEW_IMAGE_WITH_METADATA = 4


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str = COMFY_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/system_stats")
                resp.raise_for_status()
                data = resp.json()
            return {
                "ok": True,
                "comfyui_version": data.get("system", {}).get("comfyui_version"),
                "pytorch": data.get("system", {}).get("pytorch_version"),
                "devices": [
                    {
                        "name": d.get("name"),
                        "vram_total": d.get("vram_total"),
                        "vram_free": d.get("vram_free"),
                    }
                    for d in data.get("devices", [])
                ],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def queue_prompt(self, workflow: dict[str, Any], client_id: str, prompt_id: str) -> dict[str, Any]:
        payload = {"prompt": workflow, "client_id": client_id, "prompt_id": prompt_id}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/prompt", json=payload)
            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise ComfyError(f"提交工作流失败: {detail}")
            return resp.json()

    async def interrupt(self) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/interrupt")

    async def upload_image(self, data: bytes, filename: str) -> str:
        files = {"image": (filename, data, "application/octet-stream")}
        form = {"overwrite": "true", "type": "input"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/upload/image", files=files, data=form)
            resp.raise_for_status()
            body = resp.json()
        name = body.get("name")
        if not name:
            raise ComfyError(f"上传图片失败: {body}")
        return name

    async def get_history(self, prompt_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self.base_url}/history/{prompt_id}")
            resp.raise_for_status()
            return resp.json()

    async def view_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        query = urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{self.base_url}/view?{query}")
            resp.raise_for_status()
            return resp.content

    def _decode_preview(self, raw: bytes) -> bytes | None:
        if len(raw) < 8:
            return None
        event = struct.unpack(">I", raw[:4])[0]
        payload = raw[4:]
        if event == PREVIEW_IMAGE:
            if len(payload) < 4:
                return None
            return payload[4:]
        if event == PREVIEW_IMAGE_WITH_METADATA:
            if len(payload) < 4:
                return None
            meta_len = struct.unpack(">I", payload[:4])[0]
            start = 4 + meta_len
            if start > len(payload):
                return None
            return payload[start:]
        return None

    async def wait_for_prompt(
        self,
        client_id: str,
        prompt_id: str,
        on_progress: Callable[[int, int], Any] | None = None,
        on_preview: Callable[[bytes], Any] | None = None,
    ) -> None:
        uri = f"{self.ws_url}/ws?clientId={client_id}"
        async with websockets.connect(uri, max_size=32 * 1024 * 1024) as ws:
            while True:
                message = await asyncio.wait_for(ws.recv(), timeout=600)
                if isinstance(message, (bytes, bytearray)):
                    preview = self._decode_preview(bytes(message))
                    if preview and on_preview:
                        result = on_preview(preview)
                        if asyncio.iscoroutine(result):
                            await result
                    continue
                data = json.loads(message)
                msg_type = data.get("type")
                payload = data.get("data") or {}
                if payload.get("prompt_id") not in (None, prompt_id) and msg_type != "status":
                    continue
                if msg_type == "progress" and on_progress:
                    result = on_progress(int(payload.get("value") or 0), int(payload.get("max") or 0))
                    if asyncio.iscoroutine(result):
                        await result
                if msg_type == "execution_error" and payload.get("prompt_id") == prompt_id:
                    err = payload.get("exception_message") or payload.get("exception_type") or "ComfyUI 执行失败"
                    raise ComfyError(str(err))
                if msg_type == "execution_interrupted" and payload.get("prompt_id") == prompt_id:
                    raise ComfyError("已停止生成")
                if msg_type == "executing":
                    if payload.get("prompt_id") == prompt_id and payload.get("node") is None:
                        return
                if msg_type == "execution_success" and payload.get("prompt_id") == prompt_id:
                    return


def new_ids() -> tuple[str, str]:
    return str(uuid.uuid4()), str(uuid.uuid4())


async def collect_output_images(client: ComfyClient, prompt_id: str) -> list[bytes]:
    history = await client.get_history(prompt_id)
    record = history.get(prompt_id) or {}
    outputs = record.get("outputs") or {}
    images: list[bytes] = []
    for node_out in outputs.values():
        for image in node_out.get("images") or []:
            images.append(
                await client.view_image(
                    image["filename"],
                    image.get("subfolder") or "",
                    image.get("type") or "output",
                )
            )
    return images
