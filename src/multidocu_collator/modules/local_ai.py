"""通过项目托管的 llama.cpp 服务进行公文需求内容勘误。"""

from __future__ import annotations

import atexit
from difflib import SequenceMatcher
import json
import os
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from logging_config import get_logger

from ..context import AppContext


logger = get_logger(__name__)
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_RUNTIME_LOCK = threading.Lock()
_MANAGED_PROCESS: subprocess.Popen[str] | None = None
_MANAGED_LOG_FILES: tuple[Any, Any] | None = None


def _urls(base_url: str) -> tuple[str, str, str]:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("本地 AI 地址必须是本机回环 HTTP 地址")
    root = f"{parsed.scheme}://{parsed.netloc}"
    api = root + (parsed.path.rstrip("/") or "/v1")
    return f"{root}/health", f"{api}/models", f"{api}/chat/completions"


def _request_json(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"本地 AI 服务返回错误 {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"无法连接本地 llama.cpp 服务: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("本地 AI 返回了无效数据") from exc
    if not isinstance(result, dict):
        raise RuntimeError("本地 AI 返回格式不正确")
    return result


def _model_names(payload: dict[str, Any]) -> list[str]:
    return [
        str(item.get("id") or item.get("model") or item.get("name") or "")
        for item in [*(payload.get("data") or []), *(payload.get("models") or [])]
        if isinstance(item, dict)
        and (item.get("id") or item.get("model") or item.get("name"))
    ]


def _healthcheck(context: AppContext) -> list[str]:
    health_url, models_url, _ = _urls(context.local_ai_base_url)
    _request_json(health_url, timeout=3)
    models = _model_names(_request_json(models_url, timeout=3))
    if not models:
        raise RuntimeError("llama.cpp 没有返回可用模型")
    return models


def _server_command(context: AppContext) -> list[str]:
    server = Path(context.local_ai_server_path).expanduser()
    model = Path(context.local_ai_model_path).expanduser()
    mmproj = Path(context.local_ai_mmproj_path).expanduser()
    if not server.is_file():
        raise FileNotFoundError(f"llama-server.exe 不存在: {server}")
    if not model.is_file():
        raise FileNotFoundError(f"GGUF 主模型不存在: {model}")
    if not mmproj.is_file():
        raise FileNotFoundError(f"GGUF 视觉投影模型不存在: {mmproj}")
    parsed = urlsplit(context.local_ai_base_url)
    return [
        str(server),
        "-m",
        str(model),
        "--mmproj",
        str(mmproj),
        "-ngl",
        str(context.local_ai_n_gpu_layers),
        "--host",
        parsed.hostname or "127.0.0.1",
        "--port",
        str(parsed.port or 8080),
        "--verbose",
    ]


def _close_log_files() -> None:
    global _MANAGED_LOG_FILES
    if _MANAGED_LOG_FILES is None:
        return
    for handle in _MANAGED_LOG_FILES:
        try:
            handle.close()
        except OSError:
            pass
    _MANAGED_LOG_FILES = None


def shutdown_local_ai() -> None:
    """只关闭由本项目启动的 llama-server，不影响外部已有服务。"""
    global _MANAGED_PROCESS
    with _RUNTIME_LOCK:
        process = _MANAGED_PROCESS
        if process is None:
            return
        try:
            if process.poll() is None:
                logger.info("正在关闭项目托管的 llama.cpp 服务")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            _MANAGED_PROCESS = None
            _close_log_files()


def _start_server(context: AppContext) -> None:
    global _MANAGED_PROCESS, _MANAGED_LOG_FILES
    command = _server_command(context)
    stdout_path = Path(context.local_ai_stdout_log_path)
    stderr_path = Path(context.local_ai_stderr_log_path)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("a", encoding="utf-8")
    stderr_file = stderr_path.open("a", encoding="utf-8")
    environment = os.environ.copy()
    runtime_dirs = [str(Path(command[0]).resolve().parent)]
    runtime_dirs.extend(
        item.strip()
        for item in context.local_ai_extra_dll_dirs.split(os.pathsep)
        if item.strip()
    )
    environment["PATH"] = os.pathsep.join(runtime_dirs) + os.pathsep + environment.get(
        "PATH", ""
    )
    try:
        _MANAGED_PROCESS = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=str(Path(command[0]).resolve().parent),
            env=environment,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        stdout_file.close()
        stderr_file.close()
        raise
    _MANAGED_LOG_FILES = (stdout_file, stderr_file)
    logger.info("已自动启动 llama.cpp 服务: %s", context.local_ai_base_url)


def _ensure_server(context: AppContext) -> list[str]:
    global _MANAGED_PROCESS
    try:
        return _healthcheck(context)
    except RuntimeError as initial_error:
        if not context.local_ai_autostart:
            raise RuntimeError(
                f"llama.cpp 连接失败且未启用自动启动: {initial_error}"
            ) from initial_error

    with _RUNTIME_LOCK:
        try:
            return _healthcheck(context)
        except RuntimeError:
            if _MANAGED_PROCESS is None or _MANAGED_PROCESS.poll() is not None:
                _close_log_files()
                _MANAGED_PROCESS = None
                _start_server(context)
            deadline = time.monotonic() + context.local_ai_startup_timeout_sec
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if _MANAGED_PROCESS is not None and _MANAGED_PROCESS.poll() is not None:
                    code = _MANAGED_PROCESS.returncode
                    _MANAGED_PROCESS = None
                    _close_log_files()
                    raise RuntimeError(f"llama.cpp 启动后提前退出，退出码 {code}")
                try:
                    return _healthcheck(context)
                except RuntimeError as exc:
                    last_error = exc
                    time.sleep(context.local_ai_startup_poll_interval_sec)
            process = _MANAGED_PROCESS
            _MANAGED_PROCESS = None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            _close_log_files()
            raise RuntimeError(f"等待 llama.cpp 启动超时: {last_error}")


def local_ai_status(
    context: AppContext,
    *,
    system_name: str | None = None,
    start_if_needed: bool = False,
) -> dict[str, Any]:
    system = system_name or platform.system()
    if system != "Windows":
        return {
            "supported": False,
            "available": False,
            "system": system,
            "model": context.local_ai_model,
            "managed": False,
            "message": "本项目的本地 AI 勘误当前仅在 Windows 上启用",
        }
    try:
        models = _ensure_server(context) if start_if_needed else _healthcheck(context)
        installed = context.local_ai_model in models
        managed = _MANAGED_PROCESS is not None and _MANAGED_PROCESS.poll() is None
        return {
            "supported": True,
            "available": installed,
            "system": system,
            "model": context.local_ai_model,
            "managed": managed,
            "message": (
                f"本地 AI 已就绪：{context.local_ai_model}"
                if installed
                else f"llama.cpp 已启动，但模型名称不匹配；当前模型：{', '.join(models)}"
            ),
        }
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        return {
            "supported": True,
            "available": False,
            "system": system,
            "model": context.local_ai_model,
            "managed": False,
            "message": (
                str(exc)
                if start_if_needed
                else "本地 AI 未启动；点击“启动本地 AI”加载模型"
            ),
        }


def start_local_ai(context: AppContext) -> dict[str, Any]:
    """按需启动或复用本地服务，并返回最新状态。"""
    return local_ai_status(context, start_if_needed=True)


def stop_local_ai(context: AppContext) -> dict[str, Any]:
    """关闭本项目托管的服务；外部服务只报告状态，不越权终止。"""
    managed = _MANAGED_PROCESS is not None and _MANAGED_PROCESS.poll() is None
    if not managed:
        try:
            models = _healthcheck(context)
        except (ValueError, RuntimeError):
            return {
                "supported": platform.system() == "Windows",
                "available": False,
                "system": platform.system(),
                "model": context.local_ai_model,
                "managed": False,
                "message": "本地 AI 已关闭",
            }
        return {
            "supported": True,
            "available": context.local_ai_model in models,
            "system": platform.system(),
            "model": context.local_ai_model,
            "managed": False,
            "message": "当前为外部启动的 llama.cpp 服务，本项目不会将其关闭",
        }
    shutdown_local_ai()
    return {
        "supported": True,
        "available": False,
        "system": platform.system(),
        "model": context.local_ai_model,
        "managed": False,
        "message": "本地 AI 已关闭",
    }


def proofread_official_content(
    content: str,
    *,
    context: AppContext,
    system_name: str | None = None,
) -> str:
    system = system_name or platform.system()
    if system != "Windows":
        raise RuntimeError("本地 AI 勘误当前仅支持 Windows")
    text = str(content or "").strip()
    if not text:
        raise ValueError("需求内容不能为空")
    if len(text) > 4000:
        raise ValueError("需求内容不能超过 4000 个字符")
    text = "\n".join(
        line for line in text.splitlines() if line.strip() != "以下空白"
    ).strip()
    if not text:
        raise ValueError("删除“以下空白”后，需求内容不能为空")
    models = _ensure_server(context)
    if context.local_ai_model not in models:
        raise RuntimeError(
            "配置模型与 llama.cpp 已加载模型不一致: " + ", ".join(models)
        )
    _, _, chat_url = _urls(context.local_ai_base_url)
    result = _request_json(
        chat_url,
        payload={
            "model": context.local_ai_model,
            "temperature": 0.1,
            "max_tokens": 4096,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是严谨的中文公文编辑。请在忠实保留原意的前提下进行公文规范化修订："
                        "修正错别字、标点和病句；将口语化、重复、含混或冗长表达改为准确、简洁、"
                        "庄重的公文用语；优化句式、语序和逻辑衔接；统一术语及规范表达。"
                        "允许为提升公文质量重写句式，但不得改变、增加或删减任何事实、数字、日期、"
                        "计量含义、专有名词、责任主体、具体要求或时限。距离、长度、面积、功率等"
                        "单位必须使用规范的字母或符号，不使用汉字单位，例如米写为 m、毫米写为 mm、"
                        "平方米写为 m²、瓦写为 W、千瓦写为 kW；只规范单位写法，不改变数值。"
                        "“以下空白”是排版标记，不属于需求正文：如果输入中出现则删除，"
                        "如果输入中没有也不得新增。"
                        "只输出修订后的正文，不要解释、标题、引号或 Markdown。"
                    ),
                },
                {"role": "user", "content": "请勘误以下需求内容：\n\n" + text},
            ],
        },
        timeout=context.local_ai_request_timeout_sec,
    )
    choices = result.get("choices") or []
    revised = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict):
            revised = str(message.get("content") or "").strip()
    if revised.startswith("```") and revised.endswith("```"):
        revised = revised.strip("`").strip()
        if revised.startswith("text"):
            revised = revised[4:].lstrip("\r\n")
    revised = "\n".join(
        line for line in revised.splitlines() if line.strip() != "以下空白"
    ).strip()
    if not revised:
        raise RuntimeError("本地 AI 没有返回修订内容")
    if len(revised) > 4000:
        raise RuntimeError("本地 AI 返回内容超过 4000 个字符，请缩短原文后重试")
    return revised


def build_text_comparison(
    original: str, revised: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """生成原文与修订稿的逐字差异片段，供 HTML 对照高亮。"""
    original_segments: list[dict[str, Any]] = []
    revised_segments: list[dict[str, Any]] = []

    def append_segment(
        segments: list[dict[str, Any]], text: str, changed: bool
    ) -> None:
        if not text:
            return
        if segments and segments[-1]["changed"] == changed:
            segments[-1]["text"] += text
        else:
            segments.append({"text": text, "changed": changed})

    matcher = SequenceMatcher(None, original, revised, autojunk=False)
    for tag, original_start, original_end, revised_start, revised_end in matcher.get_opcodes():
        changed = tag != "equal"
        append_segment(
            original_segments,
            original[original_start:original_end],
            changed,
        )
        append_segment(
            revised_segments,
            revised[revised_start:revised_end],
            changed,
        )
    return original_segments, revised_segments


atexit.register(shutdown_local_ai)
