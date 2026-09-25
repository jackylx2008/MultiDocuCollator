"""酒店需求工作联系单本地 HTML 汇总服务。

用途：
  启动时先扫描实际资料目录并重建 JSON/HTML，再在 127.0.0.1 的动态端口打开正式
  HTML 汇总。点击“主题”链接时，由服务根据
  当前系统的 CloudStation 根目录定位资料，并使用 Finder、Windows 资源管理器
  或 Linux 默认文件管理器打开对应目录。汇总表末行还可提交新联系单，服务使用
  同级 DOCX 模板创建文档并通过 Microsoft Word 导出 PDF，随后刷新 JSON/HTML；
  既有记录可更新主题和需求正文、同步目录名并重新出具 PDF；页面只检查由外部
  启动器管理的本地 llama.cpp 服务并调用其公文勘误接口。

配置文件：
  默认读取 config.yaml 和本机私有 common.env，与 build_archive.py 使用同一
  资料根目录配置。

可选参数：
  --data-root   临时覆盖资料根目录。
  --no-browser  启动服务但不自动打开浏览器。

示例：
  python serve_summary.py

输出：
  控制台显示本地访问地址；按 Ctrl+C 停止服务。仅在用户点击末行“保存”时创建
  新资料目录并更新 JSON/HTML；点击记录删除按钮时，只把既有资料目录移动到同级
  _trash 并刷新成果，不执行永久删除。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _application_root() -> Path:
    """源码运行时返回项目目录，冻结后返回 EXE 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _application_root()
SRC_DIR = PROJECT_ROOT / "src"
if not getattr(sys, "frozen", False) and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from logging_config import configure_utf8_stdio, setup_logger
from multidocu_collator.config_loader import load_settings
from multidocu_collator.context import AppContext
from multidocu_collator.flows.build_archive_flow import run_build_archive
from multidocu_collator.flows.summary_server_flow import run_summary_server


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", help="覆盖配置中的资料根目录")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    settings = load_settings(PROJECT_ROOT)
    setup_logger(settings["log_level"])
    raw_root = args.data_root or settings["data_root"]
    context = AppContext(
        project_root=PROJECT_ROOT,
        data_root=Path(raw_root).expanduser(),
        json_name=settings["json_name"],
        html_name=settings["html_name"],
        template_name=settings["template_name"],
        local_ai_base_url=settings["local_ai_base_url"],
        local_ai_model=settings["local_ai_model"],
        local_ai_api_key=settings["local_ai_api_key"],
        local_ai_request_timeout_sec=settings["local_ai_request_timeout_sec"],
    )
    try:
        # 服务启动时先从实际资料目录重建 JSON/HTML，避免打开过期页面。
        run_build_archive(context)
        run_summary_server(context, open_browser=not args.no_browser)
    except Exception as exc:
        print(f"本地汇总服务启动失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
