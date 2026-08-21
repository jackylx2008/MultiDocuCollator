"""保存 HTML 中人工填写的需求单打印标记。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..context import AppContext
from ..modules.repository import load_dataset, now_iso, save_dataset
from ..modules.summary_html import export_summary_html
from .mutation_lock import RECORD_MUTATION_LOCK


PRINT_STATUS_FIELD = "需求单已经打印"
VALID_PRINT_STATUSES = {"是", "否"}


def update_print_statuses(
    context: AppContext, payload: dict[str, Any]
) -> dict[str, Any]:
    """按 record_id 批量保存打印标记，并同步重新生成 HTML。"""
    with RECORD_MUTATION_LOCK:
        data = load_dataset(context.json_path)
        if data is None:
            raise FileNotFoundError("JSON 数据库不存在，请先运行 build_archive.py")

        requested_revision = int(payload.get("dataset_revision") or 0)
        current_revision = int(data.get("dataset_revision") or 0)
        if requested_revision != current_revision:
            raise ValueError("页面数据已经更新，请刷新页面后重新操作")

        statuses = payload.get("statuses")
        if not isinstance(statuses, dict):
            raise ValueError("statuses 必须是以 record_id 为键的 JSON 对象")

        records = data.get("records") or []
        record_map = {str(item.get("record_id") or ""): item for item in records}
        if any(str(key) not in record_map for key in statuses):
            raise ValueError("存在无效或已删除的记录，请刷新页面后重新操作")

        normalized: dict[str, str] = {}
        for raw_record_id, raw_status in statuses.items():
            record_id = str(raw_record_id)
            if raw_status not in VALID_PRINT_STATUSES:
                raise ValueError(f"打印标记只能是“是”或“否”: {record_id}")
            normalized[record_id] = str(raw_status)

        changed_ids = [
            record_id
            for record_id, status in normalized.items()
            if record_map[record_id].get(PRINT_STATUS_FIELD) != status
        ]
        if not changed_ids:
            return {"ok": True, "changed": 0, "dataset_revision": current_revision}

        original = deepcopy(data)
        timestamp = now_iso()
        for record_id in changed_ids:
            record_map[record_id][PRINT_STATUS_FIELD] = normalized[record_id]
        data["dataset_revision"] = current_revision + 1
        data["updated_at"] = timestamp
        changes = list(data.get("changes") or [])
        changes.extend(
            {
                "at": timestamp,
                "action": "print_status_updated",
                "record_id": record_id,
                "value": normalized[record_id],
            }
            for record_id in changed_ids
        )
        data["changes"] = changes[-1000:]

        save_dataset(context.json_path, data)
        try:
            export_summary_html(data, context.html_path)
        except Exception:
            save_dataset(context.json_path, original)
            raise
        return {
            "ok": True,
            "changed": len(changed_ids),
            "dataset_revision": int(data["dataset_revision"]),
        }
