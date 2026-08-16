"""酒店需求工作联系单成果独立校验工具。

用途：
  校验 JSON 数据版本、记录唯一性、相对路径边界、文件大小与 SHA-256，及 HTML
  内嵌数据版本和记录数。只执行读取，不修改资料或成果。

可选参数：
  --data-root  临时覆盖资料根目录。
  --skip-hashes  跳过耗时的文件哈希复核，仅检查路径和大小。

示例：
  python validate_archive.py --data-root "/path/to/02 酒店需求工作联系单"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from logging_config import setup_logger
from multidocu_collator.config_loader import load_settings
from multidocu_collator.context import AppContext
from multidocu_collator.flows.validation_flow import run_validation


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", help="覆盖配置中的资料根目录")
    parser.add_argument("--skip-hashes", action="store_true", help="跳过 SHA-256 复核")
    args = parser.parse_args()
    settings = load_settings(PROJECT_ROOT)
    setup_logger(settings["log_level"])
    raw_root = args.data_root or settings["data_root"]
    if not raw_root:
        parser.error("请使用 --data-root 或 HOTEL_REQUIREMENTS_ROOT 指定资料根目录")
    context = AppContext(
        project_root=PROJECT_ROOT,
        data_root=Path(raw_root).expanduser(),
        json_name=settings["json_name"],
        html_name=settings["html_name"],
        template_name=settings["template_name"],
    )
    try:
        result = run_validation(context, verify_hashes=not args.skip_hashes)
    except Exception as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
