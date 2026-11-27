"""Use the installed Bluebeam Revu eXtreme Script Engine to reprint a PDF as A4."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..context import AppContext
from ..modules.desktop import resolve_relative_file
from ..modules.file_utils import sha256_file
from ..modules.pdf_exporter import validate_pdf
from ..modules.repository import load_dataset, save_dataset
from .build_archive_flow import run_build_archive
from .mutation_lock import RECORD_MUTATION_LOCK


def _script_engine() -> Path:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Bluebeam Software" / "Bluebeam Revu" / "20" / "Revu" / "ScriptEngine.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Bluebeam Software" / "Bluebeam Revu" / "20" / "Revu" / "ScriptEngine.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到 Bluebeam Revu 20 ScriptEngine.exe")


def _quote_script(value: str) -> str:
    return "'" + value.replace("|", "||").replace("'", "|'" ) + "'"


def print_pdf_a4(context: AppContext, payload: dict[str, Any]) -> dict[str, Any]:
    relative = payload.get("path")
    if not isinstance(relative, str):
        raise ValueError("path 必须是相对路径字符串")
    with RECORD_MUTATION_LOCK:
        dataset = load_dataset(context.json_path)
        if dataset is None:
            raise FileNotFoundError("JSON 数据库不存在")
        if int(payload.get("dataset_revision") or 0) != int(dataset.get("dataset_revision") or 0):
            raise ValueError("页面数据已经更新，请刷新页面后重新操作")
        source = resolve_relative_file(context.data_root, relative)
        if source.suffix.lower() != ".pdf":
            raise ValueError("只支持打印 PDF 文件")
        with tempfile.TemporaryDirectory(prefix=".bluebeam_a4_", dir=source.parent) as temp_dir:
            output = Path(temp_dir) / source.name
            script = (
                f"Open({_quote_script(str(source))})\n"
                f"PrintToFile({_quote_script(str(output))}, 'Bluebeam PDF', 'A4', false, '-1', 1, 1, 0, false, 1)\n"
                "Close()\n"
            )
            script_path = Path(temp_dir) / "print_a4.bci"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [str(_script_engine()), f"Script({_quote_script(str(script_path))})"],
                capture_output=True, text=True, timeout=300, check=False,
            )
            if result.returncode != 0 or not output.is_file():
                details = (result.stderr or result.stdout or "没有生成输出文件").strip()
                raise RuntimeError(f"Bluebeam A4 打印失败：{details[-1200:]}")
            validate_pdf(output)
            backup = source.with_suffix(source.suffix + ".bak")
            shutil.copy2(source, backup)
            output.replace(source)
        refreshed = run_build_archive(context)
        current = load_dataset(context.json_path)
        if current is None:
            raise RuntimeError("打印完成但无法读取更新后的 JSON")
        for record in current.get("records") or []:
            for item in record.get("files") or []:
                if item.get("path") == relative:
                    item["bluebeam_a4"] = True
                    item["bluebeam_a4_sha256"] = item.get("sha256") or sha256_file(source)
        save_dataset(context.json_path, current)
        return {"ok": True, "path": relative, "dataset_revision": refreshed.get("dataset_revision")}


def print_all_pdfs_a4(context: AppContext) -> dict[str, Any]:
    data = load_dataset(context.json_path)
    if data is None:
        raise FileNotFoundError("JSON 数据库不存在")
    paths = [
        str(item.get("path") or "")
        for record in data.get("records") or []
        for item in record.get("files") or []
        if item.get("role") == "issued_pdf"
        and str(item.get("extension") or "").lower() == ".pdf"
    ]
    results = []
    for relative in paths:
        current = load_dataset(context.json_path) or {}
        results.append(print_pdf_a4(context, {
            "path": relative,
            "dataset_revision": current.get("dataset_revision"),
        }))
    return {"ok": True, "total": len(paths), "results": results}
