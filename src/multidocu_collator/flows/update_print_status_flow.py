"""保存 HTML 中人工填写的联系单状态标记。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..context import AppContext
from ..modules.repository import load_dataset, now_iso, save_dataset
from ..modules.summary_html import export_summary_html
from .mutation_lock import RECORD_MUTATION_LOCK


PRINT_STATUS_FIELD = "需求单已经打印"
VOID_STATUS_FIELD = "作废状态"
CHANGE_REQUIRED_FIELD = "是否需要变更"
SITE_COMPLETED_FIELD = "现场是否已经完成"
VALID_PRINT_STATUSES = {"是", "否"}
VALID_VOID_STATUSES = {"是", "否"}
VALID_CHANGE_STATUSES = {"是", "否"}
VALID_COMPLETED_STATUSES = {"是", "否"}


def update_print_statuses(
    context: AppContext, payload: dict[str, Any]
) -> dict[str, Any]:
    """按 record_id 批量保存人工状态标记，并同步重新生成 HTML。"""
    with RECORD_MUTATION_LOCK:
        data = load_dataset(context.json_path)
        if data is None:
            raise FileNotFoundError("JSON 数据库不存在，请先运行 build_archive.py")

        requested_revision = int(payload.get("dataset_revision") or 0)
        current_revision = int(data.get("dataset_revision") or 0)
        if requested_revision != current_revision:
            raise ValueError("页面数据已经更新，请刷新页面后重新操作")

        statuses = payload.get("statuses", {})
        if not isinstance(statuses, dict):
            raise ValueError("statuses 必须是以 record_id 为键的 JSON 对象")
        void_statuses = payload.get("void_statuses", {})
        if not isinstance(void_statuses, dict):
            raise ValueError("void_statuses 必须是以 record_id 为键的 JSON 对象")
        change_required = payload.get("change_required", {})
        if not isinstance(change_required, dict):
            raise ValueError("change_required 必须是以 record_id 为键的 JSON 对象")
        site_completed = payload.get("site_completed", {})
        if not isinstance(site_completed, dict):
            raise ValueError("site_completed 必须是以 record_id 为键的 JSON 对象")

        records = data.get("records") or []
        record_map = {str(item.get("record_id") or ""): item for item in records}
        if any(
            str(key) not in record_map
            for key in (
                *statuses.keys(),
                *void_statuses.keys(),
                *change_required.keys(),
                *site_completed.keys(),
            )
        ):
            raise ValueError("存在无效或已删除的记录，请刷新页面后重新操作")

        normalized: dict[str, str] = {}
        for raw_record_id, raw_status in statuses.items():
            record_id = str(raw_record_id)
            if raw_status not in VALID_PRINT_STATUSES:
                raise ValueError(f"打印标记只能是“是”或“否”: {record_id}")
            normalized[record_id] = str(raw_status)

        normalized_void: dict[str, str] = {}
        for raw_record_id, raw_status in void_statuses.items():
            record_id = str(raw_record_id)
            if raw_status not in VALID_VOID_STATUSES:
                raise ValueError(f"作废状态只能是“是”或“否”: {record_id}")
            normalized_void[record_id] = str(raw_status)

        normalized_change: dict[str, str] = {}
        for raw_record_id, raw_status in change_required.items():
            record_id = str(raw_record_id)
            if raw_status not in VALID_CHANGE_STATUSES:
                raise ValueError(f"是否需要变更只能是“是”或“否”: {record_id}")
            normalized_change[record_id] = str(raw_status)

        normalized_completed: dict[str, str] = {}
        for raw_record_id, raw_status in site_completed.items():
            record_id = str(raw_record_id)
            if raw_status not in VALID_COMPLETED_STATUSES:
                raise ValueError(f"现场是否已经完成只能是“是”或“否”: {record_id}")
            normalized_completed[record_id] = str(raw_status)

        changed_ids = [
            record_id
            for record_id, status in normalized.items()
            if record_map[record_id].get(PRINT_STATUS_FIELD) != status
        ]
        changed_void_ids = [
            record_id
            for record_id, status in normalized_void.items()
            if record_map[record_id].get(VOID_STATUS_FIELD) != status
        ]
        changed_change_ids = [
            record_id
            for record_id, status in normalized_change.items()
            if record_map[record_id].get(CHANGE_REQUIRED_FIELD, "否") != status
        ]
        changed_completed_ids = [
            record_id
            for record_id, status in normalized_completed.items()
            if record_map[record_id].get(SITE_COMPLETED_FIELD, "否") != status
        ]
        if not changed_ids and not changed_void_ids and not changed_change_ids and not changed_completed_ids:
            return {"ok": True, "changed": 0, "dataset_revision": current_revision}

        original = deepcopy(data)
        timestamp = now_iso()
        for record_id in changed_ids:
            record_map[record_id][PRINT_STATUS_FIELD] = normalized[record_id]
        for record_id in changed_void_ids:
            record_map[record_id][VOID_STATUS_FIELD] = normalized_void[record_id]
        for record_id in changed_change_ids:
            record_map[record_id][CHANGE_REQUIRED_FIELD] = normalized_change[record_id]
        for record_id in changed_completed_ids:
            record_map[record_id][SITE_COMPLETED_FIELD] = normalized_completed[record_id]
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
        changes.extend(
            {
                "at": timestamp,
                "action": "void_status_updated",
                "record_id": record_id,
                "value": normalized_void[record_id],
            }
            for record_id in changed_void_ids
        )
        changes.extend(
            {
                "at": timestamp,
                "action": "change_required_updated",
                "record_id": record_id,
                "value": normalized_change[record_id],
            }
            for record_id in changed_change_ids
        )
        changes.extend(
            {
                "at": timestamp,
                "action": "site_completed_updated",
                "record_id": record_id,
                "value": normalized_completed[record_id],
            }
            for record_id in changed_completed_ids
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
            "changed": (
                len(changed_ids)
                + len(changed_void_ids)
                + len(changed_change_ids)
                + len(changed_completed_ids)
            ),
            "changed_print": len(changed_ids),
            "changed_void": len(changed_void_ids),
            "changed_change_required": len(changed_change_ids),
            "changed_site_completed": len(changed_completed_ids),
            "dataset_revision": int(data["dataset_revision"]),
        }
