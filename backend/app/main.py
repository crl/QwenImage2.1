from __future__ import annotations

import asyncio
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image
from pydantic import BaseModel

from .comfy import ComfyClient
from .config import DEFAULT_STEPS, IMAGES_DIR, ensure_dirs
from .generate import jobs, run_generation
from .hub import EventHub
from .store import Store

ensure_dirs()
store = Store()
hub = EventHub()
comfy = ComfyClient()
_running_tasks: set[asyncio.Task] = set()

app = FastAPI(title="Qwen Image Studio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationIn(BaseModel):
    title: str | None = None


class InterruptIn(BaseModel):
    conversation_id: str | None = None


class ConversationPatch(BaseModel):
    archived: bool | None = None
    title: str | None = None


def serialize_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = dict(message)
    payload["images"] = store.images_for_chat(message.get("image_ids") or [])
    payload["ref_images"] = store.images_for_chat(message.get("ref_image_ids") or [])
    payload["progress"] = message.get("progress") or 0
    payload["progress_max"] = message.get("progress_max") or 0
    return payload


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return await comfy.health()


@app.get("/api/conversations")
def list_conversations(archived: bool = False) -> list[dict[str, Any]]:
    return store.list_conversations(archived=archived)


@app.post("/api/conversations")
def create_conversation(body: ConversationIn | None = None) -> dict[str, Any]:
    title = (body.title if body else None) or "新对话"
    return store.create_conversation(title)


@app.patch("/api/conversations/{cid}")
def patch_conversation(cid: str, body: ConversationPatch) -> dict[str, Any]:
    conv = store.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "对话不存在")
    updated = conv
    if body.title is not None:
        title = body.title.strip()[:80]
        if not title:
            raise HTTPException(400, "标题不能为空")
        renamed = store.rename_conversation(cid, title)
        if not renamed:
            raise HTTPException(404, "对话不存在")
        updated = renamed
    if body.archived is not None:
        archived = store.set_archived(cid, body.archived)
        if not archived:
            raise HTTPException(404, "对话不存在")
        updated = archived
    return updated


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str) -> dict[str, Any]:
    conv = store.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "对话不存在")
    conv["messages"] = [serialize_message(m) for m in conv["messages"]]
    return conv


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> dict[str, Any]:
    record = store.get_conversation(cid)
    if not record:
        raise HTTPException(404, "对话不存在")
    deleted = store.delete_conversation(cid)
    jobs.pop(cid, None)
    for image in (deleted or {}).get("images") or []:
        filename = image.get("filename")
        if not filename:
            continue
        path = IMAGES_DIR / filename
        if path.exists():
            path.unlink()
    return {"ok": True, "id": cid}


@app.post("/api/conversations/{cid}/messages")
async def send_message(
    cid: str,
    prompt: str = Form(...),
    aspect: str = Form("1:1"),
    quality: str = Form("1k"),
    transparent: str = Form("false"),
    steps: int = Form(DEFAULT_STEPS),
    files: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    conv = store.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "对话不存在")
    if not prompt.strip():
        raise HTTPException(400, "请输入描述")
    if any(m.get("status") == "generating" for m in conv["messages"]):
        raise HTTPException(409, "当前对话正在生成")

    uploaded: list[tuple[str, bytes]] = []
    for item in (files or [])[:10]:
        data = await item.read()
        if data:
            uploaded.append((item.filename or "upload.png", data))

    is_transparent = transparent.lower() in {"1", "true", "yes", "on"}
    params = {
        "aspect": aspect,
        "quality": quality,
        "transparent": is_transparent,
        "steps": steps,
        "mode": "edit" if uploaded or store.last_output_image(cid) else "t2i",
    }
    title = prompt.strip().replace("\n", " ")[:36]
    if conv["title"] in {"新对话", ""}:
        store.touch_conversation(cid, title)
    else:
        store.touch_conversation(cid)

    user = store.add_message(cid, "user", prompt.strip(), params=params)
    ref_ids: list[str] = []
    for original_name, data in uploaded:
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            suffix = ".png"
        filename = f"{uuid.uuid4().hex}{suffix}"
        (IMAGES_DIR / filename).write_bytes(data)
        width = height = None
        try:
            with Image.open(BytesIO(data)) as img:
                width, height = img.size
        except Exception:
            pass
        record = store.add_image(
            cid,
            user["id"],
            filename,
            prompt.strip(),
            width,
            height,
            kind="reference",
        )
        ref_ids.append(record["id"])
    if ref_ids:
        updated = store.update_message(user["id"], ref_image_ids=ref_ids)
        if updated:
            user = updated
    assistant = store.add_message(
        cid,
        "assistant",
        "",
        params=params,
        status="generating",
    )
    task = asyncio.create_task(
        run_generation(
            store=store,
            hub=hub,
            client=comfy,
            conversation_id=cid,
            message_id=assistant["id"],
            prompt=prompt.strip(),
            aspect=aspect,
            quality=quality,
            transparent=is_transparent,
            steps=int(steps),
            uploaded=uploaded,
        )
    )
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return {"user": serialize_message(user), "assistant": serialize_message(assistant)}


@app.get("/api/conversations/{cid}/events")
async def conversation_events(cid: str, request: Request) -> StreamingResponse:
    if not store.get_conversation(cid):
        raise HTTPException(404, "对话不存在")
    queue = hub.subscribe(cid)

    async def stream():
        try:
            conv = store.get_conversation(cid)
            if conv:
                yield hub.format_sse(
                    {
                        "type": "snapshot",
                        "conversation": {
                            **conv,
                            "messages": [serialize_message(m) for m in conv["messages"]],
                        },
                    }
                )
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield hub.format_sse(event)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(cid, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/interrupt")
async def interrupt(body: InterruptIn | None = None) -> dict[str, str]:
    cid = body.conversation_id if body else None
    await comfy.interrupt()
    if cid:
        jobs.pop(cid, None)
        conv = store.get_conversation(cid)
        if conv:
            for message in conv["messages"]:
                if message.get("status") == "generating":
                    store.update_message(message["id"], status="error", error="已停止生成")
    return {"status": "ok"}


@app.get("/api/library")
def library() -> list[dict[str, Any]]:
    return store.list_library()


@app.get("/api/images/{iid}")
def get_image(iid: str) -> FileResponse:
    record = store.get_image(iid)
    if not record:
        raise HTTPException(404, "图片不存在")
    path = IMAGES_DIR / record["filename"]
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, media_type="image/png", filename=Path(record["filename"]).name)


@app.delete("/api/images/{iid}")
def delete_image(iid: str) -> dict[str, Any]:
    record = store.get_image(iid)
    if not record:
        raise HTTPException(404, "图片不存在")
    store.delete_image(iid)
    path = IMAGES_DIR / record["filename"]
    if path.exists():
        path.unlink()
    return {"ok": True, "id": iid}


@app.post("/api/images/{iid}/hide")
def hide_image(iid: str) -> dict[str, Any]:
    record = store.get_image(iid)
    if not record:
        raise HTTPException(404, "图片不存在")
    store.hide_image_from_chat(iid)
    return {"ok": True, "id": iid}


@app.get("/api/images/{iid}/download")
def download_image(iid: str) -> FileResponse:
    record = store.get_image(iid)
    if not record:
        raise HTTPException(404, "图片不存在")
    path = IMAGES_DIR / record["filename"]
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"qwen-image-{iid[:8]}.png",
        headers={"Content-Disposition": f'attachment; filename="qwen-image-{iid[:8]}.png"'},
    )
