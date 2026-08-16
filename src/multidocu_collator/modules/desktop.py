"""安全解析相对目录并调用当前系统的文件管理器。"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from .file_utils import ensure_within


def resolve_relative_directory(root: Path, relative_path: str) -> Path:
    """将资料相对路径解析到当前平台根目录，并阻止绝对路径和越界。"""
    value = relative_path.strip()
    if not value:
        raise ValueError("目录路径不能为空")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("只允许资料根目录内的相对路径")
    try:
        target = ensure_within(root / Path(value), root)
    except (ValueError, OSError) as exc:
        raise ValueError("目录路径越出资料根目录") from exc
    if not target.is_dir():
        raise FileNotFoundError(f"目录不存在: {value}")
    return target


def open_directory(path: Path, *, system_name: str | None = None) -> None:
    """使用 Windows 资源管理器、macOS Finder 或 Linux 默认程序打开目录。"""
    system = system_name or platform.system()
    if system == "Windows":
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise RuntimeError("当前 Python 不提供 Windows os.startfile")
        startfile(str(path))
        return
    if system == "Darwin":
        subprocess.run(["open", str(path)], check=True)
        return
    if system == "Linux":
        subprocess.run(["xdg-open", str(path)], check=True)
        return
    raise RuntimeError(f"不支持的操作系统: {system}")
