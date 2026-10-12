"""主体工作联系单原始资料备份与目录整理。"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..modules.file_utils import sha256_file
from ..modules.work_contact import FOLDER_NAME, scan_work_contacts
from .mutation_lock import RECORD_MUTATION_LOCK
from .work_contact_flow import HTML_NAME, JSON_NAME, build_work_contact_archive


BACKUP_PREFIX = "_backup_"
BACKUP_MANIFEST = "backup_manifest.json"


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part.startswith(BACKUP_PREFIX) or part == "_trash" for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"资料目录包含符号链接，无法安全备份: {relative}")
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def backup_work_contacts(root: Path) -> Path:
    """在原目录保存完整副本与逐文件 SHA-256 清单，复制核验后才发布备份。"""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    backup = root / f"{BACKUP_PREFIX}{stamp}"
    counter = 2
    while backup.exists() or (root / f".{backup.name}.pending").exists():
        backup = root / f"{BACKUP_PREFIX}{stamp}_{counter}"
        counter += 1
    staging = root / f".{backup.name}.pending"
    # Windows 上移动目录前，固定并核对两个目标都直接位于预期资料根目录。
    if staging.resolve().parent != root or backup.resolve().parent != root:
        raise ValueError("备份目标越出主体工作联系单目录")
    sources = _source_files(root)
    staging.mkdir()
    manifest = []
    for source in sources:
        relative = source.relative_to(root)
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        original_hash = sha256_file(source)
        shutil.copy2(source, destination)
        if sha256_file(destination) != original_hash:
            raise OSError(f"备份校验失败: {relative.as_posix()}")
        manifest.append({
            "path": relative.as_posix(),
            "size": source.stat().st_size,
            "sha256": original_hash,
        })
    (staging / BACKUP_MANIFEST).write_text(
        json.dumps({"source_root": str(root), "files": manifest}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    staging.replace(backup)
    return backup


def plan_work_contact_organization(root: Path, *, scheme: str) -> list[dict]:
    """生成不修改资料的逐文件迁移计划。"""
    if scheme not in {"unified", "by_kind"}:
        raise ValueError("编号方式必须是 unified 或 by_kind")
    root = root.resolve(strict=True)
    if any(path.is_dir() and FOLDER_NAME.match(path.name) for path in root.iterdir()):
        raise ValueError("资料根目录已经包含整理后的联系单目录")
    records, _ = scan_work_contacts(root)
    counters: dict[str, int] = {}
    plan: list[dict] = []
    for record in records:
        kind = str(record.get("document_code") or "").rstrip("—- ")
        discipline = "主体" if scheme == "unified" else kind
        if discipline not in {"主体", "质保", "维保"}:
            raise ValueError(f"无法判断联系单类别: {record['subject']}")
        counters[discipline] = counters.get(discipline, 0) + 1
        code = f"{discipline}-{counters[discipline]:03d}"
        subject = str(record["subject"]).strip()
        folder_name = f"{code}-{record['folder_date']}_{subject}"
        directory = root / folder_name
        if directory.exists():
            raise FileExistsError(f"目标目录已存在: {directory}")
        base_name = f"工作联系单（{code}）_{subject}"
        moves: list[tuple[str, str]] = []
        for item in record["files"]:
            source = root / str(item["path"])
            if source.parent != root:
                raise ValueError(f"联系单源文件不在资料根目录: {source}")
            if item["role"] == "source_word":
                target_name = f"{base_name}.docx"
            elif item["role"] == "issued_pdf":
                target_name = f"{base_name}.pdf"
            elif item["role"] == "signed_scan":
                target_name = f"{base_name}_扫描件.pdf"
            else:
                target_name = source.name
            moves.append((source.name, target_name))
        original_word = root / str(record["files"][0]["path"])
        duplicate = root / f"{original_word.stem} - 副本.docx"
        if duplicate.is_file():
            moves.append((duplicate.name, f"{base_name}_副本.docx"))
        plan.append({"code": code, "folder": folder_name, "moves": moves})
    target_names = [item["folder"] for item in plan]
    if len(target_names) != len(set(target_names)):
        raise ValueError("迁移计划产生了重复目录")
    return plan


def organize_work_contacts(root: Path, backup: Path, *, scheme: str) -> dict:
    """核对备份并原子移动平铺文件，失败时恢复原目录与生成成果。"""
    with RECORD_MUTATION_LOCK:
        root = root.resolve(strict=True)
        backup = backup.resolve(strict=True)
        if backup.parent != root or not backup.name.startswith(BACKUP_PREFIX):
            raise ValueError("备份必须位于主体工作联系单资料根目录")
        manifest = json.loads((backup / BACKUP_MANIFEST).read_text(encoding="utf-8"))
        if Path(manifest.get("source_root") or "").resolve() != root:
            raise ValueError("备份来源目录与当前目录不一致")
        backup_hashes = {
            item["path"]: item["sha256"] for item in manifest.get("files") or []
        }
        plan = plan_work_contact_organization(root, scheme=scheme)
        moves: list[tuple[Path, Path]] = []
        directories: list[Path] = []
        for entry in plan:
            directory = root / entry["folder"]
            if directory.resolve().parent != root:
                raise ValueError("目标目录越出资料根目录")
            for old_name, new_name in entry["moves"]:
                source = root / old_name
                destination = directory / new_name
                if source.resolve().parent != root or destination.parent != directory:
                    raise ValueError("迁移文件路径越出预期目录")
                if not source.is_file() or destination.exists():
                    raise FileNotFoundError(f"迁移源文件缺失或目标已存在: {old_name}")
                relative = source.relative_to(root).as_posix()
                if backup_hashes.get(relative) != sha256_file(source):
                    raise ValueError(f"原始文件与备份不一致: {old_name}")
                moves.append((source, destination))
            directories.append(directory)
        moved: list[tuple[Path, Path]] = []
        try:
            for directory in directories:
                directory.mkdir()
            for source, destination in moves:
                source.replace(destination)
                moved.append((source, destination))
            result = build_work_contact_archive(root)
            if result["records"] != len(plan):
                raise ValueError("整理后联系单记录数不一致")
        except Exception:
            for source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    destination.replace(source)
            for directory in reversed(directories):
                if directory.exists():
                    directory.rmdir()
            for name in (JSON_NAME, HTML_NAME):
                saved = backup / name
                if saved.is_file():
                    shutil.copy2(saved, root / name)
            raise
        return {
            "records": len(plan),
            "moved_files": len(moved),
            "backup": str(backup),
            "json_path": result["json_path"],
            "html_path": result["html_path"],
        }


def renumber_organized_work_contacts(root: Path, backup: Path) -> dict:
    """把已按“主体”统一编号的目录改为质保、维保各自连续编号。"""
    with RECORD_MUTATION_LOCK:
        root = root.resolve(strict=True)
        backup = backup.resolve(strict=True)
        if backup.parent != root or not backup.name.startswith(BACKUP_PREFIX):
            raise ValueError("备份必须位于主体工作联系单资料根目录")
        manifest = json.loads((backup / BACKUP_MANIFEST).read_text(encoding="utf-8"))
        if Path(manifest.get("source_root") or "").resolve() != root:
            raise ValueError("备份来源目录与当前目录不一致")
        expected_hashes = Counter(
            item["sha256"] for item in manifest.get("files") or []
            if "/" not in item["path"] and item["path"].lower().endswith((".docx", ".pdf"))
        )
        records, _ = scan_work_contacts(root)
        if not records or any(not record.get("folder_path") for record in records):
            raise ValueError("联系单尚未全部整理为独立目录")
        if any(record.get("discipline") != "主体" for record in records):
            raise ValueError("当前目录不是统一“主体”编号，无法重复调整")
        actual_hashes = Counter(
            sha256_file(root / item["path"])
            for record in records for item in record["files"]
        )
        if actual_hashes != expected_hashes:
            raise ValueError("已整理资料与原始备份文件不一致")

        counters: dict[str, int] = {}
        changes: list[tuple[Path, Path, list[tuple[Path, Path]]]] = []
        for record in records:
            match = re.match(r"^(质保|维保)[—-]?", str(record.get("original_document_no") or ""))
            if match is None:
                raise ValueError(f"无法判断原件类别: {record['document_code']}")
            kind = match.group(1)
            counters[kind] = counters.get(kind, 0) + 1
            new_code = f"{kind}-{counters[kind]:03d}"
            old_code = str(record["document_code"])
            source_dir = root / str(record["folder_path"])
            target_dir = root / f"{new_code}-{record['folder_date']}_{record['subject']}"
            if (source_dir.resolve().parent != root or target_dir.resolve().parent != root
                    or target_dir.exists()):
                raise ValueError(f"目标目录不安全或已存在: {target_dir.name}")
            file_changes: list[tuple[Path, Path]] = []
            for item in record["files"]:
                source = root / str(item["path"])
                old_marker = f"（{old_code}）"
                if source.parent != source_dir or old_marker not in source.name:
                    raise ValueError(f"文件名与目录编号不一致: {source.name}")
                destination = source.with_name(source.name.replace(old_marker, f"（{new_code}）", 1))
                if destination.exists() or destination.parent != source_dir:
                    raise ValueError(f"目标文件已存在或越界: {destination.name}")
                file_changes.append((source, destination))
            changes.append((source_dir, target_dir, file_changes))

        metadata = {
            name: (root / name).read_bytes() if (root / name).is_file() else None
            for name in (JSON_NAME, HTML_NAME)
        }
        moved: list[tuple[Path, Path]] = []
        try:
            for source_dir, target_dir, file_changes in changes:
                source_dir.replace(target_dir)
                moved.append((source_dir, target_dir))
                for source, destination in file_changes:
                    moved_source = target_dir / source.name
                    moved_destination = target_dir / destination.name
                    moved_source.replace(moved_destination)
                    moved.append((moved_source, moved_destination))
            result = build_work_contact_archive(root)
            if result["records"] != len(changes):
                raise ValueError("重新编号后联系单记录数不一致")
        except Exception:
            for source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    destination.replace(source)
            for name, original in metadata.items():
                if original is not None:
                    (root / name).write_bytes(original)
            raise
        return {"records": len(changes), "files": sum(len(files) for _, _, files in changes),
                "by_kind": counters, "backup": str(backup)}
