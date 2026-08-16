"""JSON 正式数据的加载与原子保存。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from multidocu_collator.constants import SCHEMA_VERSION

from .file_utils import atomic_replace_text


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_dataset(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 数据库根节点必须是对象")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"不支持的数据版本 {data.get('schema_version')}，当前为 {SCHEMA_VERSION}"
        )
    return data


def _record_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["record_id"]): item for item in records}


def build_dataset(
    *,
    root: Path,
    records: list[dict[str, Any]],
    unmatched_files: list[dict[str, str]],
    ignored_files: list[str],
    previous: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool, dict[str, int]]:
    timestamp = now_iso()
    previous_records = (previous or {}).get("records") or []
    old_map = _record_map(previous_records)
    new_map = _record_map(records)
    added = len(new_map.keys() - old_map.keys())
    removed = len(old_map.keys() - new_map.keys())
    updated = sum(
        1 for key in new_map.keys() & old_map.keys() if new_map[key] != old_map[key]
    )
    unchanged = len(new_map) - added - updated
    changed = bool(
        added
        or removed
        or updated
        or (previous or {}).get("unmatched_files", []) != unmatched_files
    )
    revision = int((previous or {}).get("dataset_revision") or 0)
    if changed:
        revision += 1
    summary = {
        "records": len(records),
        "added": added,
        "updated": updated,
        "removed": removed,
        "unchanged": unchanged,
        "warnings": sum(bool(item.get("warnings")) for item in records),
    }
    run = {
        "started_at": timestamp,
        "completed_at": timestamp,
        "status": "success",
        "summary": summary,
    }
    changes = list((previous or {}).get("changes") or [])
    if changed:
        for record_id in sorted(new_map.keys() - old_map.keys()):
            changes.append(
                {"at": timestamp, "action": "record_added", "record_id": record_id}
            )
        for record_id in sorted(old_map.keys() - new_map.keys()):
            changes.append(
                {"at": timestamp, "action": "record_removed", "record_id": record_id}
            )
        for record_id in sorted(new_map.keys() & old_map.keys()):
            if new_map[record_id] != old_map[record_id]:
                changes.append(
                    {"at": timestamp, "action": "record_updated", "record_id": record_id}
                )
    data = {
        "schema_version": SCHEMA_VERSION,
        "dataset_revision": revision,
        "data_root": str(root.resolve()),
        "created_at": (previous or {}).get("created_at") or timestamp,
        "updated_at": timestamp,
        "records": records,
        "unmatched_files": unmatched_files,
        "ignored_files": ignored_files,
        "runs": [*((previous or {}).get("runs") or []), run][-100:],
        "changes": changes[-1000:],
    }
    return data, changed, summary


def save_dataset(path: Path, data: dict[str, Any]) -> Path:
    atomic_replace_text(
        path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    )
    return path
