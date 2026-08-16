"""由正式 JSON 数据生成离线 HTML 汇总。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .file_utils import atomic_replace_text


STATUS_LABELS = {
    "complete": "资料齐全",
    "needs_review": "待核对",
    "incomplete": "资料不完整",
}
ROLE_LABELS = {
    "source_word": "Word",
    "issued_pdf": "PDF",
    "signed_scan": "扫描件",
    "attachment_pdf": "附件",
    "image_attachment": "图片",
    "drawing_source": "图纸",
    "auxiliary_file": "其他",
}


def _href(relative_path: str) -> str:
    return quote(relative_path, safe="/")


def _directory_href(relative_path: str) -> str:
    return quote(relative_path.rstrip("/") + "/", safe="/")


def build_summary_view(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in data.get("records") or []:
        files = [
            {
                "name": item.get("name") or "",
                "role": item.get("role") or "auxiliary_file",
                "role_label": ROLE_LABELS.get(
                    str(item.get("role") or ""), str(item.get("role") or "其他")
                ),
                "href": _href(str(item.get("path") or "")),
            }
            for item in record.get("files") or []
        ]
        word = record.get("word_fields") or {}
        rows.append(
            {
                "record_id": record.get("record_id") or "",
                "discipline": record.get("discipline") or "",
                "sequence_no": record.get("sequence_no") or "",
                "folder_date": record.get("folder_date") or "",
                "subject": record.get("subject") or "",
                "folder_path": record.get("folder_path") or "",
                "folder_href": _directory_href(str(record.get("folder_path") or "")),
                "requirement_content": record.get("需求内容") or "",
                "word_date": word.get("document_date") or "",
                "word_subject": word.get("subject") or "",
                "recipient": word.get("recipient") or "",
                "status": record.get("status") or "",
                "status_label": STATUS_LABELS.get(
                    str(record.get("status") or ""), str(record.get("status") or "")
                ),
                "warnings": record.get("warnings") or [],
                "files": files,
            }
        )
    status_counts: dict[str, int] = {}
    for row in rows:
        key = str(row["status"])
        status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "schema_version": 1,
        "dataset_revision": int(data.get("dataset_revision") or 0),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "record_count": len(rows),
        "warning_count": sum(bool(row["warnings"]) for row in rows),
        "status_counts": status_counts,
        "disciplines": sorted({str(row["discipline"]) for row in rows}),
        "rows": rows,
    }


def _json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def export_summary_html(data: dict[str, Any], output: Path) -> Path:
    view = build_summary_view(data)
    content = HTML_TEMPLATE.replace("__SUMMARY_DATA__", _json_for_script(view))
    atomic_replace_text(output, content)
    return output


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>酒店需求工作联系单汇总</title>
  <style>
    :root { --navy:#17324d; --blue:#245b8f; --line:#d9e1e8; --bg:#f3f6f8;
      --muted:#667583; --ok:#26734d; --warn:#a15c00; --bad:#a43333; }
    * { box-sizing:border-box; }
    body { margin:0; color:#17212b; background:var(--bg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }
    header { padding:24px 28px 18px; color:white; background:linear-gradient(120deg,var(--navy),var(--blue)); }
    h1 { margin:0 0 8px; font-size:26px; }
    #subtitle { margin:0; opacity:.86; font-size:14px; }
    main { padding:18px 22px 28px; }
    .metrics { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:12px; margin-bottom:14px; }
    .metric { padding:13px 16px; border:1px solid var(--line); border-radius:10px; background:white; box-shadow:0 2px 9px #17324d0c; }
    .metric b { display:block; margin-top:3px; font-size:22px; color:var(--navy); }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; padding:12px; border:1px solid var(--line); border-radius:10px 10px 0 0; background:white; }
    input, select { min-height:38px; padding:7px 10px; border:1px solid #b9c6d0; border-radius:7px; background:white; font:inherit; }
    input { flex:1; min-width:260px; }
    .visible-count { margin-left:auto; color:var(--muted); font-size:14px; }
    .table-wrap { max-height:calc(100vh - 270px); overflow:auto; border:1px solid var(--line); border-top:0; background:white; }
    table { width:100%; border-collapse:separate; border-spacing:0; table-layout:fixed; font-size:13px; }
    th { position:sticky; top:0; z-index:2; padding:10px 7px; color:white; background:var(--navy); text-align:left; }
    .column-header { display:flex; flex-direction:column; gap:6px; }
    .column-filter { width:100%; min-height:30px; padding:3px 5px; color:#17212b; border-color:#91a8ba; border-radius:5px; font-size:12px; font-weight:400; }
    td { padding:9px 7px; border-right:1px solid #edf1f4; border-bottom:1px solid #e5eaee; vertical-align:top; overflow-wrap:anywhere; white-space:pre-line; }
    tbody tr:hover { background:#f7fbff; }
    .subject-link { color:#174d7a; font-weight:600; text-decoration:none; }
    .subject-link:hover { color:#0c6db2; text-decoration:underline; }
    th:nth-child(1),td:nth-child(1) { width:4%; text-align:center; }
    th:nth-child(2),td:nth-child(2) { width:7%; }
    th:nth-child(3),td:nth-child(3) { width:5%; text-align:center; }
    th:nth-child(4),td:nth-child(4) { width:8%; }
    th:nth-child(5),td:nth-child(5) { width:16%; }
    th:nth-child(6),td:nth-child(6) { width:29%; }
    th:nth-child(7),td:nth-child(7) { width:20%; }
    th:nth-child(8),td:nth-child(8) { width:11%; }
    .content { max-height:9.2em; overflow:auto; line-height:1.55; }
    .files { display:flex; flex-wrap:wrap; gap:5px; white-space:normal; }
    .file { display:inline-block; max-width:100%; padding:3px 6px; color:#174d7a; border:1px solid #bed3e4; border-radius:5px; background:#f3f9fd; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .file:hover { color:white; background:var(--blue); }
    .status { display:inline-block; padding:3px 7px; border-radius:999px; font-weight:700; }
    .status.complete { color:var(--ok); background:#e7f5ed; }
    .status.needs_review { color:var(--warn); background:#fff2dd; }
    .status.incomplete { color:var(--bad); background:#fdeaea; }
    details { margin-top:7px; color:var(--muted); }
    summary { cursor:pointer; color:#36566f; }
    .warnings { margin:6px 0 0; padding-left:18px; color:#8a4e00; white-space:normal; }
    .empty { padding:40px; color:var(--muted); text-align:center; }
    @media (max-width:1100px) { main{padding:10px}.metrics{grid-template-columns:1fr 1fr}.table-wrap{max-height:none} table{min-width:1200px} }
    @media print { header,.metrics,.toolbar,.column-filter{display:none}.table-wrap{max-height:none;overflow:visible;border:0} th{position:static} body{background:white} table{font-size:9px} }
  </style>
</head>
<body>
  <header><h1>酒店需求工作联系单汇总</h1><p id="subtitle"></p></header>
  <main>
    <section class="metrics">
      <div class="metric">联系单总数<b id="total"></b></div>
      <div class="metric">资料齐全<b id="complete"></b></div>
      <div class="metric">待核对<b id="review"></b></div>
      <div class="metric">有提示记录<b id="warnings"></b></div>
    </section>
    <section class="toolbar">
      <input id="search" type="search" placeholder="搜索专业、编号、日期、主题、需求内容……">
      <span class="visible-count">当前显示 <b id="visible"></b> 条</span>
    </section>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>序号</th>
          <th><div class="column-header"><span>专业</span><select id="disciplineFilter" class="column-filter" aria-label="按专业筛选"><option value="">全部专业</option></select></div></th>
          <th>编号</th><th>目录日期</th><th>主题</th><th>需求内容</th><th>资料文件</th>
          <th><div class="column-header"><span>状态 / 核对</span><select id="statusFilter" class="column-filter" aria-label="按状态筛选"><option value="">全部状态</option><option value="complete">资料齐全</option><option value="needs_review">待核对</option><option value="incomplete">资料不完整</option></select></div></th>
        </tr></thead>
        <tbody id="body"></tbody>
      </table>
      <div id="empty" class="empty" hidden>没有符合当前条件的记录</div>
    </div>
  </main>
  <script id="summaryData" type="application/json">__SUMMARY_DATA__</script>
  <script>
    const data=JSON.parse(document.getElementById('summaryData').textContent);
    const $=id=>document.getElementById(id);
    const esc=value=>String(value??'');
    $('subtitle').textContent=`数据版本 ${data.dataset_revision} · 生成时间 ${data.generated_at}`;
    $('total').textContent=data.record_count;
    $('complete').textContent=data.status_counts.complete||0;
    $('review').textContent=data.status_counts.needs_review||0;
    $('warnings').textContent=data.warning_count;
    data.disciplines.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;$('disciplineFilter').append(option)});
    function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=esc(text);if(className)el.className=className;return el}
    async function openDirectory(event,row){
      const localHosts=['127.0.0.1','localhost','::1'];
      if(!['http:','https:'].includes(location.protocol)||!localHosts.includes(location.hostname))return;
      event.preventDefault();
      try{
        const response=await fetch('/api/open-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:row.folder_path})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'目录打开失败');
      }catch(error){alert(`目录打开失败：${error.message}`)}
    }
    function render(){
      const query=$('search').value.trim().toLowerCase(), discipline=$('disciplineFilter').value, status=$('statusFilter').value;
      const rows=data.rows.filter(row=>{
        const haystack=[row.discipline,row.sequence_no,row.folder_date,row.subject,row.requirement_content,row.word_date,row.word_subject,row.recipient,...row.warnings].join(' ').toLowerCase();
        return (!query||haystack.includes(query))&&(!discipline||row.discipline===discipline)&&(!status||row.status===status);
      });
      const body=$('body');body.replaceChildren();
      rows.forEach((row,index)=>{
        const tr=node('tr');
        [index+1,row.discipline,row.sequence_no,row.folder_date].forEach(value=>tr.append(node('td',value)));
        const subjectCell=node('td'),subjectLink=node('a',row.subject,'subject-link');subjectLink.href=row.folder_href;subjectLink.title='打开对应资料目录';subjectLink.addEventListener('click',event=>openDirectory(event,row));subjectCell.append(subjectLink);tr.append(subjectCell);
        const content=node('td');content.append(node('div',row.requirement_content||'—','content'));tr.append(content);
        const fileCell=node('td'),files=node('div',undefined,'files');
        row.files.forEach(file=>{const a=node('a',file.role_label,'file');a.href=file.href;a.title=file.name;files.append(a)});fileCell.append(files);tr.append(fileCell);
        const state=node('td');state.append(node('span',row.status_label,`status ${row.status}`));
        const details=node('details'),summary=node('summary',`Word 信息与提示（${row.warnings.length}）`);details.append(summary);
        const info=node('div',`Word日期：${row.word_date||'—'}\nWord事由：${row.word_subject||'—'}\n致送单位：${row.recipient||'—'}`);details.append(info);
        if(row.warnings.length){const list=node('ul',undefined,'warnings');row.warnings.forEach(w=>list.append(node('li',w)));details.append(list)}
        state.append(details);tr.append(state);body.append(tr);
      });
      $('visible').textContent=rows.length;$('empty').hidden=rows.length!==0;
    }
    ['search','disciplineFilter','statusFilter'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',render));render();
  </script>
</body>
</html>
'''
