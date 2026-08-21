"""安全解析相对目录并调用当前系统的文件管理器。"""

from __future__ import annotations

import os
import platform
import struct
import subprocess
import time
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


def resolve_relative_file(root: Path, relative_path: str) -> Path:
    """解析资料根目录内的相对文件路径，并阻止绝对路径和越界。"""
    value = relative_path.strip()
    if not value:
        raise ValueError("文件路径不能为空")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("只允许资料根目录内的相对路径")
    try:
        target = ensure_within(root / Path(value), root)
    except (ValueError, OSError) as exc:
        raise ValueError("文件路径越出资料根目录") from exc
    if not target.is_file():
        raise FileNotFoundError(f"文件不存在: {value}")
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


def copy_file_to_clipboard(path: Path, *, system_name: str | None = None) -> None:
    """把文件放入 Windows 文件剪贴板，供资源管理器直接粘贴。"""
    system = system_name or platform.system()
    if system != "Windows":
        raise RuntimeError("文件剪贴板复制目前仅支持 Windows")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    # DROPFILES: pFiles, POINT(x/y), fNC, fWide，随后是双空字符结尾的 UTF-16 路径。
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
    file_list = (str(path.resolve()) + "\0\0").encode("utf-16-le")
    content = header + file_list
    handle = kernel32.GlobalAlloc(0x0002, len(content))  # GMEM_MOVEABLE
    if not handle:
        raise OSError(ctypes.get_last_error(), "无法分配剪贴板内存")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError(ctypes.get_last_error(), "无法锁定剪贴板内存")
    ctypes.memmove(pointer, content, len(content))
    kernel32.GlobalUnlock(handle)

    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        kernel32.GlobalFree(handle)
        raise OSError(ctypes.get_last_error(), "剪贴板正被其他程序占用")
    try:
        if not user32.EmptyClipboard():
            raise OSError(ctypes.get_last_error(), "无法清空剪贴板")
        if not user32.SetClipboardData(15, handle):  # CF_HDROP
            raise OSError(ctypes.get_last_error(), "无法写入文件剪贴板")
        handle = None  # SetClipboardData 成功后由系统接管内存。
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)
