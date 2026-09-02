"""由正式 JSON 数据生成离线 HTML 汇总。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
    "figure_pdf": "PDF附图",
    "attachment_pdf": "附件 PDF",
    "image_attachment": "图片",
    "drawing_source": "图纸",
    "auxiliary_file": "其他",
}
BEIJING_TIMEZONE = timezone(timedelta(hours=8), name="北京时间")


def _href(relative_path: str) -> str:
    return quote(relative_path, safe="/")


def _directory_href(relative_path: str) -> str:
    return quote(relative_path.rstrip("/") + "/", safe="/")


def build_summary_view(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in data.get("records") or []:
        files = []
        for item in record.get("files") or []:
            role = str(item.get("role") or "auxiliary_file")
            extension = str(item.get("extension") or "").lower()
            name = str(item.get("name") or "")
            type_label = extension.removeprefix(".").upper() or "无扩展名"
            if extension == ".dwg":
                role_label = "DWG"
                kind_class = "dwg"
            elif extension == ".pdf" and (role == "figure_pdf" or "附图" in name):
                role_label = "PDF附图"
                kind_class = "figure-pdf"
            elif role == "attachment_pdf":
                role_label = "附件 PDF"
                kind_class = "attachment-pdf"
            else:
                role_label = ROLE_LABELS.get(role, role or "其他")
                kind_class = ""
            files.append(
                {
                    "name": name,
                    "role": role,
                    "role_label": role_label,
                    "type_label": type_label,
                    "kind_class": kind_class,
                    "path": str(item.get("path") or ""),
                    "href": _href(str(item.get("path") or "")),
                }
            )
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
                "recipient": record.get("致送单位") or word.get("recipient") or "",
                "print_status": (
                    "是" if record.get("需求单已经打印") == "是" else "否"
                ),
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
        "generated_at": datetime.now(BEIJING_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
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
    .metric { position:relative; padding:13px 16px; border:1px solid var(--line); border-radius:10px; background:white; box-shadow:0 2px 9px #17324d0c; }
    .metric b { display:block; margin-top:3px; font-size:22px; color:var(--navy); }
    .warning-metric { cursor:help; }
    .warning-metric:focus { outline:2px solid var(--blue); outline-offset:2px; }
    .metric-tooltip { position:absolute; z-index:20; top:calc(100% + 8px); right:0; width:min(460px,calc(100vw - 32px)); max-height:320px; overflow:auto; padding:11px 13px; color:#17212b; border:1px solid #d7b66a; border-radius:8px; background:#fffdf4; box-shadow:0 10px 28px #17324d30; opacity:0; visibility:hidden; pointer-events:none; transform:translateY(-4px); transition:opacity .15s,transform .15s,visibility .15s; font-size:12px; font-weight:400; line-height:1.5; }
    .warning-metric:hover .metric-tooltip,.warning-metric:focus .metric-tooltip,.warning-metric:focus-within .metric-tooltip { opacity:1; visibility:visible; pointer-events:auto; transform:translateY(0); }
    .warning-preview-item + .warning-preview-item { margin-top:9px; padding-top:9px; border-top:1px solid #eadfbd; }
    .warning-preview-code { display:block; color:var(--navy); font-size:13px; }
    .warning-preview-subject { display:block; margin-top:2px; }
    .warning-preview-message { display:block; margin-top:3px; color:var(--warn); }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; padding:12px; border:1px solid var(--line); border-radius:10px 10px 0 0; background:white; }
    input, select, textarea, button { font:inherit; }
    input, select, textarea { min-height:38px; padding:7px 10px; border:1px solid #b9c6d0; border-radius:7px; background:white; }
    .toolbar input { flex:1; min-width:260px; }
    .refresh-button { min-height:38px; padding:7px 14px; color:white; border:0; border-radius:7px; background:var(--blue); cursor:pointer; font-weight:700; }
    .refresh-button:hover { background:var(--navy); }
    .refresh-button:disabled { opacity:.55; cursor:wait; }
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
    th:nth-child(5),td:nth-child(5) { width:11%; }
    th:nth-child(6),td:nth-child(6) { width:13%; }
    th:nth-child(7),td:nth-child(7) { width:21%; }
    th:nth-child(8),td:nth-child(8) { width:14%; }
    th:nth-child(9),td:nth-child(9) { width:8%; text-align:center; }
    th:nth-child(10),td:nth-child(10) { width:9%; }
    .content { max-height:9.2em; overflow:auto; line-height:1.55; }
    .content-editor textarea { width:100%; min-height:108px; padding:7px; resize:vertical; line-height:1.55; }
    .content-actions { display:flex; flex-wrap:wrap; gap:5px; margin-top:6px; }
    .content-button { flex:1; min-width:76px; padding:6px 5px; border:1px solid #9eb5c7; border-radius:6px; color:#174d7a; background:#f4f9fc; cursor:pointer; font-size:12px; font-weight:700; }
    .content-button:hover { color:white; background:var(--blue); }
    .content-button:disabled { opacity:.55; cursor:not-allowed; }
    .content-save-button { color:var(--ok); border-color:#9fcab3; background:#f0faf5; }
    .files { display:flex; flex-wrap:wrap; gap:5px; white-space:normal; }
    .file { display:inline-block; max-width:100%; padding:3px 6px; color:#174d7a; border:1px solid #bed3e4; border-radius:5px; background:#f3f9fd; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .file:hover { color:white; background:var(--blue); }
    .file.copied { color:white; border-color:var(--ok); background:var(--ok); }
    .file.dwg { color:#5f368a; border-color:#c9afe2; background:#f7f0fc; font-weight:700; }
    .file.dwg:hover { color:white; background:#69418e; }
    .file.attachment-pdf { color:#8a4e00; border-color:#e4c48f; background:#fff7e9; font-weight:700; }
    .file.attachment-pdf:hover { color:white; background:#a15c00; }
    .file.figure-pdf { color:#815b00; border-color:#e1c65b; background:#fff9d8; font-weight:700; }
    .file.figure-pdf:hover { color:white; background:#927000; }
    .status { display:inline-block; padding:3px 7px; border-radius:999px; font-weight:700; }
    .status.complete { color:var(--ok); background:#e7f5ed; }
    .status.needs_review { color:var(--warn); background:#fff2dd; }
    .status.incomplete { color:var(--bad); background:#fdeaea; }
    .print-save-button { background:var(--ok); }
    .print-select { width:100%; min-width:62px; }
    details { margin-top:7px; color:var(--muted); }
    summary { cursor:pointer; color:#36566f; }
    .warnings { margin:6px 0 0; padding-left:18px; color:#8a4e00; white-space:normal; }
    .new-row { position:sticky; bottom:0; z-index:1; background:#eef6fc; box-shadow:0 -2px 8px #17324d1c; }
    .new-row:hover { background:#eef6fc; }
    .new-row td { padding:6px 4px; vertical-align:top; }
    .new-row input,.new-row textarea { width:100%; min-width:0; padding:6px; font-size:12px; }
    .new-row textarea { min-height:70px; resize:vertical; }
    .editable-select { position:relative; width:100%; }
    .editable-select input { padding-right:34px; }
    .discipline-picker { position:absolute; top:1px; right:1px; width:31px; min-width:31px; height:36px; min-height:36px; padding:0; color:#17212b; border:0; border-left:1px solid #b9c6d0; border-radius:0 6px 6px 0; background:#f8fafb; cursor:pointer; font-size:0; }
    .discipline-picker option { color:#17212b; background:white; font-size:13px; }
    .draft-button { width:100%; margin-top:5px; padding:6px 4px; color:#725300; border:1px solid #d8bd58; border-radius:6px; background:#fff8d5; cursor:pointer; font-size:12px; font-weight:700; }
    .draft-button:hover { color:white; background:#8b6c00; }
    .draft-button:disabled { opacity:.55; cursor:wait; }
    .draft-actions { display:flex; gap:5px; }
    .draft-actions .draft-button { flex:1; width:auto; }
    .draft-ai-button { color:#174d7a; border-color:#9eb5c7; background:#f4f9fc; }
    .draft-ai-button:hover { background:var(--blue); }
    .draft-note { display:block; margin-top:4px; color:var(--muted); font-size:11px; white-space:normal; }
    .save-button { width:100%; padding:9px 4px; color:white; border:0; border-radius:7px; background:var(--blue); cursor:pointer; font-weight:700; }
    .save-button:disabled { opacity:.55; cursor:wait; }
    .save-note { display:block; margin-top:5px; color:var(--muted); font-size:11px; white-space:normal; }
    .delete-button { width:100%; margin-top:8px; padding:6px 4px; color:var(--bad); border:1px solid #dfadad; border-radius:6px; background:#fff5f5; cursor:pointer; font-size:12px; font-weight:700; }
    .delete-button:hover { color:white; background:var(--bad); }
    .delete-button:disabled { opacity:.55; cursor:wait; }
    .empty { padding:40px; color:var(--muted); text-align:center; }
    .ai-controls { display:flex; align-items:center; gap:7px; padding:4px 7px; border:1px solid var(--line); border-radius:8px; background:#f8fafb; }
    .ai-state { color:var(--muted); font-size:12px; }
    .ai-light { width:12px; height:12px; flex:0 0 12px; border-radius:50%; background:var(--bad); box-shadow:0 0 0 3px #a4333322; }
    .ai-light.starting { background:#d69418; box-shadow:0 0 0 3px #d6941822; }
    .ai-light.running { background:#20a35a; box-shadow:0 0 0 3px #20a35a2a; }
    .ai-control-button { min-height:30px; padding:4px 9px; border:0; border-radius:6px; color:white; background:var(--ok); cursor:pointer; font-size:12px; font-weight:700; }
    .ai-control-button.stop { background:var(--bad); }
    .ai-control-button:disabled { opacity:.45; cursor:not-allowed; }
    dialog { width:min(1180px,calc(100vw - 32px)); padding:0; border:0; border-radius:12px; box-shadow:0 18px 60px #07152155; }
    dialog::backdrop { background:#07152199; }
    .dialog-head { padding:17px 20px; color:white; background:var(--navy); }
    .dialog-head h2 { margin:0; font-size:19px; }
    .dialog-body { padding:18px 20px; }
    .dialog-note { margin:0 0 10px; color:var(--muted); font-size:13px; }
    .comparison-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    .comparison-panel { min-width:0; }
    .comparison-title { margin:0 0 7px; color:var(--navy); font-size:14px; }
    .comparison-content { min-height:300px; max-height:58vh; overflow:auto; padding:12px; border:1px solid #b9c7d1; border-radius:7px; background:#f8fafb; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.7; }
    .comparison-content[contenteditable="true"] { background:white; outline:2px solid #2c6c91; }
    .ai-change { padding:1px 0; background:#ffe98a; box-shadow:0 0 0 1px #f0cf46; }
    .dialog-actions { display:flex; justify-content:flex-end; gap:9px; padding:0 20px 18px; }
    .dialog-button { padding:8px 16px; border:1px solid #aab9c5; border-radius:7px; background:white; cursor:pointer; font-weight:700; }
    .dialog-button.primary { color:white; border-color:var(--ok); background:var(--ok); }
    @media (max-width:1100px) { main{padding:10px}.metrics{grid-template-columns:1fr 1fr}.table-wrap{max-height:none} table{min-width:1200px} }
    @media (max-width:800px) { .comparison-grid{grid-template-columns:1fr}.comparison-content{min-height:210px;max-height:34vh} }
    @media print { header,.metrics,.toolbar,.column-filter,.new-row,.delete-button,.content-actions{display:none}.content-editor textarea{min-height:0;padding:0;border:0;resize:none}.table-wrap{max-height:none;overflow:visible;border:0} th{position:static} body{background:white} table{font-size:9px} }
  </style>
</head>
<body>
  <header><h1>酒店需求工作联系单汇总</h1><p id="subtitle"></p></header>
  <main>
    <section class="metrics">
      <div class="metric">联系单总数<b id="total"></b></div>
      <div class="metric">资料齐全<b id="complete"></b></div>
      <div class="metric">待核对<b id="review"></b></div>
      <div id="warningMetric" class="metric warning-metric" tabindex="0" aria-describedby="warningPreview">有提示记录<b id="warnings"></b><div id="warningPreview" class="metric-tooltip" role="tooltip"></div></div>
    </section>
    <section class="toolbar">
      <input id="search" type="search" placeholder="搜索专业、编号、日期、致送单位、主题、需求内容……">
      <button id="refreshArchive" class="refresh-button" type="button" title="重新扫描实际资料目录并更新 JSON/HTML">重新扫描刷新</button>
      <button id="savePrintStatuses" class="refresh-button print-save-button" type="button" title="将本页所有打印标记保存到 JSON，并刷新 HTML">保存打印标记</button>
      <div class="ai-controls" title="绿色表示已启动，红色表示未启动，黄色表示正在处理">
        <span id="aiLight" class="ai-light" role="status" aria-label="本地 AI 未启动"></span>
        <span id="aiState" class="ai-state">本地 AI：未启动</span>
        <button id="startLocalAi" class="ai-control-button" type="button">启动本地 AI</button>
        <button id="stopLocalAi" class="ai-control-button stop" type="button" disabled>关闭本地 AI</button>
      </div>
      <span class="visible-count">当前显示 <b id="visible"></b> 条</span>
    </section>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>序号</th>
          <th><div class="column-header"><span>专业</span><select id="disciplineFilter" class="column-filter" aria-label="按专业筛选"><option value="">全部专业</option></select></div></th>
          <th>编号</th><th>目录日期</th><th>致送单位</th><th>主题</th><th>需求内容</th><th>资料文件</th>
          <th><div class="column-header"><span>需求单已经打印</span><select id="printFilter" class="column-filter" aria-label="按需求单打印标记筛选"><option value="">全部</option><option value="是">是</option><option value="否">否</option></select></div></th>
          <th><div class="column-header"><span>状态 / 核对</span><select id="statusFilter" class="column-filter" aria-label="按状态筛选"><option value="">全部状态</option><option value="complete">资料齐全</option><option value="needs_review">待核对</option><option value="incomplete">资料不完整</option></select></div></th>
        </tr></thead>
        <tbody id="body"></tbody>
      </table>
      <div id="empty" class="empty" hidden>没有符合当前条件的记录</div>
    </div>
  </main>
  <dialog id="aiDialog">
    <div class="dialog-head"><h2>AI 公文修订对照</h2></div>
    <div class="dialog-body">
      <p id="aiDialogNote" class="dialog-note"></p>
      <div class="comparison-grid">
        <section class="comparison-panel">
          <h3 class="comparison-title">原文</h3>
          <div id="aiOriginalContent" class="comparison-content" role="textbox" aria-readonly="true" aria-label="原始需求内容"></div>
        </section>
        <section class="comparison-panel">
          <h3 class="comparison-title">AI 公文修订稿</h3>
          <div id="aiRevisedContent" class="comparison-content" role="textbox" aria-multiline="true" aria-label="AI 修订后的需求内容" contenteditable="false" spellcheck="true"></div>
        </section>
      </div>
    </div>
    <div class="dialog-actions">
      <button id="aiCancel" class="dialog-button" type="button">取消</button>
      <button id="aiManualEdit" class="dialog-button" type="button">手动修改</button>
      <button id="aiAccept" class="dialog-button primary" type="button">接受</button>
    </div>
  </dialog>
  <script id="summaryData" type="application/json">__SUMMARY_DATA__</script>
  <script>
    const data=JSON.parse(document.getElementById('summaryData').textContent);
    const $=id=>document.getElementById(id);
    const esc=value=>String(value??'');
    const localHosts=['127.0.0.1','localhost','::1'];
    const isLocalService=()=>['http:','https:'].includes(location.protocol)&&localHosts.includes(location.hostname);
    const errorMessage=error=>error instanceof TypeError&&error.message==='Failed to fetch'?'本地服务未运行，请重新启动 serve_summary.py 并刷新页面':error.message;
    $('subtitle').textContent=`数据版本 ${data.dataset_revision} · 生成时间 ${data.generated_at}`;
    $('total').textContent=data.record_count;
    $('complete').textContent=data.status_counts.complete||0;
    $('review').textContent=data.status_counts.needs_review||0;
    $('warnings').textContent=data.warning_count;
    data.disciplines.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;$('disciplineFilter').append(option)});
    function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=esc(text);if(className)el.className=className;return el}
    function buildWarningPreview(){
      const preview=$('warningPreview'),warningRows=data.rows.filter(row=>row.warnings.length);preview.replaceChildren();if(!warningRows.length){preview.append(node('div','当前没有提示记录'));return}warningRows.forEach(row=>{const item=node('div',undefined,'warning-preview-item');item.append(node('strong',`${row.discipline}-${row.sequence_no} · ${row.folder_date}`,'warning-preview-code'),node('span',row.subject||'（无主题）','warning-preview-subject'),node('span',row.warnings.join('；'),'warning-preview-message'));preview.append(item)});
    }
    buildWarningPreview();
    function renderComparison(element,segments,fallback){
      element.replaceChildren();const parts=Array.isArray(segments)&&segments.length?segments:[{text:fallback,changed:false}];parts.forEach(part=>element.append(node('span',part.text,part.changed?'ai-change':undefined)));
    }
    let aiAvailable=false,activeProofread=null,aiStartupTimer=null,aiStartupStartedAt=0;
    function stopAiStartupTimer(){
      if(aiStartupTimer!==null){clearInterval(aiStartupTimer);aiStartupTimer=null}
      aiStartupStartedAt=0;$('startLocalAi').textContent='启动本地 AI';
    }
    function startAiStartupTimer(){
      stopAiStartupTimer();aiStartupStartedAt=Date.now();
      const update=()=>{const seconds=Math.floor((Date.now()-aiStartupStartedAt)/1000);$('aiState').textContent=`本地 AI：正在启动并加载模型… 已等待 ${seconds} 秒`;$('startLocalAi').textContent=`启动中 ${seconds} 秒`};
      update();aiStartupTimer=setInterval(update,1000);
    }
    function applyAiStatus(result){
      stopAiStartupTimer();aiAvailable=Boolean(result.available);$('aiState').textContent=result.message;$('aiState').title=`系统：${result.system} · 模型：${result.model}`;$('aiLight').className=`ai-light${aiAvailable?' running':''}`;$('aiLight').setAttribute('aria-label',aiAvailable?'本地 AI 已启动':'本地 AI 未启动');$('startLocalAi').disabled=aiAvailable;$('stopLocalAi').disabled=!aiAvailable||!result.managed;$('stopLocalAi').title=aiAvailable&&!result.managed?'外部启动的服务不能由本项目关闭':'';document.querySelectorAll('.ai-button').forEach(button=>{button.disabled=!aiAvailable});
    }
    async function checkLocalAi(){
      if(!isLocalService()){$('aiState').textContent='本地 AI：请通过 serve_summary.py 打开';aiAvailable=false;return}
      try{
        const response=await fetch('/api/local-ai-status');const result=await response.json();
        applyAiStatus(result);
      }catch(error){applyAiStatus({available:false,managed:false,system:'Windows',model:'—',message:`本地 AI：${errorMessage(error)}`})}
    }
    async function controlLocalAi(action){
      if(!isLocalService()){alert('本地 AI 控制需要通过 serve_summary.py 打开本页面。');return}
      $('aiLight').className='ai-light starting';$('aiLight').setAttribute('aria-label',action==='start'?'本地 AI 正在启动':'本地 AI 正在关闭');if(action==='start'){startAiStartupTimer()}else{stopAiStartupTimer();$('aiState').textContent='本地 AI：正在关闭…'}$('startLocalAi').disabled=true;$('stopLocalAi').disabled=true;document.querySelectorAll('.ai-button').forEach(button=>{button.disabled=true});
      try{
        const response=await fetch(`/api/${action}-local-ai`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const result=await response.json();if(!response.ok)throw new Error(result.error||'本地 AI 操作失败');applyAiStatus(result);
      }catch(error){alert(`本地 AI 操作失败：${errorMessage(error)}`);await checkLocalAi()}
      finally{if(action==='start')stopAiStartupTimer()}
    }
    async function proofreadContent(row,editor,button,onAccept){
      if(!isLocalService()){alert('AI 勘误需要通过 serve_summary.py 打开本页面。');return}
      const content=editor.value.trim();if(!content){alert('需求内容不能为空');return}
      button.disabled=true;button.textContent='AI 勘误中…';
      try{
        const response=await fetch('/api/proofread-content',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requirement_content:content})});
        const result=await response.json();if(!response.ok)throw new Error(result.error||'AI 勘误失败');
        activeProofread={row,editor,onAccept};renderComparison($('aiOriginalContent'),result.original_segments,content);renderComparison($('aiRevisedContent'),result.revised_segments,result.revised_content);$('aiRevisedContent').contentEditable='false';$('aiDialogNote').textContent=`黄底为 AI 修改内容 · 模型：${result.model}。请核对事实、数字和专有名词后再接受。`;$('aiDialog').showModal();
      }catch(error){alert(`AI 勘误失败：${errorMessage(error)}`)}
      finally{button.disabled=aiAvailable===false;button.textContent='AI 公文勘误'}
    }
    async function saveRecordContent(row,editor,button){
      if(!isLocalService()){alert('更新 Word/PDF 需要通过 serve_summary.py 打开本页面。');return}
      const content=editor.value.trim();if(!content){alert('需求内容不能为空');return}
      button.disabled=true;button.textContent='正在更新 Word/PDF…';
      try{
        const response=await fetch('/api/update-record-content',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_revision:data.dataset_revision,record_id:row.record_id,requirement_content:content})});
        const result=await response.json();if(!response.ok)throw new Error(result.error||'更新失败');location.reload();
      }catch(error){alert(`更新需求内容失败：${errorMessage(error)}`);button.disabled=false;button.textContent='保存内容'}
    }
    async function openDirectory(event,row){
      if(!isLocalService())return;
      event.preventDefault();
      try{
        const response=await fetch('/api/open-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:row.folder_path})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'目录打开失败');
      }catch(error){alert(`目录打开失败：${errorMessage(error)}`)}
    }
    async function copyFile(event,file,anchor){
      if(!isLocalService())return;
      event.preventDefault();
      const original=anchor.textContent;
      try{
        const response=await fetch('/api/copy-file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:file.path})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'复制失败');
        anchor.textContent='已复制';anchor.classList.add('copied');
        setTimeout(()=>{anchor.textContent=original;anchor.classList.remove('copied')},1200);
      }catch(error){alert(`复制文件失败：${errorMessage(error)}`)}
    }
    async function refreshArchive(button){
      if(!isLocalService()){alert('重新扫描需要通过 serve_summary.py 打开本页面。');return}
      button.disabled=true;button.textContent='正在扫描…';
      try{
        const response=await fetch('/api/refresh-archive',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'刷新失败');
        location.reload();
      }catch(error){alert(`刷新失败：${errorMessage(error)}`);button.disabled=false;button.textContent='重新扫描刷新'}
    }
    async function savePrintStatuses(button){
      if(!isLocalService()){alert('保存打印标记需要通过 serve_summary.py 打开本页面。');return}
      const statuses=Object.fromEntries(data.rows.map(row=>[row.record_id,row.print_status]));
      const tableWrap=document.querySelector('.table-wrap'),tableScrollTop=tableWrap.scrollTop,pageScrollX=window.scrollX,pageScrollY=window.scrollY;
      button.disabled=true;button.textContent='正在保存…';
      try{
        const response=await fetch('/api/save-print-status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_revision:data.dataset_revision,statuses})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'保存失败');
        data.dataset_revision=Number(result.dataset_revision);$('subtitle').textContent=`数据版本 ${data.dataset_revision} · 生成时间 ${data.generated_at}`;button.disabled=false;button.textContent=result.changed?`已保存 ${result.changed} 条`:'没有变更';requestAnimationFrame(()=>{tableWrap.scrollTop=tableScrollTop;window.scrollTo(pageScrollX,pageScrollY)});setTimeout(()=>{button.textContent='保存打印标记'},1500);
      }catch(error){alert(`保存打印标记失败：${errorMessage(error)}`);button.disabled=false;button.textContent='保存打印标记'}
    }
    async function deleteRecord(row,button){
      const localHosts=['127.0.0.1','localhost','::1'];
      if(!['http:','https:'].includes(location.protocol)||!localHosts.includes(location.hostname)){alert('删除需要通过 serve_summary.py 打开本页面。');return}
      const code=`${row.discipline}-${row.sequence_no}`;
      if(!confirm(`确定删除“${code} ${row.subject}”吗？\n\n整个资料目录将移动到同级 _trash，可人工恢复。`))return;
      button.disabled=true;button.textContent='正在移入 _trash…';
      try{
        const response=await fetch('/api/delete-record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_revision:data.dataset_revision,record_id:row.record_id,folder_path:row.folder_path})});
        const result=await response.json();if(!response.ok)throw new Error(result.error||'删除失败');location.reload();
      }catch(error){alert(`删除失败：${errorMessage(error)}`);button.disabled=false;button.textContent='删除'}
    }
    function render(){
      const query=$('search').value.trim().toLowerCase(), discipline=$('disciplineFilter').value, printStatus=$('printFilter').value, status=$('statusFilter').value;
      const rows=data.rows.filter(row=>{
        const haystack=[row.discipline,row.sequence_no,row.folder_date,row.subject,row.requirement_content,row.word_date,row.word_subject,row.recipient,row.print_status,...row.warnings].join(' ').toLowerCase();
        return (!query||haystack.includes(query))&&(!discipline||row.discipline===discipline)&&(!printStatus||row.print_status===printStatus)&&(!status||row.status===status);
      });
      const body=$('body');body.replaceChildren();
      rows.forEach((row,index)=>{
        const tr=node('tr');
        [index+1,row.discipline,row.sequence_no,row.folder_date,row.recipient||'—'].forEach(value=>tr.append(node('td',value)));
        const subjectCell=node('td'),subjectLink=node('a',row.subject,'subject-link');subjectLink.href=row.folder_href;subjectLink.title='打开对应资料目录';subjectLink.addEventListener('click',event=>openDirectory(event,row));subjectCell.append(subjectLink);tr.append(subjectCell);
        const content=node('td'),contentEditor=node('div',undefined,'content-editor'),contentInput=node('textarea');contentInput.value=row.requirement_content;contentInput.setAttribute('aria-label',`${row.discipline}-${row.sequence_no} 需求内容`);contentInput.addEventListener('input',()=>{row.requirement_content=contentInput.value});
        const contentActions=node('div',undefined,'content-actions'),aiButton=node('button','AI 公文勘误','content-button ai-button'),contentSave=node('button','保存内容','content-button content-save-button');aiButton.type='button';contentSave.type='button';aiButton.disabled=aiAvailable===false;aiButton.addEventListener('click',()=>proofreadContent(row,contentInput,aiButton));contentSave.addEventListener('click',()=>saveRecordContent(row,contentInput,contentSave));contentActions.append(aiButton,contentSave);contentEditor.append(contentInput,contentActions);content.append(contentEditor);tr.append(content);
        const fileCell=node('td'),files=node('div',undefined,'files');
        row.files.forEach(file=>{const a=node('a',file.role_label,`file${file.kind_class?' '+file.kind_class:''}`);a.href=file.href;a.title=`${file.name}\n文件类型：${file.type_label}\n左键复制，可在其他位置粘贴`;a.addEventListener('click',event=>copyFile(event,file,a));files.append(a)});fileCell.append(files);tr.append(fileCell);
        const printCell=node('td'),printSelect=node('select',undefined,'print-select');
        ['否','是'].forEach(value=>{const option=node('option',value);option.value=value;printSelect.append(option)});printSelect.value=row.print_status;printSelect.setAttribute('aria-label',`${row.discipline}-${row.sequence_no} 需求单已经打印`);printSelect.addEventListener('change',()=>{row.print_status=printSelect.value});printCell.append(printSelect);tr.append(printCell);
        const state=node('td');state.append(node('span',row.status_label,`status ${row.status}`));
        const details=node('details'),summary=node('summary',`Word 信息与提示（${row.warnings.length}）`);details.append(summary);
        const info=node('div',`Word日期：${row.word_date||'—'}\nWord事由：${row.word_subject||'—'}\n致送单位：${row.recipient||'—'}`);details.append(info);
        if(row.warnings.length){const list=node('ul',undefined,'warnings');row.warnings.forEach(w=>list.append(node('li',w)));details.append(list)}
        const deleteButton=node('button','删除','delete-button');deleteButton.type='button';deleteButton.title='将整条资料目录移动到同级 _trash';deleteButton.addEventListener('click',()=>deleteRecord(row,deleteButton));
        state.append(details,deleteButton);tr.append(state);body.append(tr);
      });
      body.append(newRow||(newRow=buildNewRow()));
      $('visible').textContent=rows.length;$('empty').hidden=rows.length!==0;
    }
    let sequenceEdited=false,newRow;
    function localDate(){const now=new Date();return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`}
    function suggestedSequence(discipline){
      const values=data.rows.filter(row=>row.discipline===discipline&&/^\d+$/.test(row.sequence_no)).map(row=>Number(row.sequence_no));
      return String((values.length?Math.max(...values):0)+1).padStart(3,'0');
    }
    function field(tag,name,placeholder,type){const el=document.createElement(tag);el.name=name;el.placeholder=placeholder||'';if(type)el.type=type;return el}
    async function loadNewContentDraft(editor,note){
      if(!isLocalService()){note.textContent='临时保存需通过 serve_summary.py 使用';return}
      try{const response=await fetch('/api/new-content-draft');const result=await response.json();if(!response.ok)throw new Error(result.error||'草稿读取失败');if(result.requirement_content){editor.value=result.requirement_content;note.textContent='已恢复上次临时保存的内容'}}catch(error){note.textContent=`草稿读取失败：${errorMessage(error)}`}
    }
    async function saveNewContentDraft(editor,button,note){
      if(!isLocalService()){alert('临时保存需要通过 serve_summary.py 打开本页面。');return}
      if(editor.value.length>4000){alert('临时保存内容不能超过 4000 个字符');return}
      button.disabled=true;button.textContent='正在临时保存…';
      try{const response=await fetch('/api/save-new-content-draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requirement_content:editor.value})});const result=await response.json();if(!response.ok)throw new Error(result.error||'临时保存失败');button.textContent='已临时保存';note.textContent=`已保存 ${result.characters} 个字符，不会生成 Word/PDF`;setTimeout(()=>{button.disabled=false;button.textContent='临时保存内容'},1200)}catch(error){alert(`临时保存失败：${errorMessage(error)}`);button.disabled=false;button.textContent='临时保存内容'}
    }
    function buildNewRow(){
      const tr=node('tr',undefined,'new-row');tr.id='newRow';tr.append(node('td','新增'));
      const discipline=field('input','discipline','输入或点右侧箭头选择');discipline.autocomplete='off';const disciplinePicker=node('select',undefined,'discipline-picker');disciplinePicker.name='discipline_picker';disciplinePicker.setAttribute('aria-label','选择已有专业');const pickerPlaceholder=node('option','选择已有专业');pickerPlaceholder.value='';disciplinePicker.append(pickerPlaceholder);data.disciplines.forEach(value=>{const option=node('option',value);option.value=value;disciplinePicker.append(option)});const disciplineWrap=node('div',undefined,'editable-select');disciplineWrap.append(discipline,disciplinePicker);
      const disciplineCell=node('td');disciplineCell.append(disciplineWrap);tr.append(disciplineCell);
      const sequence=field('input','sequence_no','自动','text');sequence.inputMode='numeric';const sequenceCell=node('td');sequenceCell.append(sequence);tr.append(sequenceCell);
      const dateInput=field('input','folder_date','', 'date');dateInput.value=localDate();const dateCell=node('td');dateCell.append(dateInput);tr.append(dateCell);
      const recipient=field('textarea','recipient','致送单位');recipient.value='中国建筑第二工程局有限公司国家会议中心二期项目配套部分项目部';const recipientCell=node('td');recipientCell.append(recipient);tr.append(recipientCell);
      const subject=field('textarea','subject','主题');subject.value='关于   的事宜';const subjectCell=node('td');subjectCell.append(subject);tr.append(subjectCell);
      const content=field('textarea','requirement_content','需求内容'),draftAiButton=node('button','AI 公文勘误','draft-button draft-ai-button ai-button'),draftButton=node('button','临时保存内容','draft-button'),draftNote=node('span','AI 修订或临时保存都不会生成 Word/PDF','draft-note'),draftActions=node('div',undefined,'draft-actions');draftAiButton.type='button';draftAiButton.disabled=!aiAvailable;draftAiButton.addEventListener('click',()=>proofreadContent(null,content,draftAiButton,()=>{draftNote.textContent='AI 修订稿已回填；如需保留，请点击“临时保存内容”'}));draftButton.type='button';draftButton.title='保存到项目本地草稿，重启服务后仍可恢复';draftButton.addEventListener('click',()=>saveNewContentDraft(content,draftButton,draftNote));draftActions.append(draftAiButton,draftButton);const contentCell=node('td');contentCell.append(content,draftActions,draftNote);tr.append(contentCell);loadNewContentDraft(content,draftNote);
      const fileCell=node('td','保存后自动创建目录、DOCX 和 PDF');tr.append(fileCell);
      tr.append(node('td','否'));
      const actionCell=node('td'),button=node('button','保存','save-button'),note=node('span','编号可自动生成，也可手填','save-note');button.type='button';actionCell.append(button,note);tr.append(actionCell);
      if(data.disciplines.length){discipline.value=data.disciplines[0];sequence.value=suggestedSequence(discipline.value)}
      discipline.addEventListener('input',()=>{if(!sequenceEdited)sequence.value=suggestedSequence(discipline.value.trim())});
      disciplinePicker.addEventListener('change',()=>{if(!disciplinePicker.value)return;discipline.value=disciplinePicker.value;discipline.dispatchEvent(new Event('input',{bubbles:true}));disciplinePicker.value='';discipline.focus()});
      sequence.addEventListener('input',()=>{sequenceEdited=sequence.value.trim()!==''});
      button.addEventListener('click',async()=>{
        if(!['http:','https:'].includes(location.protocol)||!['127.0.0.1','localhost','::1'].includes(location.hostname)){alert('新增保存需要通过 serve_summary.py 打开本页面。');return}
        const payload={dataset_revision:data.dataset_revision,discipline:discipline.value,sequence_no:sequence.value,folder_date:dateInput.value,recipient:recipient.value,subject:subject.value,requirement_content:content.value};
        button.disabled=true;button.textContent='Word 正在导出…';note.textContent='请勿关闭 Microsoft Word';
        try{
          const response=await fetch('/api/create-record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await response.json();
          if(!response.ok)throw new Error(result.error||'保存失败');location.reload();
        }catch(error){alert(`保存失败：${errorMessage(error)}`);button.disabled=false;button.textContent='保存';note.textContent='编号可自动生成，也可手填'}
      });
      return tr;
    }
    $('refreshArchive').addEventListener('click',event=>refreshArchive(event.currentTarget));
    $('savePrintStatuses').addEventListener('click',event=>savePrintStatuses(event.currentTarget));
    $('startLocalAi').addEventListener('click',()=>controlLocalAi('start'));
    $('stopLocalAi').addEventListener('click',()=>controlLocalAi('stop'));
    $('aiCancel').addEventListener('click',()=>{$('aiDialog').close();activeProofread=null});
    $('aiManualEdit').addEventListener('click',()=>{const revised=$('aiRevisedContent');revised.textContent=revised.textContent;revised.contentEditable='true';revised.focus();$('aiDialogNote').textContent='已进入手动修改模式；黄底对比标记已清除，修改完成后点击“接受”。'});
    $('aiAccept').addEventListener('click',()=>{const revised=$('aiRevisedContent').textContent.trim();if(!activeProofread||!revised){alert('修订内容不能为空');return}if(revised.length>4000){alert('修订内容不能超过 4000 个字符');return}if(activeProofread.row)activeProofread.row.requirement_content=revised;activeProofread.editor.value=revised;if(activeProofread.onAccept)activeProofread.onAccept(revised);$('aiDialog').close();activeProofread=null});
    function scrollToNewEntry(){
      const tableWrap=document.querySelector('.table-wrap'),entry=$('newRow');
      if(!tableWrap||!entry)return;
      tableWrap.scrollTop=tableWrap.scrollHeight;
      entry.scrollIntoView({block:'end',inline:'nearest'});
      tableWrap.scrollTop=tableWrap.scrollHeight;
    }
    function scheduleInitialScroll(){[0,120,400].forEach(delay=>setTimeout(()=>requestAnimationFrame(scrollToNewEntry),delay))}
    if('scrollRestoration' in history)history.scrollRestoration='manual';
    ['search','disciplineFilter','printFilter','statusFilter'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',render));render();scheduleInitialScroll();window.addEventListener('load',scheduleInitialScroll,{once:true});window.addEventListener('pageshow',scheduleInitialScroll,{once:true});checkLocalAi();
  </script>
</body>
</html>
'''
