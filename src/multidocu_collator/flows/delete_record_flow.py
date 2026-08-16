"""将联系单目录移入同级 _trash，并刷新 JSON/HTML。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..constants import TRASH_DIRECTORY_NAME
from ..context import AppContext
from ..modules.desktop import resolve_relative_directory
from ..modules.repository import load_dataset
from .build_archive_flow import run_build_archive
from .mutation_lock import RECORD_MUTATION_LOCK


def _trash_destination(trash_root: Path, original_name: str) -> Path:
    preferred = trash_root / original_name
    if not preferred.exists():
        return preferred
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    candidate = trash_root / f"{original_name}__{timestamp}"
    counter = 2
    while candidate.exists():
        candidate = trash_root / f"{original_name}__{timestamp}_{counter}"
        counter += 1
    return candidate


def delete_record(context: AppContext, payload: dict[str, Any]) -> dict[str, Any]:
    """执行可恢复删除；任何刷新错误都会把目录移回原位置。"""
    with RECORD_MUTATION_LOCK:
        data = load_dataset(context.json_path)
        if data is None:
            raise FileNotFoundError("JSON 数据库不存在，请先运行 build_archive.py")
        requested_revision = int(payload.get("dataset_revision") or 0)
        current_revision = int(data.get("dataset_revision") or 0)
        if requested_revision != current_revision:
            raise ValueError("页面数据已经更新，请刷新页面后重新操作")
        record_id = str(payload.get("record_id") or "").strip()
        folder_path = str(payload.get("folder_path") or "").strip()
        record = next(
            (
                item
                for item in data.get("records") or []
                if item.get("record_id") == record_id
            ),
            None,
        )
        if record is None:
            raise ValueError("待删除记录不存在或已被删除")
        if not folder_path or record.get("folder_path") != folder_path:
            raise ValueError("记录目录与当前 JSON 数据不一致")

        unresolved_source = context.data_root / folder_path
        if unresolved_source.is_symlink():
            raise ValueError("不允许通过符号链接删除资料目录")
        source = resolve_relative_directory(context.data_root, folder_path)
        if source.parent != context.data_root.resolve():
            raise ValueError("只允许删除资料根目录下的一级联系单目录")
        trash_root = context.data_root / TRASH_DIRECTORY_NAME
        trash_root.mkdir(exist_ok=True)
        destination = _trash_destination(trash_root, source.name)
        source.replace(destination)
        try:
            run_build_archive(context)
        except Exception:
            if destination.exists() and not source.exists():
                destination.replace(source)
            raise
        refreshed = load_dataset(context.json_path) or {}
        return {
            "ok": True,
            "record_id": record_id,
            "trash_path": destination.relative_to(context.data_root).as_posix(),
            "dataset_revision": int(refreshed.get("dataset_revision") or 0),
        }
