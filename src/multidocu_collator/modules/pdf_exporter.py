"""跨平台调用 Microsoft Word 将 DOCX 导出为 PDF。"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter


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
$inputPath = $env:MULTIDOCU_INPUT_PATH
$outputPath = $env:MULTIDOCU_OUTPUT_PATH
$word = $null
$doc = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $word.DisplayAlerts = 0
  $doc = $word.Documents.Open([string]$inputPath)
  $doc.SaveAs2([string]$outputPath, 17)
} finally {
  if ($null -ne $doc) {
    $doc.Close($false)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc)
  }
  if ($null -ne $word) {
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
'''


def validate_pdf(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 100:
        raise ValueError("Microsoft Word 未生成有效 PDF")
    if not path.read_bytes()[:5] == b"%PDF-":
        raise ValueError("生成文件不是有效 PDF")


def replace_pdf_first_page(original: Path, replacement: Path, output: Path) -> Path:
    """以新 PDF 的唯一页面替换原 PDF 首页，并保留原 PDF 的后续页面。"""
    resolved_output = output.resolve()
    if resolved_output in {original.resolve(), replacement.resolve()}:
        raise ValueError("PDF 首页替换必须输出到独立的临时文件")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with original.open("rb") as original_stream, replacement.open(
            "rb"
        ) as replacement_stream:
            original_reader = PdfReader(original_stream)
            replacement_reader = PdfReader(replacement_stream)
            if original_reader.is_encrypted:
                raise ValueError("原 PDF 已加密，无法替换第一页")
            if replacement_reader.is_encrypted:
                raise ValueError("新生成的 PDF 已加密，无法用于替换第一页")
            if not original_reader.pages:
                raise ValueError("原 PDF 没有可替换的页面")
            if len(replacement_reader.pages) != 1:
                raise ValueError("新生成的联系单 PDF 必须恰好为一页")

            original_page_count = len(original_reader.pages)
            writer = PdfWriter()
            writer.add_page(replacement_reader.pages[0])
            for page in original_reader.pages[1:]:
                writer.add_page(page)
            metadata = original_reader.metadata or {}
            if metadata:
                writer.add_metadata(
                    {
                        str(key): str(value)
                        for key, value in metadata.items()
                        if value is not None
                    }
                )
            with output.open("wb") as output_stream:
                writer.write(output_stream)

        validate_pdf(output)
        with output.open("rb") as output_stream:
            page_count = len(PdfReader(output_stream).pages)
        if page_count != original_page_count:
            raise ValueError("替换首页后的 PDF 页数不正确")
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise


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
        ]
        environment = os.environ.copy()
        environment["MULTIDOCU_INPUT_PATH"] = str(docx.resolve())
        environment["MULTIDOCU_OUTPUT_PATH"] = str(pdf.resolve())
    else:
        raise RuntimeError("自动导出 PDF 目前仅支持安装了 Microsoft Word 的 macOS/Windows")
    try:
        run_options = {
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": 180,
        }
        if system == "Windows":
            run_options["env"] = environment
        subprocess.run(command, **run_options)
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 Microsoft Word 导出所需的系统命令") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Microsoft Word 导出 PDF 超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "未知错误").strip()
        raise RuntimeError(f"Microsoft Word 导出 PDF 失败: {detail}") from exc
    validate_pdf(pdf)
    return pdf
