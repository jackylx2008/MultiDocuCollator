"""酒店需求工作联系单 JSON 与 HTML 生成工具。

用途：
  只读扫描资料根目录下符合“专业-编号-日期_主题”规则的一级子目录，解析
  Word 当前有效文字及“内容：”后的下划线正文，生成正式 JSON 数据库和离线
  HTML 汇总。不会移动、重命名或删除原始资料。

配置文件：
  默认读取项目根目录 config.yaml；本机真实路径可写入不入库的 common.env。

可选参数：
  --data-root  临时覆盖资料根目录。

示例：
  python build_archive.py --data-root "/path/to/02 酒店需求工作联系单"

输出：
  在资料根目录生成“酒店需求工作联系单数据.json”和
  “酒店需求工作联系单汇总.html”（文件名可由配置覆盖）。
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
from multidocu_collator.flows.build_archive_flow import run_build_archive


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", help="覆盖配置中的资料根目录")
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
        result = run_build_archive(context)
    except Exception as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
