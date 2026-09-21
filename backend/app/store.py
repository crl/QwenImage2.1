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

    def _loads_message(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        data = _row_to_dict(row)
        if not data:
            return None
        data["image_ids"] = json.loads(data["image_ids"] or "[]")
        data["ref_image_ids"] = json.loads(data["ref_image_ids"] or "[]")
        data["params"] = json.loads(data["params"] or "{}")
        return data

    def create_conversation(self, title: str = "新对话") -> dict[str, Any]:
        cid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, title, now, now),
            )
        return {"id": cid, "title": title, "created_at": now, "updated_at": now, "archived": False}

    def _summary(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["archived"] = bool(data.get("archived_at"))
        return data

    def list_conversations(self, archived: bool = False) -> list[dict[str, Any]]:
        clause = "archived_at IS NOT NULL" if archived else "archived_at IS NULL"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM conversations WHERE {clause} ORDER BY updated_at DESC"
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
    ) -> dict[str, Any]:
        iid = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO images (
                    id, conversation_id, message_id, filename, prompt, width, height, created_at, kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (iid, conversation_id, message_id, filename, prompt, width, height, now, kind),
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

    def delete_image(self, iid: str) -> dict[str, Any] | None:
        record = self.get_image(iid)
        if not record:
            return None
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM images WHERE id = ?", (iid,))
        return record
