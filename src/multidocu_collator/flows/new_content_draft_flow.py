"""保存新增联系单的需求内容草稿，不写入正式归档。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from ..context import AppContext
from ..modules.file_utils import atomic_replace_text
from ..modules.repository import now_iso


DRAFT_LOCK = Lock()
MAX_DRAFT_LENGTH = 4000


def _draft_path(context: AppContext) -> Path:
    return context.project_root / "log" / "new_record_content_draft.json"


def load_new_content_draft(context: AppContext) -> dict[str, Any]:
    """读取与当前资料根目录匹配的新增需求内容草稿。"""
    path = _draft_path(context)
    with DRAFT_LOCK:
        if not path.is_file():
            return {"ok": True, "requirement_content": "", "saved_at": ""}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"临时草稿无法读取: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("data_root") != str(
        context.data_root.resolve()
    ):
        return {"ok": True, "requirement_content": "", "saved_at": ""}
    return {
        "ok": True,
        "requirement_content": str(payload.get("requirement_content") or ""),
        "saved_at": str(payload.get("saved_at") or ""),
    }


def save_new_content_draft(
    context: AppContext, payload: dict[str, Any]
) -> dict[str, Any]:
    """只保存需求内容草稿；不创建资料目录、Word、PDF 或正式记录。"""
    content = str(payload.get("requirement_content") or "")
    if len(content) > MAX_DRAFT_LENGTH:
        raise ValueError(f"临时保存内容不能超过 {MAX_DRAFT_LENGTH} 个字符")
    saved_at = now_iso()
    draft = {
        "data_root": str(context.data_root.resolve()),
        "requirement_content": content,
        "saved_at": saved_at,
    }
    with DRAFT_LOCK:
        atomic_replace_text(
            _draft_path(context),
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
        )
    return {"ok": True, "saved_at": saved_at, "characters": len(content)}


def clear_new_content_draft(context: AppContext) -> None:
    """正式新增成功后保留草稿文件，但清空其中的正文。"""
    save_new_content_draft(context, {"requirement_content": ""})
