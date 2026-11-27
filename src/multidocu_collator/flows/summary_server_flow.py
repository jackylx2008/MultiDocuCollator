"""运行仅监听本机回环地址的 HTML 汇总与目录打开服务。"""

from __future__ import annotations

import json
import mimetypes
import platform
import subprocess
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from logging_config import get_logger

from ..context import AppContext
from ..modules.desktop import (
    copy_file_to_clipboard,
    open_directory,
    resolve_relative_directory,
    resolve_relative_file,
)
from ..modules.local_ai import (
    build_text_comparison,
    local_ai_status,
    proofread_official_content,
)
from ..modules.work_contact_ai import generate_work_contact_draft, split_work_contact_content
from .build_archive_flow import run_build_archive
from .create_record_flow import create_record
from .delete_record_flow import delete_record
from .mutation_lock import RECORD_MUTATION_LOCK
from .new_content_draft_flow import (
    clear_new_content_draft,
    load_new_content_draft,
    save_new_content_draft,
)
from .update_print_status_flow import update_print_statuses
from .update_record_content_flow import update_record_content
from .print_pdf_a4_flow import print_all_pdfs_a4, print_pdf_a4
from .work_contact_flow import HTML_NAME as WORK_HTML_NAME, build_work_contact_archive
from .work_contact_mutation import (
    create_work_contact,
    delete_work_contact,
    update_work_contact,
)


logger = get_logger(__name__)
MAX_REQUEST_BYTES = 1024 * 1024
SUMMARY_WINDOW_MARKERS = (
    "酒店需求工作联系单汇总",
    "主体工作联系单汇总",
)


def _open_summary_browser(url: str, *, system_name: str | None = None) -> None:
    if (system_name or platform.system()) == "Windows":
        _position_summary_window_on_primary_monitor(url)
        return
    webbrowser.open(url)


def _position_summary_window_on_primary_monitor(url: str, *, timeout: float = 8.0) -> None:
    """定位本次打开的汇总浏览器窗口到 Windows 主显示器并最大化。"""
    if platform.system() != "Windows":
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def matching_windows() -> set[int]:
        found: set[int] = set()

        @enum_proc
        def visit(hwnd: int, _lparam: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                size = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(size + 1)
                user32.GetWindowTextW(hwnd, title, size + 1)
                if any(marker in title.value for marker in SUMMARY_WINDOW_MARKERS):
                    found.add(hwnd)
            return True

        user32.EnumWindows(visit, 0)
        return found

    prior_windows = matching_windows()
    _launch_summary_url(url)
    deadline = time.monotonic() + timeout
    target = None
    while time.monotonic() < deadline:
        target = next(iter(matching_windows() - prior_windows), None)
        if target:
            break
        time.sleep(0.2)
    if not target:
        logger.warning("未能在 %.1f 秒内定位新打开的汇总浏览器窗口", timeout)
        return

    class RECT(ctypes.Structure):
        _fields_ = [(name, wintypes.LONG) for name in ("left", "top", "right", "bottom")]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
    )
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, monitor_enum_proc, wintypes.LPARAM]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

    primary = None

    @monitor_enum_proc
    def find_primary(monitor: int, _dc: int, _rect: Any, _lparam: int) -> bool:
        nonlocal primary
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)) and info.dwFlags & 1:
            primary = info.rcWork
            return False
        return True

    user32.EnumDisplayMonitors(None, None, find_primary, 0)
    if primary is None:
        logger.warning("无法读取主显示器工作区，汇总页面保持打开")
        return
    user32.ShowWindow(target, 9)  # SW_RESTORE
    user32.SetWindowPos(target, 0, primary.left, primary.top,
                        primary.right - primary.left, primary.bottom - primary.top, 0x0040)
    user32.ShowWindow(target, 3)  # SW_MAXIMIZE


def _launch_summary_url(url: str) -> None:
    """Windows 下脱离启动器进程树，避免 Code Runner 连带关闭浏览器。"""
    creation_flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    command = ["cmd.exe", "/d", "/c", "start", "", url]
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    try:
        subprocess.Popen(
            command,
            creationflags=creation_flags | breakaway_flag,
            **options,
        )
    except OSError:
        # 某些宿主 Job 不允许 BREAKAWAY；其余分离标志仍可避免普通进程树终止。
        subprocess.Popen(command, creationflags=creation_flags, **options)


def _handler_class(context: AppContext) -> type[SimpleHTTPRequestHandler]:
    root = context.data_root.resolve()
    work_root = context.work_contact_root.resolve() if context.work_contact_root else None
    html_name = context.html_name

    class SummaryHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802 - http.server 固定接口名
            route = urlsplit(self.path).path
            if route == "/work-contact":
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", "/work-contact/")
                self.end_headers()
                return
            if route == "/work-contact/":
                if work_root is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_work_file(work_root / WORK_HTML_NAME)
                return
            if route.startswith("/work-contact/"):
                if work_root is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                try:
                    relative = unquote(route.removeprefix("/work-contact/"))
                    target = resolve_relative_file(work_root, relative)
                except (ValueError, FileNotFoundError):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_work_file(target)
                return
            if route == "/api/local-ai-status":
                result = local_ai_status(context)
                self._send_json(HTTPStatus.OK, result)
                return
            if route == "/api/new-content-draft":
                try:
                    self._send_json(HTTPStatus.OK, load_new_content_draft(context))
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if route == "/":
                self.path = "/" + quote(html_name)
            super().do_GET()

        def _send_work_file(self, path: Path) -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() in {".html", ".json"}:
                content_type += "; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    self.wfile.write(chunk)

        def do_POST(self) -> None:  # noqa: N802 - http.server 固定接口名
            route = urlsplit(self.path).path
            if route not in {
                "/api/open-path",
                "/api/copy-file",
                "/api/create-record",
                "/api/save-new-content-draft",
                "/api/delete-record",
                "/api/refresh-archive",
                "/api/refresh-work-contact",
                "/api/create-work-contact",
                "/api/update-work-contact",
                "/api/delete-work-contact",
                "/api/open-work-contact-path",
                "/api/copy-work-contact-file",
                "/api/save-print-status",
                "/api/save-manual-statuses",
                "/api/update-record-content",
                "/api/proofread-content",
                "/api/proofread-work-contact",
                "/api/generate-work-contact",
                "/api/split-work-contact",
                "/api/print-pdf-a4",
                "/api/print-all-pdfs-a4",
            }:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("请求体大小无效")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                if route == "/api/refresh-archive":
                    with RECORD_MUTATION_LOCK:
                        result = run_build_archive(context)
                    logger.info("已从实际资料目录重新扫描并刷新汇总")
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/print-pdf-a4":
                    result = print_pdf_a4(context, payload)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/print-all-pdfs-a4":
                    result = print_all_pdfs_a4(context)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/refresh-work-contact":
                    if work_root is None:
                        raise FileNotFoundError("主体工作联系单目录未配置")
                    with RECORD_MUTATION_LOCK:
                        result = build_work_contact_archive(work_root)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/generate-work-contact":
                    if work_root is None:
                        raise FileNotFoundError("主体工作联系单目录未配置")
                    self._send_json(
                        HTTPStatus.OK,
                        generate_work_contact_draft(work_root, payload, context=context),
                    )
                    return
                if route == "/api/split-work-contact":
                    if work_root is None:
                        raise FileNotFoundError("主体工作联系单目录未配置")
                    self._send_json(
                        HTTPStatus.OK,
                        split_work_contact_content(work_root, payload, context=context),
                    )
                    return
                if route in {
                    "/api/create-work-contact",
                    "/api/update-work-contact",
                    "/api/delete-work-contact",
                    "/api/open-work-contact-path",
                    "/api/copy-work-contact-file",
                }:
                    if work_root is None:
                        raise FileNotFoundError("主体工作联系单目录未配置")
                    if route == "/api/create-work-contact":
                        self._send_json(HTTPStatus.CREATED, create_work_contact(work_root, payload))
                        return
                    if route == "/api/update-work-contact":
                        self._send_json(HTTPStatus.OK, update_work_contact(work_root, payload))
                        return
                    if route == "/api/delete-work-contact":
                        self._send_json(HTTPStatus.OK, delete_work_contact(work_root, payload))
                        return
                    relative = payload.get("path")
                    if not isinstance(relative, str):
                        raise ValueError("path 必须是相对路径字符串")
                    if route == "/api/copy-work-contact-file":
                        target_file = resolve_relative_file(work_root, relative)
                        copy_file_to_clipboard(target_file)
                        self._send_json(HTTPStatus.OK, {"ok": True})
                        return
                    target_directory = resolve_relative_directory(work_root, relative)
                    open_directory(target_directory)
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return
                if route in {"/api/save-print-status", "/api/save-manual-statuses"}:
                    result = update_print_statuses(context, payload)
                    logger.info("已保存 %d 项人工状态修改", result["changed"])
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/update-record-content":
                    result = update_record_content(context, payload)
                    logger.info("已更新联系单主题或需求内容: %s", payload.get("record_id"))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/save-new-content-draft":
                    result = save_new_content_draft(context, payload)
                    logger.info("已临时保存新增需求内容草稿")
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route in {"/api/proofread-content", "/api/proofread-work-contact"}:
                    work_contact = route == "/api/proofread-work-contact"
                    if work_contact and work_root is None:
                        raise FileNotFoundError("主体工作联系单目录未配置")
                    original = str(payload.get("content" if work_contact else "requirement_content") or "")
                    revised = (
                        proofread_official_content(
                            original, context=context, content_label="工作联系单正文"
                        ) if work_contact else proofread_official_content(original, context=context)
                    )
                    original_segments, revised_segments = build_text_comparison(
                        original.strip(), revised
                    )
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "revised_content": revised,
                            "original_segments": original_segments,
                            "revised_segments": revised_segments,
                            "model": context.local_ai_model,
                        },
                    )
                    return
                if route == "/api/create-record":
                    result = create_record(context, payload)
                    try:
                        clear_new_content_draft(context)
                    except OSError:
                        logger.warning("联系单已创建，但临时草稿清理失败", exc_info=True)
                    logger.info("已创建联系单: %s", result["document_code"])
                    self._send_json(HTTPStatus.CREATED, result)
                    return
                if route == "/api/delete-record":
                    result = delete_record(context, payload)
                    logger.info("联系单已移入回收目录: %s", result["trash_path"])
                    self._send_json(HTTPStatus.OK, result)
                    return
                if not isinstance(payload.get("path"), str):
                    raise ValueError("path 必须是相对路径字符串")
                if route == "/api/copy-file":
                    target = resolve_relative_file(root, payload["path"])
                    copy_file_to_clipboard(target)
                    logger.info("文件已复制到剪贴板: %s", target)
                    self._send_json(
                        HTTPStatus.OK, {"ok": True, "file_name": target.name}
                    )
                    return
                target = resolve_relative_directory(root, payload["path"])
                open_directory(target)
            except (ValueError, FileNotFoundError, FileExistsError, json.JSONDecodeError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except Exception as exc:
                logger.exception("本地资料操作失败")
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"系统无法完成操作: {exc}"},
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
    server, url = create_summary_server(context)
    logger.info("本地汇总服务: %s", url)
    logger.info("按 Ctrl+C 停止服务")
    if open_browser:
        _open_summary_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在停止本地汇总服务")
    finally:
        server.server_close()
    return url


def create_summary_server(
    context: AppContext,
) -> tuple[ThreadingHTTPServer, str]:
    """创建尚未启动的本地 HTTP 服务，供控制窗口或命令行托管。"""
    if not context.html_path.is_file():
        raise FileNotFoundError(f"请先生成 HTML 汇总: {context.html_path}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_class(context))
    url = f"http://127.0.0.1:{server.server_port}/"
    return server, url
