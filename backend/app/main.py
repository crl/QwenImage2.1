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
from .config import DEFAULT_STEPS, IMAGES_DIR, VIDEO_DURATION_DEFAULT, VIDEO_DURATION_MAX, VIDEO_DURATION_MIN, ensure_dirs
from .generate import display_prompt, edit_preview_image, jobs, run_generation
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


class CanvasIn(BaseModel):
    title: str | None = None


class CanvasPatch(BaseModel):
    title: str | None = None
    viewport: dict[str, float] | None = None


class CanvasItemIn(BaseModel):
    image_id: str | None = None
    node_kind: str = "image"
    title: str | None = None
    x: float
    y: float
    width: float
    height: float


class CanvasItemPatch(BaseModel):
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    z: int | None = None
    image_id: str | None = None
    node_kind: str | None = None
    title: str | None = None


class CanvasEdgeIn(BaseModel):
    from_item_id: str
    to_item_id: str


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
    prompt: str = Form(""),
    aspect: str = Form("1:1"),
    quality: str = Form("1k"),
    transparent: str = Form("false"),
    steps: int = Form(DEFAULT_STEPS),
    media_mode: str = Form("image"),
    video_seconds: int = Form(5),
    chain: str = Form("true"),
    edit_mode: str = Form(""),
    source_image_id: str = Form(""),
    pad_left: int = Form(0),
    pad_top: int = Form(0),
    pad_right: int = Form(0),
    pad_bottom: int = Form(0),
    files: list[UploadFile] | None = File(default=None),
    mask: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    conv = store.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "对话不存在")
    media = (media_mode or "image").strip().lower()
    if media not in {"image", "video"}:
        raise HTTPException(400, "不支持的生成模式")
    duration = int(video_seconds or VIDEO_DURATION_DEFAULT)
    duration = max(VIDEO_DURATION_MIN, min(VIDEO_DURATION_MAX, duration))
    mode = (edit_mode or "").strip().lower()
    if media == "video" and mode:
        raise HTTPException(400, "视频模式不支持图片编辑")
    if mode not in {"", "erase", "outpaint", "enhance"}:
        raise HTTPException(400, "不支持的编辑模式")
    if not prompt.strip() and not mode:
        raise HTTPException(400, "请输入描述")
    if any(m.get("status") == "generating" for m in conv["messages"]):
        raise HTTPException(409, "当前对话正在生成")

    source = None
    if mode:
        if not source_image_id.strip():
            raise HTTPException(400, "缺少要编辑的图片")
        source = store.get_image(source_image_id.strip())
        if not source:
            raise HTTPException(404, "要编辑的图片不存在")
        if mode == "enhance":
            quality = "2k"

    uploaded: list[tuple[str, bytes]] = []
    if not mode:
        for item in (files or [])[:10]:
            data = await item.read()
            if data:
                uploaded.append((item.filename or "upload.png", data))

    mask_bytes: bytes | None = None
    if mask is not None:
        mask_bytes = await mask.read()
        if not mask_bytes:
            mask_bytes = None
    if mode == "erase" and not mask_bytes:
        raise HTTPException(400, "请先涂抹要修改的区域")
    pads = (max(0, pad_left), max(0, pad_top), max(0, pad_right), max(0, pad_bottom))
    if mode == "outpaint" and sum(pads) <= 0:
        raise HTTPException(400, "请先扩展画布")

    is_transparent = transparent.lower() in {"1", "true", "yes", "on"}
    if media == "video":
        is_transparent = False
    use_chain = chain.lower() not in {"0", "false", "no", "off"}
    params = {
        "aspect": aspect,
        "quality": quality,
        "transparent": is_transparent,
        "steps": steps,
        "media_mode": media,
        "video_seconds": duration if media == "video" else None,
        "mode": mode
        or (
            "video"
            if media == "video"
            else ("edit" if uploaded or (use_chain and store.last_output_image(cid)) else "t2i")
        ),
    }
    shown = display_prompt(mode or None, prompt)
    title = shown.replace("\n", " ")[:36]
    if (conv.get("kind") or "chat") != "canvas" and conv["title"] in {"新对话", ""}:
        store.touch_conversation(cid, title)
    else:
        store.touch_conversation(cid)

    user = store.add_message(cid, "user", shown, params=params)
    ref_ids: list[str] = []
    if source:
        preview_record = None
        if mode in {"erase", "outpaint"}:
            source_path = IMAGES_DIR / source["filename"]
            if source_path.exists():
                with Image.open(source_path) as src_img:
                    preview = edit_preview_image(
                        mode,
                        src_img.copy(),
                        mask_bytes=mask_bytes,
                        pads=pads if mode == "outpaint" else None,
                    )
                if preview is not None:
                    filename = f"{uuid.uuid4().hex}.png"
                    preview.save(IMAGES_DIR / filename, format="PNG")
                    preview_record = store.add_image(
                        cid,
                        user["id"],
                        filename,
                        shown,
                        preview.width,
                        preview.height,
                        kind="reference",
                    )
        ref_ids.append((preview_record or source)["id"])
    else:
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
                shown,
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
            edit_mode=mode or None,
            source_image=source,
            mask_bytes=mask_bytes,
            pads=pads if mode == "outpaint" else None,
            media_mode=media,
            video_seconds=duration,
            chain=use_chain,
        )
    )
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return {"user": serialize_message(user), "assistant": serialize_message(assistant)}


def _media_type_for(filename: str, media_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    if media_type == "video" or suffix in {".mp4", ".webm", ".mkv", ".mov"}:
        return {
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
            ".mov": "video/quicktime",
        }.get(suffix, "video/mp4")
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


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


@app.get("/api/canvases")
def list_canvases() -> list[dict[str, Any]]:
    return store.list_canvases()


@app.post("/api/canvases")
def create_canvas(body: CanvasIn | None = None) -> dict[str, Any]:
    title = ((body.title if body else None) or "未命名画布").strip()[:80] or "未命名画布"
    return store.create_canvas(title)


@app.get("/api/canvases/{cid}")
def get_canvas(cid: str) -> dict[str, Any]:
    canvas = store.get_canvas(cid)
    if not canvas:
        raise HTTPException(404, "画布不存在")
    return canvas


@app.patch("/api/canvases/{cid}")
def patch_canvas(cid: str, body: CanvasPatch) -> dict[str, Any]:
    if body.title is None and body.viewport is None:
        canvas = store.get_canvas(cid)
        if not canvas:
            raise HTTPException(404, "画布不存在")
        return canvas
    title = None
    if body.title is not None:
        title = body.title.strip()[:80]
        if not title:
            raise HTTPException(400, "标题不能为空")
    updated = store.update_canvas(cid, title=title, viewport=body.viewport)
    if not updated:
        raise HTTPException(404, "画布不存在")
    return updated


@app.delete("/api/canvases/{cid}")
def delete_canvas(cid: str) -> dict[str, Any]:
    deleted = store.delete_canvas(cid)
    if not deleted:
        raise HTTPException(404, "画布不存在")
    return {"ok": True, "id": cid}


@app.post("/api/canvases/{cid}/items")
def create_canvas_item(cid: str, body: CanvasItemIn) -> dict[str, Any]:
    if body.width <= 0 or body.height <= 0:
        raise HTTPException(400, "卡片尺寸无效")
    kind = "video" if body.node_kind == "video" else "image"
    item = store.add_canvas_item(
        cid,
        body.x,
        body.y,
        body.width,
        body.height,
        image_id=(body.image_id or "").strip() or None,
        node_kind=kind,
        title=body.title,
    )
    if not item:
        raise HTTPException(404, "画布或图片不存在")
    return item


@app.patch("/api/canvases/{cid}/items/{item_id}")
def patch_canvas_item(cid: str, item_id: str, body: CanvasItemPatch) -> dict[str, Any]:
    item = store.update_canvas_item(
        cid,
        item_id,
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
        z=body.z,
        image_id=(body.image_id or "").strip() or None,
        node_kind=body.node_kind,
        title=body.title,
    )
    if not item:
        raise HTTPException(404, "卡片不存在")
    return item


@app.delete("/api/canvases/{cid}/items/{item_id}")
def delete_canvas_item(cid: str, item_id: str) -> dict[str, Any]:
    if not store.delete_canvas_item(cid, item_id):
        raise HTTPException(404, "卡片不存在")
    return {"ok": True, "id": item_id}


@app.post("/api/canvases/{cid}/edges")
def create_canvas_edge(cid: str, body: CanvasEdgeIn) -> dict[str, Any]:
    edge = store.add_canvas_edge(cid, body.from_item_id.strip(), body.to_item_id.strip())
    if not edge:
        raise HTTPException(400, "无法连接这两个节点")
    return edge


@app.delete("/api/canvases/{cid}/edges/{edge_id}")
def delete_canvas_edge(cid: str, edge_id: str) -> dict[str, Any]:
    if not store.delete_canvas_edge(cid, edge_id):
        raise HTTPException(404, "连线不存在")
    return {"ok": True, "id": edge_id}


@app.post("/api/canvases/{cid}/uploads")
async def upload_canvas_media(cid: str, file: UploadFile = File(...)) -> dict[str, Any]:
    canvas = store.get_canvas(cid)
    if not canvas:
        raise HTTPException(404, "画布不存在")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件是空的")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mkv"}:
        suffix = ".png"
    media = "video" if suffix in {".mp4", ".webm", ".mov", ".mkv"} else "image"
    filename = f"{uuid.uuid4().hex}{suffix}"
    (IMAGES_DIR / filename).write_bytes(data)
    width = height = None
    if media == "image":
        try:
            with Image.open(BytesIO(data)) as img:
                width, height = img.size
        except Exception:
            pass
    return store.add_image(
        canvas["conversation_id"],
        None,
        filename,
        Path(file.filename or "upload").stem,
        width,
        height,
        kind="output",
        media_type=media,
    )


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
    return FileResponse(
        path,
        media_type=_media_type_for(record["filename"], record.get("media_type")),
        filename=Path(record["filename"]).name,
    )


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
    media = _media_type_for(record["filename"], record.get("media_type"))
    suffix = Path(record["filename"]).suffix or (".mp4" if record.get("media_type") == "video" else ".png")
    prefix = "qwen-video" if record.get("media_type") == "video" else "qwen-image"
    filename = f"{prefix}-{iid[:8]}{suffix}"
    return FileResponse(
        path,
        media_type=media,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
