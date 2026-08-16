"""独立校验 JSON、资料文件与 HTML 成果。"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from multidocu_collator.constants import SCHEMA_VERSION

from .file_utils import ensure_within, sha256_file


class _SummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_data = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "summaryData":
            self.in_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_data:
            self.in_data = False

    def handle_data(self, data: str) -> None:
        if self.in_data:
            self.parts.append(data)


def validate_dataset(
    data: dict[str, Any], root: Path, *, verify_hashes: bool = True
) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"不支持的 schema_version: {data.get('schema_version')}")
    record_ids: set[str] = set()
    business_keys: set[tuple[str, str]] = set()
    file_paths: set[str] = set()
    for record in data.get("records") or []:
        record_id = str(record.get("record_id") or "")
        if not record_id or record_id in record_ids:
            errors.append(f"缺少或重复 record_id: {record_id or '[空]'}")
        record_ids.add(record_id)
        key = (str(record.get("discipline") or ""), str(record.get("sequence_no") or ""))
        if key in business_keys:
            errors.append(f"重复业务编号: {'-'.join(key)}")
        business_keys.add(key)
        if "需求内容" not in record:
            errors.append(f"记录缺少“需求内容”字段: {record_id}")
        for item in record.get("files") or []:
            relative = str(item.get("path") or "")
            if relative in file_paths:
                warnings.append(f"同一路径被多次引用: {relative}")
            file_paths.add(relative)
            try:
                path = ensure_within(root / relative, root)
            except (ValueError, OSError):
                errors.append(f"文件路径越界: {relative}")
                continue
            if not path.is_file():
                errors.append(f"文件不存在: {relative}")
                continue
            if path.stat().st_size != int(item.get("size") or -1):
                errors.append(f"文件大小不一致: {relative}")
            if verify_hashes and sha256_file(path) != item.get("sha256"):
                errors.append(f"文件哈希不一致: {relative}")
    return {"errors": errors, "warnings": warnings}


def validate_summary_html(
    html_path: Path, data: dict[str, Any]
) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not html_path.is_file():
        return {"errors": [f"HTML 不存在: {html_path}"], "warnings": []}
    parser = _SummaryParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    if not parser.parts:
        errors.append("HTML 缺少 summaryData 数据块")
        return {"errors": errors, "warnings": warnings}
    try:
        view = json.loads("".join(parser.parts))
    except json.JSONDecodeError as exc:
        errors.append(f"HTML summaryData 不是有效 JSON: {exc}")
        return {"errors": errors, "warnings": warnings}
    if int(view.get("dataset_revision") or 0) != int(data.get("dataset_revision") or 0):
        errors.append("HTML 数据版本与 JSON 不一致")
    if int(view.get("record_count") or 0) != len(data.get("records") or []):
        errors.append("HTML 记录数与 JSON 不一致")
    return {"errors": errors, "warnings": warnings}
