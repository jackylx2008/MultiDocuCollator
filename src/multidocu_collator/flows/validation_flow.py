"""独立运行资料数据库和 HTML 校验。"""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..modules.repository import load_dataset
from ..modules.validation import validate_dataset, validate_summary_html


def run_validation(
    context: AppContext, *, verify_hashes: bool = True
) -> dict[str, Any]:
    data = load_dataset(context.json_path)
    if data is None:
        raise FileNotFoundError(f"JSON 数据库不存在: {context.json_path}")
    dataset_result = validate_dataset(
        data, context.data_root.resolve(), verify_hashes=verify_hashes
    )
    html_result = validate_summary_html(context.html_path, data)
    return {
        "errors": [*dataset_result["errors"], *html_result["errors"]],
        "warnings": [*dataset_result["warnings"], *html_result["warnings"]],
        "records": len(data.get("records") or []),
        "dataset_revision": int(data.get("dataset_revision") or 0),
    }
