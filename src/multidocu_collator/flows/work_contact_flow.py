"""生成主体工作联系单的独立 JSON 和 HTML 管理页面。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..modules.file_utils import atomic_replace_text
from ..modules.summary_html import _json_for_script
from ..modules.work_contact import TEMPLATE_NAME, TEMPLATE_NAMES, WRITING_SKILL_NAME, scan_work_contacts


JSON_NAME = "主体工作联系单数据.json"
HTML_NAME = "主体工作联系单汇总.html"


def build_work_contact_archive(root: Path) -> dict[str, Any]:
    root = root.resolve()
    records, unmatched = scan_work_contacts(root)
    json_path = root / JSON_NAME
    previous = json.loads(json_path.read_text(encoding="utf-8")) if json_path.is_file() else {}
    categories = {str(record["discipline"]) for record in records if record.get("discipline")} or {"主体"}
    generic_template_available = (root / TEMPLATE_NAME).is_file()
    template_categories = sorted(
        category for category in categories
        if (root / TEMPLATE_NAMES.get(category, TEMPLATE_NAME)).is_file()
        or generic_template_available
    )
    template_available = bool(template_categories)
    writing_skill_available = (root / WRITING_SKILL_NAME).is_file()
    changed = (
        records != previous.get("records")
        or unmatched != previous.get("unmatched_files")
        or template_available != previous.get("template_available")
        or template_categories != previous.get("template_categories")
        or generic_template_available != previous.get("generic_template_available")
        or writing_skill_available != previous.get("writing_skill_available")
    )
    revision = int(previous.get("dataset_revision") or 0) + int(changed)
    data = {
        "schema_version": 1,
        "dataset_revision": revision,
        "data_root": str(root),
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "records": records,
        "unmatched_files": unmatched,
        "template_available": template_available,
        "template_categories": template_categories,
        "generic_template_available": generic_template_available,
        "writing_skill_available": writing_skill_available,
    }
    atomic_replace_text(json_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    html_path = root / HTML_NAME
    atomic_replace_text(html_path, HTML.replace("__DATA__", _json_for_script(data)))
    return {
        "changed": changed,
        "records": len(records),
        "unmatched_files": len(unmatched),
        "json_path": str(json_path),
        "html_path": str(html_path),
    }


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>主体工作联系单汇总</title>
  <style>
    :root{--navy:#17324d;--blue:#245b8f;--line:#d9e1e8;--bg:#f3f6f8;--muted:#667583;--bad:#a43333}[hidden]{display:none!important}
    *{box-sizing:border-box}body{margin:0;color:#17212b;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
    header{padding:24px 28px 18px;color:white;background:linear-gradient(120deg,var(--navy),var(--blue))}h1{margin:0 0 8px;font-size:26px}header p{margin:0;opacity:.86}
    main{padding:18px 22px 28px}.metrics{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:14px}.metric{min-width:140px;padding:13px 16px;border:1px solid var(--line);border-radius:10px;background:white}.metric b{display:block;margin-top:3px;color:var(--navy);font-size:22px}
    .toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:10px 10px 0 0;background:white}input,select,textarea,button{font:inherit}input,select,textarea{min-height:38px;padding:7px 10px;border:1px solid #b9c6d0;border-radius:7px;background:white}input[type=search]{flex:1;min-width:250px}button{min-height:32px;padding:5px 10px;border:0;border-radius:6px;color:white;background:var(--blue);cursor:pointer;font-weight:700}button:disabled{opacity:.55;cursor:not-allowed}.count{margin-left:auto;color:var(--muted)}
    .table-wrap{max-height:calc(100vh - 300px);overflow:auto;border:1px solid var(--line);border-top:0;background:white}table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;font-size:13px}th{position:sticky;top:0;z-index:2;padding:9px 7px;color:white;background:var(--navy);text-align:left}td{padding:8px 7px;border-bottom:1px solid #e5eaee;vertical-align:top;overflow-wrap:anywhere}tbody tr:hover{background:#f7fbff}th:nth-child(1){width:4%}th:nth-child(2){width:7%}th:nth-child(3){width:7%}th:nth-child(4){width:8%}th:nth-child(5){width:11%}th:nth-child(6){width:17%}th:nth-child(7){width:23%}th:nth-child(8){width:11%}th:nth-child(9){width:12%}
    .content{max-height:9em;overflow:auto;white-space:pre-line;line-height:1.5}.content-editor{width:100%;min-height:125px;resize:vertical;line-height:1.5}.content-actions,.files,.actions{display:flex;flex-wrap:wrap;gap:5px}.content-actions{margin-top:6px}.content-actions button{font-size:12px}.file{display:inline-block;max-width:100%;padding:4px 6px;border:1px solid #bed3e4;border-radius:5px;background:#f3f9fd;color:#174d7a;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file:hover{background:var(--blue);color:white}.file.copied{border-color:#8fc5a5;background:#e9f7ee;color:#26734d}.subject{color:#174d7a;font-weight:600}.subject-button{padding:0;color:#174d7a;background:none;text-align:left}.subject-button:hover{text-decoration:underline}.status{font-weight:700}.complete{color:#26734d}.incomplete{color:var(--bad)}.needs_review{color:#a15c00}.warning{display:block;margin-top:4px;color:#a15c00;font-size:12px}.empty{padding:40px;text-align:center;color:var(--muted)}.delete{background:var(--bad)}
    .new-row{position:sticky;bottom:0;z-index:1;background:#eef6fc}.new-row td{padding:8px 7px}.new-row button{font-size:12px}.note{display:block;margin-top:5px;color:var(--muted);font-size:11px;white-space:normal}
    dialog{width:min(760px,calc(100vw - 32px));padding:0;border:0;border-radius:12px;box-shadow:0 18px 60px #07152155}#editDialog,#draftDialog,#splitDialog{max-height:calc(100vh - 32px);overflow-y:auto}dialog::backdrop{background:#07152199}.dialog-head{padding:17px 20px;color:white;background:var(--navy)}.dialog-head h2{margin:0;font-size:19px}.dialog-body{padding:18px 20px}.dialog-body label{display:block;margin-bottom:12px;color:var(--navy);font-weight:700}.dialog-body input,.dialog-body textarea{display:block;width:100%;margin-top:5px;font-weight:400}.dialog-body textarea{min-height:220px;resize:vertical;line-height:1.6}.dialog-actions{display:flex;justify-content:flex-end;gap:8px;padding:0 20px 18px}.secondary{color:var(--navy);border:1px solid var(--line);background:white}
    #newContactDialog{width:min(1520px,calc(100vw - 32px));max-height:calc(100vh - 24px);overflow:hidden}#newContactDialog[open]{display:flex;flex-direction:column}#newContactDialog .dialog-head,#newContactDialog .dialog-actions{flex:none}#newContactDialog .dialog-actions{padding:8px 20px 14px}#newContactFields{min-height:0;overflow-y:auto;padding:12px 20px}#newContactFields label{margin:0}#newContactFields .new-meta-grid{display:grid;grid-template-columns:1fr 1.2fr 1fr 1.3fr;gap:10px 16px}#newContactFields .new-subject{grid-column:1/-1}#newContactFields .new-body-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px;margin-top:12px}#newContactFields .new-field-group{min-width:0}#newContactFields .new-attachment{grid-column:1/-1}#newContactFields textarea{min-height:120px;height:clamp(150px,20vh,240px)}#newContactFields .new-attachment textarea{height:clamp(120px,13vh,180px)}#newContactFields .ai-button{margin:6px 8px 0 0}#newContactFields .ai-note{margin-top:8px}
    .ai-controls{display:flex;align-items:center;gap:7px;padding:4px 7px;border:1px solid var(--line);border-radius:8px;background:#f8fafb}.ai-state{color:var(--muted);font-size:12px}.ai-light{width:12px;height:12px;flex:0 0 12px;border-radius:50%;background:var(--bad)}.ai-light.checking{background:#d69418}.ai-light.running{background:#20a35a}.ai-button{margin-top:7px;font-size:12px}.ai-note{display:block;margin-top:5px;color:var(--muted);font-size:12px}
    .field-caption{display:block;margin:5px 0 3px;color:var(--navy);font-size:12px;font-weight:700}.number-input{margin-top:5px}.number-hint{display:block;margin-top:4px;color:var(--muted);font-size:11px}.subject-detail{max-height:55vh;overflow:auto;padding:13px;border:1px solid var(--line);border-radius:7px;background:#f8fafb;white-space:pre-wrap;line-height:1.7}.new-row .facts-input{min-height:95px}.new-row .generated-content{min-height:110px}.draft-generate{background:#26734d}.draft-warning{color:#a15c00;white-space:pre-wrap;line-height:1.5}
    #aiDialog{width:min(1180px,calc(100vw - 32px))}.dialog-note{margin:0 0 12px;color:var(--muted);font-size:13px}.comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.comparison-panel{min-width:0}.comparison-panel h3{margin:0 0 7px;color:var(--navy);font-size:14px}.comparison-content{min-height:300px;max-height:58vh;overflow:auto;padding:12px;border:1px solid #b9c7d1;border-radius:7px;background:#f8fafb;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}.comparison-content[contenteditable="true"]{background:white;outline:2px solid var(--blue)}.ai-change{background:#ffe98a;box-shadow:0 0 0 1px #f0cf46}
    @media(max-width:1100px){main{padding:10px}.table-wrap{max-height:none}table{min-width:1260px}}@media(max-width:800px){.comparison-grid{grid-template-columns:1fr}.comparison-content{min-height:210px;max-height:34vh}#newContactFields .new-meta-grid{grid-template-columns:1fr 1fr}#newContactFields .new-body-grid{grid-template-columns:1fr}#newContactFields .new-attachment{grid-column:auto}}@media(max-width:520px){#newContactFields .new-meta-grid{grid-template-columns:1fr}}@media print{.toolbar,.new-row,.actions,.ai-button{display:none}.table-wrap{max-height:none;overflow:visible}}
  </style>
</head>
<body>
  <header><h1>主体工作联系单汇总</h1><p>现有资料的目录编号仅作临时索引，原 Word 的未编号内容保持原样；修改与删除保留可恢复的旧版。</p></header>
  <main>
    <section class="metrics"><div class="metric">联系单总数<b id="total"></b></div><div class="metric">资料齐全<b id="complete"></b></div><div class="metric">有提示记录<b id="warnings"></b></div><div class="metric">未匹配文件<b id="unmatchedCount"></b></div></section>
    <section class="toolbar"><input id="search" type="search" placeholder="搜索类别、编号、日期、致送单位、主题、正文……" aria-label="搜索联系单"><select id="statusFilter" aria-label="按状态筛选"><option value="">全部状态</option><option value="complete">资料齐全</option><option value="incomplete">资料不完整</option><option value="needs_review">待核对</option></select><button id="refresh" type="button">重新扫描刷新</button><div class="ai-controls"><span id="aiLight" class="ai-light" role="status" aria-label="本地 AI 等待检查"></span><span id="aiState" class="ai-state">本地 AI：等待检查</span><button id="checkLocalAi" type="button">检查本地 AI</button></div><span class="count">当前显示 <b id="visible"></b> 条</span></section>
    <div class="table-wrap"><table><thead><tr><th>序号</th><th>类别</th><th>编号</th><th>日期</th><th>致送单位</th><th>主题</th><th>内容</th><th>资料文件</th><th>状态 / 操作</th></tr></thead><tbody id="body"></tbody></table><div id="empty" class="empty" hidden>没有符合当前条件的记录</div></div>
    <details id="unmatchedDetails"><summary>查看未匹配文件</summary><ul id="unmatchedList"></ul></details>
  </main>
  <dialog id="subjectDialog"><div class="dialog-head"><h2 id="subjectTitle"></h2></div><div class="dialog-body"><p id="subjectMeta" class="dialog-note"></p><div id="subjectContent" class="subject-detail"></div><h3 id="subjectAttachmentTitle" hidden>附件：具体问题及整改要求</h3><div id="subjectAttachment" class="subject-detail" hidden></div><p id="subjectUnavailable" class="dialog-note" hidden>该条目尚未整理成独立资料目录。</p></div><div class="dialog-actions"><button id="subjectClose" class="secondary" type="button">关闭</button><button id="subjectOpen" class="secondary" type="button">打开资料文件夹</button><button id="subjectEdit" type="button">修改主题和内容</button></div></dialog>
  <dialog id="editDialog"><div class="dialog-head"><h2 id="editTitle">修改主体工作联系单</h2></div><form id="editForm"><div class="dialog-body"><label>编号方式<select id="editNumberMode"><option value="keep">保持当前</option><option value="auto">自动编号</option><option value="temporary">临时编号（Word 仅保留类别-）</option><option value="manual">手动输入</option></select><input id="editManualNumber" class="number-input" maxlength="40" placeholder="如 023 或 类别-023" hidden><span id="editNumberHint" class="number-hint"></span></label><label>日期<input id="editDate" type="date" required></label><label>致送单位<input id="editRecipient" maxlength="100" required></label><label>主题<input id="editSubject" maxlength="120" required></label><label>正文概述与整改要求<textarea id="editContent" maxlength="10000" required></textarea></label><button id="editAi" class="ai-button" type="button" disabled>AI 公文勘误</button><button id="editSplit" class="ai-button split-generate" type="button" disabled>AI 拆分正文与附件</button><label>附件：具体问题及整改要求（可选）<textarea id="editAttachment" maxlength="20000"></textarea></label><button id="editAttachmentAi" class="ai-button" type="button" disabled>AI 勘误附件</button><span class="ai-note">接受修订稿后仍需点击“保存修改”，才会更新 Word 和 PDF。</span></div><div class="dialog-actions"><button id="editCancel" class="secondary" type="button">取消</button><button id="editSave" type="submit">保存修改</button></div></form></dialog>
  <dialog id="aiDialog"><div class="dialog-head"><h2>AI 公文修订对照</h2></div><div class="dialog-body"><p id="aiDialogNote" class="dialog-note"></p><div class="comparison-grid"><section class="comparison-panel"><h3>原文</h3><div id="aiOriginalContent" class="comparison-content" aria-label="原始工作联系单正文"></div></section><section class="comparison-panel"><h3>AI 公文修订稿</h3><div id="aiRevisedContent" class="comparison-content" aria-label="AI 修订后的工作联系单正文" contenteditable="false" spellcheck="true"></div></section></div></div><div class="dialog-actions"><button id="aiCancel" class="secondary" type="button">取消</button><button id="aiManualEdit" class="secondary" type="button">手动修改</button><button id="aiAccept" type="button">接受</button></div></dialog>
  <dialog id="draftDialog"><div class="dialog-head"><h2>按写作规则生成工作联系单</h2></div><div class="dialog-body"><p id="draftSource" class="dialog-note"></p><p id="draftMissing" class="draft-warning" hidden></p><label>致送单位<input id="draftRecipient" maxlength="100"></label><label>事由<input id="draftSubject" maxlength="120" required></label><label>正文概述与整改要求<textarea id="draftContent" maxlength="10000" required></textarea></label><label>附件：具体问题及整改要求<textarea id="draftAttachment" maxlength="20000"></textarea></label><span class="ai-note">请核对事实、时限及责任依据；回填后仍需点击“新增联系单”才会生成 Word/PDF。</span></div><div class="dialog-actions"><button id="draftCancel" class="secondary" type="button">取消</button><button id="draftApply" type="button">回填新增行</button></div></dialog>
  <dialog id="splitDialog"><div class="dialog-head"><h2>AI 拆分正文与附件</h2></div><div class="dialog-body"><p id="splitSource" class="dialog-note"></p><h3>拆分前正文</h3><div id="splitOriginal" class="subject-detail"></div><label>拆分后正文概述与整改要求<textarea id="splitContent" maxlength="10000"></textarea></label><label>拆分后附件：具体问题及整改要求<textarea id="splitAttachment" maxlength="20000"></textarea></label><span class="ai-note">请逐项核对原文事实；回填仅修改页面输入框，点击“保存修改”或“新增联系单”后才生成 Word/PDF。</span></div><div class="dialog-actions"><button id="splitCancel" class="secondary" type="button">取消</button><button id="splitApply" type="button">接受并回填</button></div></dialog>
  <dialog id="newContactDialog"><div class="dialog-head"><h2>新增主体工作联系单</h2></div><div id="newContactFields" class="dialog-body"></div><div class="dialog-actions"><button id="newContactCancel" class="secondary" type="button">取消</button><button id="newContactSave" type="button">新增联系单</button></div></dialog>
  <script type="application/json" id="summaryData">__DATA__</script>
  <script>
    const data=JSON.parse(document.getElementById('summaryData').textContent),$=id=>document.getElementById(id);
    const service=['http:','https:'].includes(location.protocol),rows=data.records||[];
    const fileHref=path=>(service?'/work-contact/':'./')+path.split('/').map(encodeURIComponent).join('/');
    function localDate(){const now=new Date();return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`}
    function cell(value){const td=document.createElement('td');td.textContent=value??'';return td}
    function numberLabel(row){return (row.sequence_no||row.document_code||'—')+(row.temporary_number?'（临时编号）':'')}
    function codeLabel(row){return (row.document_code||'—')+(row.temporary_number?'（临时编号）':'')}
    function nextCode(category,excludedId){const values=rows.filter(row=>row.discipline===category&&row.record_id!==excludedId).map(row=>Number(row.sequence_no)||0);return `${category}-${String(Math.max(0,...values)+1).padStart(3,'0')}`}
    function button(label,action,className){const element=document.createElement('button');element.type='button';element.textContent=label;if(className)element.className=className;element.addEventListener('click',action);return element}
    async function post(route,payload){if(!service)throw new Error('请通过 serve_summary.py 或 EXE 打开页面');const response=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error||'操作失败');return result}
    let aiAvailable=false,aiTarget=null,activeDraftFields=null,activeSplitFields=null;
    function applyAiStatus(result){aiAvailable=Boolean(result.available);$('aiState').textContent=result.message||'本地 AI 不可用';$('aiLight').className='ai-light'+(aiAvailable?' running':'');$('aiLight').setAttribute('aria-label',aiAvailable?'本地 AI API 可用':'本地 AI API 不可用');document.querySelectorAll('.ai-button').forEach(control=>{control.disabled=!aiAvailable||((control.classList.contains('draft-generate')||control.classList.contains('split-generate'))&&!data.writing_skill_available)})}
    async function checkLocalAi(){const control=$('checkLocalAi');if(!service){applyAiStatus({available:false,message:'本地 AI：请通过服务打开页面'});return}control.disabled=true;control.textContent='正在检查…';$('aiLight').className='ai-light checking';$('aiState').textContent='本地 AI：正在检查…';try{const response=await fetch('/api/local-ai-status');const result=await response.json();if(!response.ok)throw new Error(result.error||'检查失败');applyAiStatus(result)}catch(error){applyAiStatus({available:false,message:`本地 AI：${error.message}`})}finally{control.disabled=false;control.textContent='检查本地 AI'}}
    function renderComparison(element,segments,fallback){element.replaceChildren();const parts=Array.isArray(segments)&&segments.length?segments:[{text:fallback,changed:false}];parts.forEach(part=>{const span=document.createElement('span');span.textContent=part.text;if(part.changed)span.className='ai-change';element.append(span)})}
    async function proofread(editor,control){const content=editor.value.trim();if(!content){alert('工作联系单正文不能为空');return}if(content.length>4000){alert('AI 勘误内容不能超过 4000 个字符');return}control.disabled=true;control.textContent='AI 勘误中…';try{const result=await post('/api/proofread-work-contact',{content});aiTarget=editor;renderComparison($('aiOriginalContent'),result.original_segments,content);renderComparison($('aiRevisedContent'),result.revised_segments,result.revised_content);$('aiRevisedContent').contentEditable='false';$('aiDialogNote').textContent=`黄底为 AI 修改内容 · 模型：${result.model}。请核对事实、数字和专有名词后再接受。`;$('aiDialog').showModal()}catch(error){alert(`AI 勘误失败：${error.message}`)}finally{control.disabled=!aiAvailable;control.textContent='AI 公文勘误'}}
    async function generateDraft(fields,control){const facts=fields.facts.value.trim();if(!facts){alert('请先输入具体事项');fields.facts.focus();return}if(!fields.date.value){alert('请先选择日期');return}control.disabled=true;control.textContent='正在生成草稿…';try{const result=await post('/api/generate-work-contact',{facts,discipline:fields.category.value,folder_date:fields.date.value,recipient:fields.recipient.value,subject:fields.subject.value});if(!fields.facts.isConnected)throw new Error('新增行已经刷新，请重新填写具体事项');activeDraftFields=fields;$('draftRecipient').value=result.recipient||'';$('draftSubject').value=result.subject||'';$('draftContent').value=result.content||'';$('draftAttachment').value=result.attachment_content||'';$('draftSource').textContent=`写作规则：${result.skill_file} · 本地模型：${result.model}`;const missing=result.missing_information||[];$('draftMissing').hidden=!missing.length;$('draftMissing').textContent=missing.length?`请补充或核对：${missing.join('；')}`:'';$('draftDialog').showModal()}catch(error){alert(`生成失败：${error.message}`)}finally{control.disabled=!aiAvailable||!data.writing_skill_available;control.textContent='按写作规则生成草稿'}}
    async function splitContent(fields,control){const content=fields.content.value.trim();if(!content){alert('请先填写需要拆分的正文');fields.content.focus();return}const label=control.textContent;control.disabled=true;control.textContent='AI 正在拆分…';try{const result=await post('/api/split-work-contact',{content,attachment_content:fields.attachment.value,subject:fields.subject.value});if(!fields.content.isConnected)throw new Error('编辑区域已刷新，请重新打开');activeSplitFields=fields;$('splitOriginal').textContent=content;$('splitContent').value=result.content;$('splitAttachment').value=result.attachment_content;$('splitSource').textContent=`写作规则：${result.skill_file} · 本地模型：${result.model}。现有附件内容已保留在下方。`;$('splitDialog').showModal()}catch(error){alert(`AI 拆分失败：${error.message}`)}finally{control.disabled=!aiAvailable||!data.writing_skill_available;control.textContent=label}}
    async function openFolder(row){if(!row.folder_path)return;if(!service){location.href='./'+row.folder_path.split('/').map(encodeURIComponent).join('/')+'/';return}try{await post('/api/open-work-contact-path',{path:row.folder_path})}catch(error){alert(error.message)}}
    async function copyContactFile(file,control){if(!service){alert('复制文件需要通过 serve_summary.py 或 EXE 打开本页面');return}const label=control.textContent;control.disabled=true;try{await post('/api/copy-work-contact-file',{path:file.path});control.textContent='已复制';control.classList.add('copied');setTimeout(()=>{control.textContent=label;control.classList.remove('copied');control.disabled=false},1200)}catch(error){control.disabled=false;alert(`复制文件失败：${error.message}`)}}
    $('total').textContent=rows.length;$('complete').textContent=rows.filter(row=>row.status==='complete').length;$('warnings').textContent=rows.filter(row=>row.warnings.length).length;$('unmatchedCount').textContent=(data.unmatched_files||[]).length;
    $('unmatchedDetails').hidden=!(data.unmatched_files||[]).length;(data.unmatched_files||[]).forEach(path=>{const item=document.createElement('li');item.textContent=path;$('unmatchedList').append(item)});
    let activeRecord=null,activeSubjectRecord=null;
    function showSubject(row){activeSubjectRecord=row;$('subjectTitle').textContent=row.subject||'未命名主题';$('subjectMeta').textContent=`${row.discipline||'—'} · ${codeLabel(row)} · ${row.folder_date||'—'} · 致送：${row['致送单位']||'—'}`;$('subjectContent').textContent=row['内容']||'暂无正文';$('subjectAttachment').textContent=row['附件内容']||'';$('subjectAttachment').hidden=$('subjectAttachmentTitle').hidden=!row['附件内容'];$('subjectOpen').disabled=!row.folder_path;$('subjectEdit').disabled=!row.folder_path;$('subjectUnavailable').hidden=Boolean(row.folder_path);$('subjectDialog').showModal()}
    function updateEditNumber(){if(!activeRecord)return;const mode=$('editNumberMode').value,manual=$('editManualNumber');manual.hidden=mode!=='manual';manual.required=mode==='manual';$('editNumberHint').textContent=mode==='keep'?`当前：${codeLabel(activeRecord)}`:mode==='manual'?'请输入本类别中未使用的数字序号':`${nextCode(activeRecord.discipline,activeRecord.record_id)}${mode==='temporary'?'（临时编号；Word 仅写'+activeRecord.discipline+'-）':''}`}
    function edit(row){activeRecord=row;$('editTitle').textContent=`修改 ${codeLabel(row)}`;$('editNumberMode').value='keep';$('editManualNumber').value=row.sequence_no||'';updateEditNumber();$('editDate').value=row.folder_date;$('editRecipient').value=row['致送单位'];$('editSubject').value=row.subject;$('editContent').value=row['内容'];$('editAttachment').value=row['附件内容']||'';$('editDialog').showModal()}
    async function remove(row){if(!confirm(`确认把“${codeLabel(row)} ${row.subject}”移入 _trash？`))return;try{await post('/api/delete-work-contact',{dataset_revision:data.dataset_revision,record_id:row.record_id,folder_path:row.folder_path});location.reload()}catch(error){alert(`删除失败：${error.message}`)}}
    function renderContentCell(row,contentCell){
      contentCell.replaceChildren();
      if(!row._contentEditing){const view=document.createElement('div');view.className='content';view.textContent=row['内容']||'';contentCell.append(view);if(row['附件内容']){const detail=document.createElement('div');detail.className='note';detail.textContent='附有具体问题清单';contentCell.append(detail)}if(row.folder_path){const actions=document.createElement('div');actions.className='content-actions';actions.append(button('修改',()=>{row._contentEditing=true;row._contentDraft=row['内容']||'';renderContentCell(row,contentCell);contentCell.querySelector('textarea')?.focus()},'secondary'));contentCell.append(actions)}return}
      const editor=document.createElement('textarea');editor.className='content-editor';editor.maxLength=10000;editor.value=row._contentDraft??row['内容']??'';editor.setAttribute('aria-label',`${codeLabel(row)} 联系单正文`);editor.addEventListener('input',()=>{row._contentDraft=editor.value});
      const actions=document.createElement('div');actions.className='content-actions';
      const save=button('保存内容',async()=>{const content=editor.value.trim();if(!content){alert('联系单正文不能为空');editor.focus();return}save.disabled=true;save.textContent='正在更新 Word/PDF…';try{await post('/api/update-work-contact',{dataset_revision:data.dataset_revision,record_id:row.record_id,number_mode:'keep',folder_date:row.folder_date,recipient:row['致送单位'],subject:row.subject,content});location.reload()}catch(error){alert(`保存内容失败：${error.message}`);save.disabled=false;save.textContent='保存内容'}});
      actions.append(save,button('取消',()=>{row._contentEditing=false;delete row._contentDraft;renderContentCell(row,contentCell)},'secondary'));
      contentCell.append(editor,actions)
    }
    function render(){const query=$('search').value.trim().toLowerCase(),status=$('statusFilter').value;const visible=rows.filter(row=>(!status||row.status===status)&&(!query||[row.discipline,row.sequence_no,row.folder_date,row.document_code,row['致送单位'],row.subject,row['内容'],row['附件内容'],row.word_subject].join(' ').toLowerCase().includes(query)));const body=$('body'),existingNewRow=body.querySelector('.new-row');body.replaceChildren();visible.forEach((row,index)=>{const tr=document.createElement('tr'),numberCell=cell(numberLabel(row));numberCell.title=`原 Word 资料编号：${row.original_document_no||'未填写'}`;tr.append(cell(index+1),cell(row.discipline||'—'),numberCell,cell(row.folder_date),cell(row['致送单位']||'—'));const subject=cell('');subject.className='subject';subject.append(button(row.subject||'未命名主题',()=>showSubject(row),'subject-button'));tr.append(subject);const content=cell('');renderContentCell(row,content);tr.append(content);const files=cell(''),fileWrap=document.createElement('div');fileWrap.className='files';(row.files||[]).forEach(file=>{const label=({source_word:'Word',auxiliary_word:'Word副本',issued_pdf:'PDF',signed_scan:'扫描件',attachment_word:'附件Word',attachment_pdf:'附件PDF'})[file.role]||'附件';if(/\.(?:docx?|pdf)$/i.test(file.name)){const control=button(label,()=>copyContactFile(file,control),'file');control.title=`${file.name}\n点击复制文件，可直接粘贴`;control.setAttribute('aria-label',`复制文件 ${file.name}`);fileWrap.append(control)}else{const link=document.createElement('a');link.className='file';link.textContent=label;link.title=file.name;link.href=fileHref(file.path);link.target='_blank';link.rel='noopener';fileWrap.append(link)}});files.append(fileWrap);tr.append(files);const state=cell(''),statusLabel=document.createElement('div');statusLabel.className='status '+row.status;statusLabel.textContent=({complete:'资料齐全',incomplete:'资料不完整',needs_review:'待核对'})[row.status]||row.status;state.append(statusLabel);(row.warnings||[]).forEach(message=>{const note=document.createElement('span');note.className='warning';note.textContent=message;state.append(note)});if(row.folder_path){const actions=document.createElement('div');actions.className='actions';actions.append(button('修改',()=>edit(row)),button('删除',()=>remove(row),'delete'));state.append(actions)}else state.append(document.createTextNode('待整理目录'));tr.append(state);body.append(tr)});if(existingNewRow)body.append(existingNewRow);else buildNewRow(body);$('visible').textContent=visible.length;$('empty').hidden=visible.length!==0}
    function buildNewRow(body){
      const tr=document.createElement('tr');tr.className='new-row';const entry=cell('');entry.colSpan=9;entry.append(button('＋ 新增主体工作联系单',()=>$('newContactDialog').showModal()));entry.append(document.createTextNode('　点击填写正文、附件及资料信息'));tr.append(entry);body.append(tr);
      const panel=$('newContactFields');panel.replaceChildren();const meta=document.createElement('div'),bodyFields=document.createElement('div');meta.className='new-meta-grid';bodyFields.className='new-body-grid';panel.append(meta,bodyFields);
      const categories=[...new Set(rows.map(row=>row.discipline).filter(Boolean))].sort();
      const labeled=(title,control,container)=>{const label=document.createElement('label');label.textContent=title;label.append(control);container.append(label);return label};
      const category=document.createElement('input'),suggestions=document.createElement('datalist');
      category.type='text';category.maxLength=30;category.placeholder='输入类别';category.value='质保';
      suggestions.id='contactCategories';category.setAttribute('list',suggestions.id);
      categories.forEach(value=>{const option=document.createElement('option');option.value=value;suggestions.append(option)});
      labeled('类别',category,meta).append(suggestions);
      const numberMode=document.createElement('select'),manualNumber=document.createElement('input'),numberHint=document.createElement('span');
      [['auto','自动编号'],['temporary','临时编号（Word 仅保留类别-）'],['manual','手动输入']].forEach(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;numberMode.append(option)});
      numberMode.value='temporary';
      manualNumber.className='number-input';manualNumber.maxLength=40;manualNumber.placeholder='如 023';manualNumber.hidden=true;numberHint.className='number-hint';
      const updateNumber=()=>{const mode=numberMode.value;manualNumber.hidden=mode!=='manual';manualNumber.required=mode==='manual';numberHint.textContent=mode==='manual'?'输入本类别未使用的数字序号':`${nextCode(category.value.trim())}${mode==='temporary'?'（仅 HTML 标注；Word 仅写'+category.value.trim()+'-）':''}`};
      numberMode.addEventListener('change',updateNumber);const numberLabel=labeled('编号方式',numberMode,meta);numberLabel.append(manualNumber,numberHint);
      const dateInput=document.createElement('input');dateInput.type='date';dateInput.value=localDate();labeled('日期',dateInput,meta);
      const recipient=document.createElement('input');recipient.placeholder='致送单位';recipient.maxLength=100;labeled('致送单位',recipient,meta);
      const subject=document.createElement('input');subject.placeholder='主题';subject.maxLength=120;labeled('主题',subject,meta).className='new-subject';
      const facts=document.createElement('textarea'),content=document.createElement('textarea'),attachment=document.createElement('textarea');
      facts.className='facts-input';facts.maxLength=6000;facts.placeholder='输入具体事项、问题、要求及已知的时限与责任依据';
      content.className='generated-content';content.maxLength=10000;content.placeholder='概述问题和影响，提出整改、复验要求；有附件时写具体问题详见附件';attachment.maxLength=20000;attachment.placeholder='逐项写明位置或设备、问题现象、影响和整改动作（可选）';
      const factsGroup=document.createElement('div'),contentGroup=document.createElement('div'),attachmentGroup=document.createElement('div');factsGroup.className=contentGroup.className='new-field-group';attachmentGroup.className='new-field-group new-attachment';bodyFields.append(factsGroup,contentGroup,attachmentGroup);
      labeled('具体事项（供 AI 起草）',facts,factsGroup);labeled('正文概述与整改要求',content,contentGroup);labeled('附件：具体问题及整改要求（可选）',attachment,attachmentGroup);
      const fields={facts,category,date:dateInput,recipient,subject,content,attachment};
      const draftButton=button('按写作规则生成草稿',()=>generateDraft(fields,draftButton),'ai-button draft-generate');draftButton.disabled=!aiAvailable||!data.writing_skill_available;
      const splitButton=button('AI 拆分正文与附件',()=>splitContent(fields,splitButton),'ai-button split-generate');splitButton.disabled=!aiAvailable||!data.writing_skill_available;
      const aiButton=button('AI 公文勘误',()=>proofread(content,aiButton),'ai-button');aiButton.disabled=!aiAvailable;
      const attachmentAi=button('AI 勘误附件',()=>proofread(attachment,attachmentAi),'ai-button');attachmentAi.disabled=!aiAvailable;factsGroup.append(draftButton);contentGroup.append(aiButton,splitButton);attachmentGroup.append(attachmentAi);
      const save=$('newContactSave'),note=document.createElement('span');note.className='ai-note';panel.append(note);
      const updateTemplate=()=>{const ready=Boolean(category.value.trim())&&(data.generic_template_available||(data.template_categories||[]).includes(category.value.trim()));save.disabled=!ready;note.textContent=ready?'可选自动、临时编号或手动输入':'请输入类别并放入可用模板'};
      category.addEventListener('input',()=>{updateTemplate();updateNumber()});updateNumber();updateTemplate();
      save.addEventListener('click',async()=>{save.disabled=true;try{await post('/api/create-work-contact',{dataset_revision:data.dataset_revision,discipline:category.value,number_mode:numberMode.value,manual_number:manualNumber.value,folder_date:dateInput.value,recipient:recipient.value,subject:subject.value,content:content.value,attachment_content:attachment.value});location.reload()}catch(error){alert(`新增失败：${error.message}`);updateTemplate()}});
      $('newContactCancel').addEventListener('click',()=>$('newContactDialog').close())
    }
    $('checkLocalAi').addEventListener('click',checkLocalAi);
    $('subjectClose').addEventListener('click',()=>$('subjectDialog').close());
    $('subjectDialog').addEventListener('close',()=>{activeSubjectRecord=null});
    $('subjectOpen').addEventListener('click',()=>{const row=activeSubjectRecord;$('subjectDialog').close();if(row)openFolder(row)});
    $('subjectEdit').addEventListener('click',()=>{const row=activeSubjectRecord;$('subjectDialog').close();if(row)edit(row)});
    $('editAi').addEventListener('click',()=>proofread($('editContent'),$('editAi')));$('editAttachmentAi').addEventListener('click',()=>proofread($('editAttachment'),$('editAttachmentAi')));
    $('editSplit').addEventListener('click',()=>splitContent({content:$('editContent'),attachment:$('editAttachment'),subject:$('editSubject')},$('editSplit')));
    $('aiCancel').addEventListener('click',()=>{$('aiDialog').close();aiTarget=null});
    $('aiManualEdit').addEventListener('click',()=>{const revised=$('aiRevisedContent');revised.textContent=revised.textContent;revised.contentEditable='true';revised.focus();$('aiDialogNote').textContent='已进入手动修改模式；对比标记已清除。修改完成后点击“接受”。'});
    $('aiAccept').addEventListener('click',()=>{const revised=$('aiRevisedContent').textContent.trim();if(!aiTarget||!revised){alert('修订内容不能为空');return}if(revised.length>4000){alert('修订内容不能超过 4000 个字符');return}aiTarget.value=revised;$('aiDialog').close();aiTarget=null});
    $('draftCancel').addEventListener('click',()=>{$('draftDialog').close();activeDraftFields=null});
    $('draftApply').addEventListener('click',()=>{if(!activeDraftFields||!activeDraftFields.facts.isConnected){alert('新增行已刷新，请重新生成草稿');return}const recipient=$('draftRecipient').value.trim(),subject=$('draftSubject').value.trim(),content=$('draftContent').value.trim(),attachment=$('draftAttachment').value.trim();if(!recipient||!subject||!content){alert('请填写致送单位、事由和完整正文');return}activeDraftFields.recipient.value=recipient;activeDraftFields.subject.value=subject;activeDraftFields.content.value=content;activeDraftFields.attachment.value=attachment;$('draftDialog').close();activeDraftFields=null});
    $('splitCancel').addEventListener('click',()=>{$('splitDialog').close();activeSplitFields=null});
    $('splitApply').addEventListener('click',()=>{if(!activeSplitFields||!activeSplitFields.content.isConnected){alert('编辑区域已刷新，请重新拆分');return}const content=$('splitContent').value.trim(),attachment=$('splitAttachment').value.trim();if(!content||!attachment){alert('请核对并填写正文与附件');return}activeSplitFields.content.value=content;activeSplitFields.attachment.value=attachment;$('splitDialog').close();activeSplitFields=null});
    $('editNumberMode').addEventListener('change',updateEditNumber);
    $('editCancel').addEventListener('click',()=>{$('editDialog').close();activeRecord=null});$('editForm').addEventListener('submit',async event=>{event.preventDefault();if(!activeRecord)return;const save=$('editSave');save.disabled=true;try{await post('/api/update-work-contact',{dataset_revision:data.dataset_revision,record_id:activeRecord.record_id,number_mode:$('editNumberMode').value,manual_number:$('editManualNumber').value,folder_date:$('editDate').value,recipient:$('editRecipient').value,subject:$('editSubject').value,content:$('editContent').value,attachment_content:$('editAttachment').value});location.reload()}catch(error){alert(`修改失败：${error.message}`);save.disabled=false}});
    function showLatestSavedRecord(){if(!rows.length)return;const tableWrap=document.querySelector('.table-wrap');tableWrap.scrollTop=tableWrap.scrollHeight;if(window.matchMedia('(max-width:1100px)').matches)window.scrollTo(0,document.documentElement.scrollHeight)}
    $('refresh').addEventListener('click',async event=>{const control=event.currentTarget;control.disabled=true;try{await post('/api/refresh-work-contact',{});location.reload()}catch(error){alert(`刷新失败：${error.message}`);control.disabled=false}});$('search').addEventListener('input',render);$('statusFilter').addEventListener('change',render);render();checkLocalAi();
    if('scrollRestoration' in history)history.scrollRestoration='manual';
    window.addEventListener('load',()=>requestAnimationFrame(showLatestSavedRecord),{once:true});
  </script>
</body>
</html>
'''
