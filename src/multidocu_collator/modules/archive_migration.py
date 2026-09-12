"""将现有存档复制到独立归档目录，并生成离线索引。"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .file_utils import atomic_replace_text
from .repository import build_dataset, load_dataset, save_dataset
from .scanner import scan_data_root


MIGRATION_JSON_NAME = "存档迁移数据.json"
MIGRATION_HTML_NAME = "存档检索.html"


def _safe_destination(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("目标目录不能是资料根目录本身或其子目录")
    return destination


def _copy_directory(source: Path, destination: Path) -> tuple[list[str], set[str]]:
    """逐文件复制，以便个别被占用文件不会中断整批迁移。"""
    warnings: list[str] = []
    skipped: set[str] = set()

    def on_walk_error(exc: OSError) -> None:
        path = Path(exc.filename) if exc.filename else source
        try:
            relative = path.resolve().relative_to(source.resolve()).as_posix()
        except ValueError:
            relative = path.name
        warnings.append(
            f"迁移时无法读取目录“{relative}”（{type(exc).__name__}），已跳过其中资料"
        )

    for current, _, file_names in os.walk(source, onerror=on_walk_error):
        current_path = Path(current)
        target_directory = destination / current_path.relative_to(source)
        target_directory.mkdir(parents=True, exist_ok=True)
        for file_name in file_names:
            source_file = current_path / file_name
            relative = source_file.relative_to(source).as_posix()
            try:
                shutil.copy2(source_file, target_directory / file_name)
            except (PermissionError, OSError) as exc:
                skipped.add(relative)
                warnings.append(
                    f"迁移时无法复制资料文件“{relative}”（{type(exc).__name__}），已跳过；"
                    "请关闭占用该文件的软件后重新运行迁移"
                )
    return warnings, skipped


def _copy_record(
    source_root: Path, destination_root: Path, record: dict[str, Any]
) -> tuple[str, list[str]]:
    source_dir = (source_root / str(record["folder_path"])).resolve()
    if not source_dir.is_dir() or source_dir.parent != source_root.resolve():
        raise FileNotFoundError(f"存档目录不存在或不在根目录下: {source_dir}")
    relative_dir = Path(str(record.get("discipline") or "未分类")) / source_dir.name
    destination_dir = destination_root / relative_dir
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    copy_warnings, skipped = _copy_directory(source_dir, destination_dir)
    if copy_warnings:
        record["warnings"] = [*(record.get("warnings") or []), *copy_warnings]
        record["status"] = "needs_review"
    record["folder_path"] = relative_dir.as_posix()
    copied_files: list[dict[str, Any]] = []
    for item in record.get("files") or []:
        original = (source_root / Path(str(item.get("path") or "").replace("/", "\\"))).resolve()
        if not original.is_relative_to(source_dir):
            raise ValueError(f"资料文件路径超出存档目录: {item.get('path')}")
        relative_file = original.relative_to(source_dir).as_posix()
        if relative_file in skipped:
            continue
        item["path"] = (relative_dir / relative_file).as_posix()
        copied_files.append(item)
    record["files"] = copied_files
    word_fields = record.get("word_fields") or {}
    if word_fields.get("source_path"):
        original_word = (
            source_root / Path(str(word_fields["source_path"]).replace("/", "\\"))
        ).resolve()
        if original_word.is_relative_to(source_dir):
            relative_word = original_word.relative_to(source_dir).as_posix()
            word_fields["source_path"] = (
                "" if relative_word in skipped else (relative_dir / relative_word).as_posix()
            )
    return relative_dir.as_posix(), copy_warnings


def _html(data: dict[str, Any], json_name: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return MIGRATION_HTML_TEMPLATE.replace("__DATA__", payload).replace("__JSON_NAME__", json_name)


def migrate_archive(source_root: Path, destination_root: Path) -> dict[str, Any]:
    """复制存档记录及全部附件，并在目标根目录生成 JSON/HTML 索引。"""
    source = source_root.resolve()
    destination = _safe_destination(source, destination_root)
    if not source.is_dir():
        raise FileNotFoundError(f"资料根目录不存在: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    records, unmatched, ignored = scan_data_root(source)
    previous = None
    for candidate in sorted(source.glob("*数据.json")):
        try:
            previous = load_dataset(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if previous is not None:
            break
    copied: list[str] = []
    copy_warnings: list[str] = []
    for record in records:
        copied_path, record_warnings = _copy_record(source, destination, record)
        copied.append(copied_path)
        copy_warnings.extend(record_warnings)
    data, _, summary = build_dataset(
        root=destination,
        records=records,
        unmatched_files=unmatched,
        ignored_files=ignored,
        previous=previous,
    )
    data["migration"] = {
        "source_root": str(source),
        "directory_layout": "专业/原存档目录",
        "migrated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "copied_records": copied,
        "copy_warnings": copy_warnings,
    }
    json_path = destination / MIGRATION_JSON_NAME
    html_path = destination / MIGRATION_HTML_NAME
    save_dataset(json_path, data)
    atomic_replace_text(html_path, _html(data, MIGRATION_JSON_NAME))
    return {
        "source_root": str(source),
        "destination_root": str(destination),
        "records": len(records),
        "summary": summary,
        "json_path": str(json_path),
        "html_path": str(html_path),
        "copied_directories": copied,
        "copy_warnings": copy_warnings,
    }


MIGRATION_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>存档检索</title>
  <style>
    *{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#17212b;font-family:"Microsoft YaHei",sans-serif}
    header{padding:20px 24px;color:#fff;background:#17324d}h1{margin:0 0 8px;font-size:24px}main{padding:16px 20px}
    .toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:12px;background:#fff;border:1px solid #d9e1e8;border-radius:8px}
    .toolbar input{flex:1;min-width:240px;padding:8px;border:1px solid #aebdca;border-radius:5px}
    .toolbar button{padding:8px 12px;color:#fff;border:0;border-radius:5px;background:#245b8f;cursor:pointer}.count{margin-left:auto;padding:8px;color:#667583}
    .table-wrap{margin-top:12px;overflow:auto;background:#fff;border:1px solid #d9e1e8}table{width:100%;min-width:1100px;border-collapse:collapse;table-layout:fixed;font-size:14px}
    th,td{padding:7px 6px;border-bottom:1px solid #e5eaee;text-align:left;vertical-align:top}th{position:sticky;top:0;z-index:2;color:#fff;background:#17324d}
    th:nth-child(1),td:nth-child(1){width:9%}th:nth-child(2),td:nth-child(2){width:10%}th:nth-child(3),td:nth-child(3){width:10%}th:nth-child(4),td:nth-child(4){width:19%}th:nth-child(5),td:nth-child(5){width:32%}th:nth-child(6),td:nth-child(6){width:9%}th:nth-child(7),td:nth-child(7){width:11%}
    .column-head{display:flex;flex-direction:column;gap:4px}.column-filter{width:100%;min-height:28px;padding:3px 4px;color:#17212b;border:1px solid #91a8ba;border-radius:4px;background:#fff}
    tbody tr{height:92px}.cell-scroll{height:76px;overflow:auto;white-space:pre-line;line-height:1.45}.subject-link{color:#174d7a;font-weight:700;text-decoration:none}.subject-link:hover{text-decoration:underline}
    .files{display:flex;flex-wrap:wrap;align-content:flex-start;gap:4px;height:76px;overflow:auto}.files a{padding:3px 5px;color:#174d7a;background:#f1f7fb;border:1px solid #bed3e4;border-radius:4px;text-decoration:none;white-space:nowrap}.files a:hover{color:#fff;background:#245b8f}
  </style>
</head>
<body>
  <header><h1>存档检索</h1><div id="meta"></div></header>
  <main>
    <div class="toolbar"><input id="q" placeholder="搜索专业、编号、日期、主题、需求内容"><button id="exportJson">导出当前 JSON</button><button id="exportCsv">导出当前 CSV</button><span class="count" id="count"></span></div>
    <div class="table-wrap"><table><thead><tr>
      <th><div class="column-head"><span>专业</span><select id="disciplineFilter" class="column-filter"><option value="">全部专业</option></select></div></th>
      <th>编号</th><th>日期</th><th>主题</th><th>需求内容</th>
      <th><div class="column-head"><span>是否需要出变更</span><select id="changeFilter" class="column-filter"><option value="">全部</option><option value="是">是</option><option value="否">否</option></select></div></th>
      <th>资料文件</th>
    </tr></thead><tbody id="rows"></tbody></table></div>
  </main>
  <script>
    const DATA=__DATA__,JSON_NAME="__JSON_NAME__";
    const q=document.getElementById('q'),rows=document.getElementById('rows'),count=document.getElementById('count'),disciplineFilter=document.getElementById('disciplineFilter'),changeFilter=document.getElementById('changeFilter');
    const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const relativeHref=value=>String(value??'').split('/').map(encodeURIComponent).join('/');
    const list=()=>[...(DATA.records||[])].sort((a,b)=>String(a.document_code||'').localeCompare(String(b.document_code||''),'zh-CN',{numeric:true,sensitivity:'base'}));
    const roleLabel=f=>{const role=String(f.role||''),extension=String(f.extension||'').toLowerCase(),name=String(f.name||'');if(extension==='.dwg')return'DWG';if(extension==='.pdf'&&(role==='figure_pdf'||name.includes('附图')))return'PDF附图';return({source_word:'Word',issued_pdf:'PDF',signed_scan:'扫描件',attachment_pdf:'附件 PDF',image_attachment:'图片',drawing_source:'图纸',auxiliary_file:'其他'})[role]||(extension.replace('.','').toUpperCase()||'其他')};
    function render(){
      const term=q.value.trim().toLowerCase(),discipline=disciplineFilter.value,change=changeFilter.value;
      const filtered=list().filter(r=>(!term||[r.discipline,r.document_code,r.folder_date,r.subject,r['需求内容'],r['致送单位']].join(' ').toLowerCase().includes(term))&&(!discipline||r.discipline===discipline)&&(!change||(r['是否需要变更']==='是'?'是':'否')===change));
      rows.innerHTML=filtered.map(r=>{const files=(r.files||[]).map(f=>`<a href="${relativeHref(f.path)}" target="_blank" title="${esc(f.name)}">${esc(roleLabel(f))}</a>`).join('');const folder=relativeHref(String(r.folder_path||'').replace(/\/$/,'')+'/');return `<tr><td>${esc(r.discipline)}</td><td>${esc(r.document_code)}</td><td>${esc(r.folder_date)}</td><td><div class="cell-scroll"><a class="subject-link" href="${folder}" target="_blank" title="打开资料文件夹">${esc(r.subject)}</a></div></td><td><div class="cell-scroll">${esc(r['需求内容'])}</div></td><td>${r['是否需要变更']==='是'?'是':'否'}</td><td><div class="files">${files||'—'}</div></td></tr>`}).join('');
      count.textContent=`显示 ${filtered.length} / ${list().length} 条`;return filtered;
    }
    function download(name,text,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
    document.getElementById('exportJson').onclick=()=>download(JSON_NAME,JSON.stringify({schema_version:DATA.schema_version,records:render()},null,2),'application/json');
    document.getElementById('exportCsv').onclick=()=>{const rs=render(),head=['专业','编号','日期','主题','致送单位','需求内容','是否需要出变更'];const cell=v=>`"${String(v??'').replace(/"/g,'""').replace(/\r?\n/g,' ')}"`;download('存档检索.csv',[head.join(','),...rs.map(r=>[r.discipline,r.document_code,r.folder_date,r.subject,r['致送单位'],r['需求内容'],r['是否需要变更']==='是'?'是':'否'].map(cell).join(','))].join('\r\n'),'text/csv;charset=utf-8')};
    [...new Set(list().map(r=>String(r.discipline||'')).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN')).forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;disciplineFilter.append(option)});
    q.oninput=render;disciplineFilter.onchange=render;changeFilter.onchange=render;document.getElementById('meta').textContent=`共 ${list().length} 条 · 生成时间 ${DATA.updated_at||''}`;render();
  </script>
</body>
</html>'''
