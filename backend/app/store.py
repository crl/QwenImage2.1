from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_dirs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class Store:
    def __init__(self, path: Path = DB_PATH) -> None:
        ensure_dirs()
        self.path = path
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_ids TEXT NOT NULL DEFAULT '[]',
                    ref_image_ids TEXT NOT NULL DEFAULT '[]',
                    params TEXT NOT NULL DEFAULT '{}',
                    status TEXT,
                    progress INTEGER DEFAULT 0,
                    progress_max INTEGER DEFAULT 0,
                    preview TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT,
                    filename TEXT NOT NULL,
                    prompt TEXT,
                    width INTEGER,
                    height INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                """
            )
            cols = [row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()]
            if "archived_at" not in cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN archived_at TEXT")
            image_cols = [row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()]
            if "kind" not in image_cols:
                conn.execute("ALTER TABLE images ADD COLUMN kind TEXT NOT NULL DEFAULT 'output'")
            if "hidden_in_chat" not in image_cols:
                conn.execute("ALTER TABLE images ADD COLUMN hidden_in_chat INTEGER NOT NULL DEFAULT 0")
            image_cols = [row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()]
            if "media_type" not in image_cols:
                conn.execute("ALTER TABLE images ADD COLUMN media_type TEXT NOT NULL DEFAULT 'image'")
            conv_cols = [row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()]
            if "kind" not in conv_cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS canvases (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    viewport TEXT NOT NULL DEFAULT '{"x":0,"y":0,"scale":1}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS canvas_items (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL,
                    image_id TEXT,
                    node_kind TEXT NOT NULL DEFAULT 'image',
                    title TEXT NOT NULL DEFAULT '',
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    width REAL NOT NULL,
                    height REAL NOT NULL,
                    z INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE,
                    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE SET NULL
                );
                """
            )
            item_info = list(conn.execute("PRAGMA table_info(canvas_items)"))
            item_cols = {row[1]: row for row in item_info}
            image_notnull = item_cols.get("image_id") is not None and item_cols["image_id"][3] == 1
            if "node_kind" not in item_cols or image_notnull:
                conn.execute("DROP TABLE IF EXISTS canvas_edges")
                conn.execute("ALTER TABLE canvas_items RENAME TO canvas_items_old")
                conn.execute(
                    """
                    CREATE TABLE canvas_items (
                        id TEXT PRIMARY KEY,
                        canvas_id TEXT NOT NULL,
                        image_id TEXT,
                        node_kind TEXT NOT NULL DEFAULT 'image',
                        title TEXT NOT NULL DEFAULT '',
                        x REAL NOT NULL,
                        y REAL NOT NULL,
                        width REAL NOT NULL,
                        height REAL NOT NULL,
                        z INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE,
                        FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE SET NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO canvas_items (
                        id, canvas_id, image_id, node_kind, title, x, y, width, height, z, created_at
                    )
                    SELECT id, canvas_id, image_id, 'image', '', x, y, width, height, z, created_at
                    FROM canvas_items_old
                    """
                )
                conn.execute("DROP TABLE canvas_items_old")
            edge_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'canvas_edges'"
            ).fetchone()
            edge_tables = (
                {row[2] for row in conn.execute("PRAGMA foreign_key_list(canvas_edges)")} if edge_exists else set()
            )
            if "canvas_items" not in edge_tables:
                conn.execute("DROP TABLE IF EXISTS canvas_edges")
                conn.execute(
                    """
                    CREATE TABLE canvas_edges (
                        id TEXT PRIMARY KEY,
                        canvas_id TEXT NOT NULL,
                        from_item_id TEXT NOT NULL,
                        to_item_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE,
                        FOREIGN KEY (from_item_id) REFERENCES canvas_items(id) ON DELETE CASCADE,
                        FOREIGN KEY (to_item_id) REFERENCES canvas_items(id) ON DELETE CASCADE
                    )
                    """
                )
            blanks = conn.execute(
                """
                SELECT id, canvas_id, node_kind FROM canvas_items
                WHERE TRIM(title) = ''
                ORDER BY canvas_id, created_at
                """
            ).fetchall()
            for row in blanks:
                kind = "video" if row["node_kind"] == "video" else "image"
                prefix = "视频" if kind == "video" else "图片"
                taken = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM canvas_items
                    WHERE canvas_id = ? AND node_kind = ? AND TRIM(title) != ''
                    """,
                    (row["canvas_id"], kind),
                ).fetchone()
                conn.execute(
                    "UPDATE canvas_items SET title = ? WHERE id = ?",
                    (f"{prefix} {int(taken['n']) + 1}", row["id"]),
                )

    def _loads_message(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        data = _row_to_dict(row)
        if not data:
            return None
        data["image_ids"] = json.loads(data["image_ids"] or "[]")
        data["ref_image_ids"] = json.loads(data["ref_image_ids"] or "[]")
        data["params"] = json.loads(data["params"] or "{}")
        return data

    def create_conversation(self, title: str = "新对话", kind: str = "chat") -> dict[str, Any]:
        cid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, kind) VALUES (?, ?, ?, ?, ?)",
                (cid, title, now, now, kind),
            )
        return {
            "id": cid,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "archived": False,
            "kind": kind,
        }

    def _summary(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["archived"] = bool(data.get("archived_at"))
        return data

    def list_conversations(self, archived: bool = False) -> list[dict[str, Any]]:
        archived_sql = "archived_at IS NOT NULL" if archived else "archived_at IS NULL"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM conversations
                WHERE {archived_sql} AND IFNULL(kind, 'chat') = 'chat'
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._summary(r) for r in rows]

    def set_archived(self, cid: str, archived: bool) -> dict[str, Any] | None:
        value = _now() if archived else None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET archived_at = ? WHERE id = ?",
                (value, cid),
            )
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        return self._summary(row) if row else None

    def list_images_for_conversation(self, cid: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM images WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        return [dict(row) | {"url": f"/api/images/{row['id']}"} for row in rows]

    def delete_conversation(self, cid: str) -> dict[str, Any] | None:
        conv = self.get_conversation(cid)
        if not conv:
            return None
        images = self.list_images_for_conversation(cid)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        conv["images"] = images
        return conv

    def get_conversation(self, cid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
            if not row:
                return None
            msgs = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (cid,),
            ).fetchall()
        conv = self._summary(row)
        conv["messages"] = [self._loads_message(m) for m in msgs]
        return conv

    def touch_conversation(self, cid: str, title: str | None = None) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            if title:
                conn.execute(
                    "UPDATE conversations SET updated_at = ?, title = ? WHERE id = ?",
                    (now, title, cid),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, cid),
                )

    def rename_conversation(self, cid: str, title: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, cid))
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        return self._summary(row) if row else None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        image_ids: list[str] | None = None,
        ref_image_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        mid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, image_ids, ref_image_ids,
                    params, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    conversation_id,
                    role,
                    content,
                    json.dumps(image_ids or []),
                    json.dumps(ref_image_ids or []),
                    json.dumps(params or {}),
                    status,
                    now,
                ),
            )
        self.touch_conversation(conversation_id)
        msg = self.get_message(mid)
        assert msg is not None
        return msg

    def get_message(self, mid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        return self._loads_message(row)

    def update_message(self, mid: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get_message(mid)
        allowed = {
            "content",
            "image_ids",
            "ref_image_ids",
            "status",
            "progress",
            "progress_max",
            "preview",
            "error",
        }
        sets = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"image_ids", "ref_image_ids"}:
                value = json.dumps(value)
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get_message(mid)
        values.append(mid)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id = ?", values)
        return self.get_message(mid)

    def last_output_image(self, cid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM images
                WHERE conversation_id = ?
                  AND IFNULL(kind, 'output') = 'output'
                  AND IFNULL(hidden_in_chat, 0) = 0
                  AND IFNULL(media_type, 'image') = 'image'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (cid,),
            ).fetchone()
        return _row_to_dict(row)

    def add_image(
        self,
        conversation_id: str,
        message_id: str | None,
        filename: str,
        prompt: str,
        width: int | None,
        height: int | None,
        kind: str = "output",
        media_type: str = "image",
    ) -> dict[str, Any]:
        iid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO images (
                    id, conversation_id, message_id, filename, prompt, width, height, created_at, kind, media_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (iid, conversation_id, message_id, filename, prompt, width, height, now, kind, media_type),
            )
        return {
            "id": iid,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "filename": filename,
            "prompt": prompt,
            "width": width,
            "height": height,
            "created_at": now,
            "kind": kind,
            "media_type": media_type,
            "url": f"/api/images/{iid}",
        }

    def get_image(self, iid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM images WHERE id = ?", (iid,)).fetchone()
        data = _row_to_dict(row)
        if data:
            data["url"] = f"/api/images/{iid}"
        return data

    def list_library(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM images WHERE IFNULL(kind, 'output') = 'output' ORDER BY created_at DESC"
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["url"] = f"/api/images/{item['id']}"
            items.append(item)
        return items

    def images_for_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM images WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        by_id = {r["id"]: dict(r) | {"url": f"/api/images/{r['id']}"} for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def images_for_chat(self, ids: list[str]) -> list[dict[str, Any]]:
        found = {item["id"]: item for item in self.images_for_ids(ids)}
        items: list[dict[str, Any]] = []
        for iid in ids:
            item = found.get(iid)
            if item is None or item.get("hidden_in_chat"):
                items.append(
                    {
                        "id": iid,
                        "conversation_id": (item or {}).get("conversation_id") or "",
                        "message_id": (item or {}).get("message_id"),
                        "filename": "",
                        "prompt": (item or {}).get("prompt"),
                        "width": (item or {}).get("width"),
                        "height": (item or {}).get("height"),
                        "created_at": (item or {}).get("created_at") or "",
                        "url": "",
                        "deleted": True,
                    }
                )
            else:
                items.append(item | {"deleted": False})
        return items

    def hide_image_from_chat(self, iid: str) -> dict[str, Any] | None:
        record = self.get_image(iid)
        if not record:
            return None
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE images SET hidden_in_chat = 1 WHERE id = ?", (iid,))
        record["hidden_in_chat"] = 1
        record["deleted"] = True
        return record

    def _viewport(self, raw: str | None) -> dict[str, float]:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        scale = float(data.get("scale") or 1)
        return {
            "x": float(data.get("x") or 0),
            "y": float(data.get("y") or 0),
            "scale": min(3.0, max(0.15, scale)),
        }

    def _canvas_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["viewport"] = self._viewport(data.get("viewport"))
        return data

    def list_canvases(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM canvases ORDER BY updated_at DESC").fetchall()
        return [self._canvas_row(row) for row in rows]

    def create_canvas(self, title: str = "未命名画布") -> dict[str, Any]:
        conv = self.create_conversation(title, kind="canvas")
        cid = str(uuid.uuid4())
        now = _now()
        viewport = json.dumps({"x": 0, "y": 0, "scale": 1})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO canvases (id, title, conversation_id, viewport, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cid, title, conv["id"], viewport, now, now),
            )
        canvas = self.get_canvas(cid)
        assert canvas is not None
        return canvas

    def get_canvas(self, cid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM canvases WHERE id = ?", (cid,)).fetchone()
            if not row:
                return None
            items = conn.execute(
                """
                SELECT canvas_items.*, images.filename, images.prompt, images.width AS image_width,
                       images.height AS image_height, images.created_at AS image_created_at,
                       images.conversation_id AS image_conversation_id, images.message_id,
                       images.kind, images.media_type, images.hidden_in_chat
                FROM canvas_items
                LEFT JOIN images ON images.id = canvas_items.image_id
                WHERE canvas_items.canvas_id = ?
                ORDER BY canvas_items.z ASC, canvas_items.created_at ASC
                """,
                (cid,),
            ).fetchall()
            edges = conn.execute(
                "SELECT * FROM canvas_edges WHERE canvas_id = ? ORDER BY created_at ASC",
                (cid,),
            ).fetchall()
        canvas = self._canvas_row(row)
        packed = []
        for item in items:
            data = dict(item)
            image = None
            if data.get("image_id") and data.get("filename"):
                image = {
                    "id": data["image_id"],
                    "conversation_id": data["image_conversation_id"],
                    "message_id": data["message_id"],
                    "filename": data["filename"],
                    "prompt": data["prompt"],
                    "width": data["image_width"],
                    "height": data["image_height"],
                    "created_at": data["image_created_at"],
                    "kind": data.get("kind") or "output",
                    "media_type": data.get("media_type") or "image",
                    "hidden_in_chat": data.get("hidden_in_chat") or 0,
                    "url": f"/api/images/{data['image_id']}",
                }
            packed.append(
                {
                    "id": data["id"],
                    "canvas_id": data["canvas_id"],
                    "image_id": data.get("image_id"),
                    "node_kind": data.get("node_kind") or "image",
                    "title": data.get("title") or "",
                    "x": data["x"],
                    "y": data["y"],
                    "width": data["width"],
                    "height": data["height"],
                    "z": data["z"],
                    "created_at": data["created_at"],
                    "image": image,
                }
            )
        canvas["items"] = packed
        canvas["edges"] = [dict(edge) for edge in edges]
        return canvas

    def update_canvas(
        self,
        cid: str,
        *,
        title: str | None = None,
        viewport: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        sets = []
        values: list[Any] = []
        if title is not None:
            sets.append("title = ?")
            values.append(title)
        if viewport is not None:
            sets.append("viewport = ?")
            values.append(json.dumps(self._viewport(json.dumps(viewport))))
        if not sets:
            return self.get_canvas(cid)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(cid)
        with self._lock, self._connect() as conn:
            cur = conn.execute(f"UPDATE canvases SET {', '.join(sets)} WHERE id = ?", values)
            if cur.rowcount == 0:
                return None
        return self.get_canvas(cid)

    def delete_canvas(self, cid: str) -> dict[str, Any] | None:
        canvas = self.get_canvas(cid)
        if not canvas:
            return None
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM canvases WHERE id = ?", (cid,))
        return canvas

    def add_canvas_item(
        self,
        canvas_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        image_id: str | None = None,
        node_kind: str = "image",
        title: str | None = None,
    ) -> dict[str, Any] | None:
        kind = "video" if node_kind == "video" else "image"
        if image_id:
            image = self.get_image(image_id)
            if not image:
                return None
            if image.get("media_type") == "video":
                kind = "video"
        iid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            exists = conn.execute("SELECT id FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
            if not exists:
                return None
            zrow = conn.execute(
                "SELECT COALESCE(MAX(z), 0) + 1 AS z FROM canvas_items WHERE canvas_id = ?",
                (canvas_id,),
            ).fetchone()
            z = int(zrow["z"])
            label = (title or "").strip()
            if not label:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM canvas_items WHERE canvas_id = ? AND node_kind = ?",
                    (canvas_id, kind),
                ).fetchone()
                label = f"{'视频' if kind == 'video' else '图片'} {int(count['n']) + 1}"
            conn.execute(
                """
                INSERT INTO canvas_items (
                    id, canvas_id, image_id, node_kind, title, x, y, width, height, z, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (iid, canvas_id, image_id, kind, label, x, y, width, height, z, now),
            )
            conn.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))
        canvas = self.get_canvas(canvas_id)
        if not canvas:
            return None
        for item in canvas["items"]:
            if item["id"] == iid:
                return item
        return None

    def update_canvas_item(self, canvas_id: str, item_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"x", "y", "width", "height", "z", "image_id", "node_kind", "title"}
        sets = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            canvas = self.get_canvas(canvas_id)
            if not canvas:
                return None
            return next((item for item in canvas["items"] if item["id"] == item_id), None)
        values.extend([item_id, canvas_id])
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"UPDATE canvas_items SET {', '.join(sets)} WHERE id = ? AND canvas_id = ?",
                values,
            )
            if cur.rowcount == 0:
                return None
            conn.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (_now(), canvas_id))
        canvas = self.get_canvas(canvas_id)
        if not canvas:
            return None
        return next((item for item in canvas["items"] if item["id"] == item_id), None)

    def delete_canvas_item(self, canvas_id: str, item_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM canvas_items WHERE id = ? AND canvas_id = ?",
                (item_id, canvas_id),
            )
            if cur.rowcount == 0:
                return False
            conn.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (_now(), canvas_id))
        return True

    def add_canvas_edge(self, canvas_id: str, from_item_id: str, to_item_id: str) -> dict[str, Any] | None:
        if from_item_id == to_item_id:
            return None
        eid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM canvas_items WHERE canvas_id = ? AND id IN (?, ?)",
                (canvas_id, from_item_id, to_item_id),
            ).fetchall()
            if len(rows) != 2:
                return None
            existing = conn.execute(
                """
                SELECT id FROM canvas_edges
                WHERE canvas_id = ? AND from_item_id = ? AND to_item_id = ?
                """,
                (canvas_id, from_item_id, to_item_id),
            ).fetchone()
            if existing:
                return dict(existing) | {
                    "canvas_id": canvas_id,
                    "from_item_id": from_item_id,
                    "to_item_id": to_item_id,
                }
            conn.execute(
                """
                INSERT INTO canvas_edges (id, canvas_id, from_item_id, to_item_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (eid, canvas_id, from_item_id, to_item_id, now),
            )
        return {
            "id": eid,
            "canvas_id": canvas_id,
            "from_item_id": from_item_id,
            "to_item_id": to_item_id,
            "created_at": now,
        }

    def delete_canvas_edge(self, canvas_id: str, edge_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM canvas_edges WHERE id = ? AND canvas_id = ?",
                (edge_id, canvas_id),
            )
            if cur.rowcount == 0:
                return False
            conn.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (_now(), canvas_id))
        return True

    def delete_image(self, iid: str) -> dict[str, Any] | None:
        record = self.get_image(iid)
        if not record:
            return None
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM images WHERE id = ?", (iid,))
        return record
