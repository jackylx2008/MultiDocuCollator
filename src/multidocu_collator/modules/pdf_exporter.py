"""跨平台调用 Microsoft Word 将 DOCX 导出为 PDF。"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path


MACOS_SCRIPT = r'''
on run argv
  set inputPath to item 1 of argv
  set outputPath to item 2 of argv
  tell application "Microsoft Word"
    open (POSIX file inputPath)
    delay 2
    set docRef to active document
    save as docRef file name outputPath file format format PDF
    close docRef saving no
  end tell
end run
'''

WINDOWS_SCRIPT = r'''
$inputPath = $args[0]
$outputPath = $args[1]
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($inputPath)
  try { $doc.SaveAs2($outputPath, 17) } finally { $doc.Close($false) }
} finally { $word.Quit() }
'''


def validate_pdf(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 100:
        raise ValueError("Microsoft Word 未生成有效 PDF")
    if not path.read_bytes()[:5] == b"%PDF-":
        raise ValueError("生成文件不是有效 PDF")


def export_pdf_with_word(
    docx: Path, pdf: Path, *, system_name: str | None = None
) -> Path:
    system = system_name or platform.system()
    pdf.parent.mkdir(parents=True, exist_ok=True)
    if system == "Darwin":
        command = ["osascript", "-e", MACOS_SCRIPT, str(docx.resolve()), str(pdf.resolve())]
    elif system == "Windows":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            WINDOWS_SCRIPT,
            str(docx.resolve()),
            str(pdf.resolve()),
        ]
    else:
        raise RuntimeError("自动导出 PDF 目前仅支持安装了 Microsoft Word 的 macOS/Windows")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 Microsoft Word 导出所需的系统命令") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Microsoft Word 导出 PDF 超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "未知错误").strip()
        raise RuntimeError(f"Microsoft Word 导出 PDF 失败: {detail}") from exc
    validate_pdf(pdf)
    return pdf
