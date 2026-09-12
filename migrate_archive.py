"""迁移已存档资料到独立目录，并生成离线检索/导出 HTML。

示例：
  python migrate_archive.py --source-root "D:\\CloudStation\\国会二期\\02 酒店需求工作联系单" --destination-root "E:\\酒店需求存档"
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from multidocu_collator.config_loader import load_settings
from multidocu_collator.modules.archive_migration import migrate_archive
from logging_config import configure_utf8_stdio


def _choose_destination_directory() -> Path | None:
    """为双击或 Code Runner 运行提供目标目录选择窗口。"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root,
            title="选择存档迁移目标目录（将在此目录建立专业目录和检索 HTML）",
            mustexist=False,
        )
        root.destroy()
    except Exception as exc:
        print(f"无法打开目标目录选择窗口：{exc}", file=sys.stderr)
        return None
    return Path(selected) if selected else None


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source-root", help="现有存档资料根目录；省略时使用配置")
    parser.add_argument("--destination-root", help="迁移目标目录；省略时弹出选择窗口")
    parser.add_argument("--no-open", action="store_true", help="完成后不自动打开检索 HTML")
    args = parser.parse_args()
    settings = load_settings(PROJECT_ROOT)
    source = Path(args.source_root or settings["data_root"]).expanduser()
    destination = (
        Path(args.destination_root).expanduser()
        if args.destination_root
        else _choose_destination_directory()
    )
    if destination is None:
        print("已取消迁移：未选择目标目录")
        return 0
    try:
        result = migrate_archive(source, destination)
    except Exception as exc:
        print(f"迁移失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.no_open:
        try:
            webbrowser.open(Path(result["html_path"]).resolve().as_uri())
        except OSError as exc:
            print(f"迁移已完成，但无法自动打开检索 HTML：{exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
