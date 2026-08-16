"""运行仅监听本机回环地址的 HTML 汇总与目录打开服务。"""

from __future__ import annotations

import json
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from logging_config import get_logger

from ..context import AppContext
from ..modules.desktop import open_directory, resolve_relative_directory
from .create_record_flow import create_record


logger = get_logger(__name__)
MAX_REQUEST_BYTES = 16 * 1024


def _handler_class(context: AppContext) -> type[SimpleHTTPRequestHandler]:
    root = context.data_root.resolve()
    html_name = context.html_name

    class SummaryHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802 - http.server 固定接口名
            if urlsplit(self.path).path == "/":
                self.path = "/" + quote(html_name)
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802 - http.server 固定接口名
            route = urlsplit(self.path).path
            if route not in {"/api/open-path", "/api/create-record"}:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("请求体大小无效")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                if route == "/api/create-record":
                    result = create_record(context, payload)
                    logger.info("已创建联系单: %s", result["document_code"])
                    self._send_json(HTTPStatus.CREATED, result)
                    return
                if not isinstance(payload.get("path"), str):
                    raise ValueError("path 必须是相对目录字符串")
                target = resolve_relative_directory(root, payload["path"])
                open_directory(target)
            except (ValueError, FileNotFoundError, FileExistsError, json.JSONDecodeError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except Exception as exc:
                logger.exception("打开目录失败")
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"系统无法打开目录: {exc}"},
                )
                return
            logger.info("已打开资料目录: %s", target)
            self._send_json(HTTPStatus.OK, {"ok": True})

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug(format, *args)

    return SummaryHandler


def run_summary_server(
    context: AppContext, *, open_browser: bool = True
) -> str:
    if not context.html_path.is_file():
        raise FileNotFoundError(f"请先生成 HTML 汇总: {context.html_path}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_class(context))
    url = f"http://127.0.0.1:{server.server_port}/"
    logger.info("本地汇总服务: %s", url)
    logger.info("按 Ctrl+C 停止服务")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在停止本地汇总服务")
    finally:
        server.server_close()
    return url
