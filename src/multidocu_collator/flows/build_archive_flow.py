"""扫描资料、更新正式 JSON 并生成 HTML。"""

from __future__ import annotations

from typing import Any

from logging_config import get_logger

from ..context import AppContext
from ..modules.repository import build_dataset, load_dataset, save_dataset
from ..modules.scanner import scan_data_root
from ..modules.summary_html import export_summary_html
from ..modules.validation import validate_dataset, validate_summary_html


logger = get_logger(__name__)


def run_build_archive(context: AppContext) -> dict[str, Any]:
    root = context.data_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"资料根目录不存在: {root}")
    logger.info("扫描资料目录: %s", root)
    previous = load_dataset(context.json_path)
    records, unmatched, ignored = scan_data_root(
        root,
        generated_names={context.json_name, context.html_name, context.template_name},
    )
    logger.info("扫描到 %d 条联系单记录", len(records))
    data, changed, summary = build_dataset(
        root=root,
        records=records,
        unmatched_files=unmatched,
        ignored_files=ignored,
        previous=previous,
    )
    save_dataset(context.json_path, data)
    export_summary_html(data, context.html_path)
    dataset_validation = validate_dataset(data, root, verify_hashes=True)
    html_validation = validate_summary_html(context.html_path, data)
    errors = [*dataset_validation["errors"], *html_validation["errors"]]
    warnings = [*dataset_validation["warnings"], *html_validation["warnings"]]
    if errors:
        raise ValueError("生成后校验失败：" + "；".join(errors))
    logger.info(
        "完成：新增 %d，更新 %d，删除 %d，未变化 %d，含提示 %d",
        summary["added"], summary["updated"], summary["removed"],
        summary["unchanged"], summary["warnings"],
    )
    logger.info("JSON: %s", context.json_path)
    logger.info("HTML: %s", context.html_path)
    return {
        "changed": changed,
        "summary": summary,
        "json_path": str(context.json_path),
        "html_path": str(context.html_path),
        "warnings": warnings,
    }
