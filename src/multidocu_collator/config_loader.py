"""读取项目配置和本机环境变量。"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Any

from .constants import DEFAULT_HTML_NAME, DEFAULT_JSON_NAME, DEFAULT_TEMPLATE_NAME


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
PLATFORM_ROOT_KEYS = {
    "Windows": "CLOUDSTATION_ROOT_WINDOWS",
    "Darwin": "CLOUDSTATION_ROOT_MACOS",
    "Linux": "CLOUDSTATION_ROOT_LINUX",
}
PLATFORM_ROOT_DEFAULTS = {
    "Windows": r"D:\CloudStation",
    "Darwin": "~/SynologyDrive/",
    "Linux": "~/CloudStation",
}


def load_common_env(project_root: Path) -> None:
    """载入 common.env，但不覆盖进程中已经设置的环境变量。"""
    path = project_root / "common.env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def select_cloudstation_root(
    *,
    system_name: str | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """按当前系统选择群晖同步根目录，显式 CLOUDSTATION_ROOT 优先。"""
    values = os.environ if environ is None else environ
    explicit = values.get("CLOUDSTATION_ROOT", "").strip()
    if explicit:
        return explicit
    system = system_name or platform.system()
    variable = PLATFORM_ROOT_KEYS.get(system)
    if variable is None:
        raise ValueError(f"不支持的操作系统: {system}")
    return values.get(variable, PLATFORM_ROOT_DEFAULTS[system]).strip()


def configure_cloudstation_root() -> str:
    """设置统一 CLOUDSTATION_ROOT，供 config.yaml 环境标记展开。"""
    selected = select_cloudstation_root()
    os.environ.setdefault("CLOUDSTATION_ROOT", selected)
    return selected


def expand_env(value: str) -> str:
    """展开 ${NAME:-default} 形式的环境变量。"""

    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2) or ""
        return os.environ.get(name, default)

    previous = value
    for _ in range(5):
        expanded = ENV_PATTERN.sub(replace, previous)
        if expanded == previous:
            return expanded
        previous = expanded
    return previous


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    """读取本项目使用的简单键值 YAML，避免运行时强制依赖 PyYAML。"""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            raise ValueError(f"不支持的配置行 {line_number}: {stripped}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        value = raw_value.strip()
        if not value:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = expand_env(value.strip('"').strip("'"))
    return root


def load_settings(project_root: Path) -> dict[str, Any]:
    load_common_env(project_root)
    configure_cloudstation_root()
    path = project_root / "config.yaml"
    data = _read_simple_yaml(path)
    app = data.get("app") or {}
    flow = (data.get("flows") or {}).get("build_archive") or {}
    configured_data_root = str(flow.get("data_root") or "")
    data_root = os.environ.get("HOTEL_REQUIREMENTS_ROOT", "").strip()
    def local_path(name: str, default: str) -> str:
        value = os.environ.get(name, default).strip()
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else project_root / path)

    return {
        "log_level": str(app.get("log_level") or "INFO"),
        "data_root": str(Path(data_root or configured_data_root).expanduser()),
        "json_name": str(flow.get("json_name") or DEFAULT_JSON_NAME),
        "html_name": str(flow.get("html_name") or DEFAULT_HTML_NAME),
        "template_name": str(flow.get("template_name") or DEFAULT_TEMPLATE_NAME),
        "local_ai_base_url": os.environ.get(
            "LLAMACPP_BASE_URL", "http://127.0.0.1:8080/v1"
        ).strip(),
        "local_ai_model": os.environ.get(
            "LLAMACPP_MODEL", "Qwen3.8-27B-Q4_K_M.gguf"
        ).strip(),
        "local_ai_autostart": os.environ.get(
            "LLAMACPP_AUTOSTART", "true"
        ).strip().lower() in {"1", "true", "yes", "on"},
        "local_ai_server_path": os.environ.get("LLAMACPP_SERVER_PATH", "").strip(),
        "local_ai_model_path": os.environ.get("LLAMACPP_MODEL_PATH", "").strip(),
        "local_ai_mmproj_path": os.environ.get("LLAMACPP_MMPROJ_PATH", "").strip(),
        "local_ai_n_gpu_layers": int(os.environ.get("LLAMACPP_N_GPU_LAYERS", "999")),
        "local_ai_startup_timeout_sec": int(
            os.environ.get("LLAMACPP_STARTUP_TIMEOUT_SEC", "180")
        ),
        "local_ai_startup_poll_interval_sec": float(
            os.environ.get("LLAMACPP_STARTUP_POLL_INTERVAL_SEC", "1")
        ),
        "local_ai_request_timeout_sec": int(
            os.environ.get("LLAMACPP_TIMEOUT_SEC", "180")
        ),
        "local_ai_stdout_log_path": local_path(
            "LLAMACPP_STDOUT_LOG_PATH", "log/llama_server.out.log"
        ),
        "local_ai_stderr_log_path": local_path(
            "LLAMACPP_STDERR_LOG_PATH", "log/llama_server.err.log"
        ),
        "local_ai_extra_dll_dirs": os.environ.get(
            "LLAMACPP_EXTRA_DLL_DIRS", ""
        ).strip(),
    }
