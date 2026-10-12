"""生成主体工作联系单的独立 JSON 和 HTML 管理页面。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..modules.file_utils import atomic_replace_text
from ..modules.summary_html import _json_for_script
from ..modules.work_contact import TEMPLATE_NAME, TEMPLATE_NAMES, scan_work_contacts


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
    changed = (
        records != previous.get("records")
        or unmatched != previous.get("unmatched_files")
        or template_available != previous.get("template_available")
        or template_categories != previous.get("template_categories")
        or generic_template_available != previous.get("generic_template_available")
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
    :root{--navy:#17324d;--blue:#245b8f;--line:#d9e1e8;--bg:#f3f6f8;--muted:#667583;--bad:#a43333}
    *{box-sizing:border-box}body{margin:0;color:#17212b;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
    header{padding:24px 28px 18px;color:white;background:linear-gradient(120deg,var(--navy),var(--blue))}h1{margin:0 0 8px;font-size:26px}header p{margin:0;opacity:.86}
    main{padding:18px 22px 28px}.metrics{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:14px}.metric{min-width:140px;padding:13px 16px;border:1px solid var(--line);border-radius:10px;background:white}.metric b{display:block;margin-top:3px;color:var(--navy);font-size:22px}
    .toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:10px 10px 0 0;background:white}input,select,textarea,button{font:inherit}input,select,textarea{min-height:38px;padding:7px 10px;border:1px solid #b9c6d0;border-radius:7px;background:white}input[type=search]{flex:1;min-width:250px}button{min-height:32px;padding:5px 10px;border:0;border-radius:6px;color:white;background:var(--blue);cursor:pointer;font-weight:700}button:disabled{opacity:.55;cursor:not-allowed}.count{margin-left:auto;color:var(--muted)}
    .table-wrap{max-height:calc(100vh - 300px);overflow:auto;border:1px solid var(--line);border-top:0;background:white}table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;font-size:13px}th{position:sticky;top:0;z-index:2;padding:9px 7px;color:white;background:var(--navy);text-align:left}td{padding:8px 7px;border-bottom:1px solid #e5eaee;vertical-align:top;overflow-wrap:anywhere}tbody tr:hover{background:#f7fbff}th:nth-child(1){width:4%}th:nth-child(2){width:7%}th:nth-child(3){width:7%}th:nth-child(4){width:8%}th:nth-child(5){width:11%}th:nth-child(6){width:17%}th:nth-child(7){width:23%}th:nth-child(8){width:11%}th:nth-child(9){width:12%}
    .content{max-height:9em;overflow:auto;white-space:pre-line;line-height:1.5}.files,.actions{display:flex;flex-wrap:wrap;gap:5px}.file{display:inline-block;max-width:100%;padding:4px 6px;border:1px solid #bed3e4;border-radius:5px;background:#f3f9fd;color:#174d7a;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file:hover{background:var(--blue);color:white}.subject{color:#174d7a;font-weight:600}.subject-button{padding:0;color:#174d7a;background:none;text-align:left}.subject-button:hover{text-decoration:underline}.status{font-weight:700}.complete{color:#26734d}.incomplete{color:var(--bad)}.needs_review{color:#a15c00}.warning{display:block;margin-top:4px;color:#a15c00;font-size:12px}.empty{padding:40px;text-align:center;color:var(--muted)}.delete{background:var(--bad)}
    .new-row{position:sticky;bottom:0;z-index:1;background:#eef6fc}.new-row td{padding:6px 4px}.new-row input,.new-row select,.new-row textarea{width:100%;min-width:0;padding:6px;font-size:12px}.new-row textarea{min-height:80px;resize:vertical}.note{display:block;margin-top:5px;color:var(--muted);font-size:11px;white-space:normal}
    dialog{width:min(760px,calc(100vw - 32px));padding:0;border:0;border-radius:12px;box-shadow:0 18px 60px #07152155}dialog::backdrop{background:#07152199}.dialog-head{padding:17px 20px;color:white;background:var(--navy)}.dialog-head h2{margin:0;font-size:19px}.dialog-body{padding:18px 20px}.dialog-body label{display:block;margin-bottom:12px;color:var(--navy);font-weight:700}.dialog-body input,.dialog-body textarea{display:block;width:100%;margin-top:5px;font-weight:400}.dialog-body textarea{min-height:220px;resize:vertical;line-height:1.6}.dialog-actions{display:flex;justify-content:flex-end;gap:8px;padding:0 20px 18px}.secondary{color:var(--navy);border:1px solid var(--line);background:white}
    @media(max-width:1100px){main{padding:10px}.table-wrap{max-height:none}table{min-width:1260px}}@media print{.toolbar,.new-row,.actions{display:none}.table-wrap{max-height:none;overflow:visible}}
  </style>
</head>
<body>
  <header><h1>主体工作联系单汇总</h1><p>现有资料的目录编号仅作临时索引，原 Word 的未编号内容保持原样；修改与删除保留可恢复的旧版。</p></header>
  <main>
    <section class="metrics"><div class="metric">联系单总数<b id="total"></b></div><div class="metric">资料齐全<b id="complete"></b></div><div class="metric">有提示记录<b id="warnings"></b></div><div class="metric">未匹配文件<b id="unmatchedCount"></b></div></section>
    <section class="toolbar"><input id="search" type="search" placeholder="搜索类别、编号、日期、致送单位、主题、正文……" aria-label="搜索联系单"><select id="statusFilter" aria-label="按状态筛选"><option value="">全部状态</option><option value="complete">资料齐全</option><option value="incomplete">资料不完整</option><option value="needs_review">待核对</option></select><button id="refresh" type="button">重新扫描刷新</button><span class="count">当前显示 <b id="visible"></b> 条</span></section>
    <div class="table-wrap"><table><thead><tr><th>序号</th><th>类别</th><th>编号</th><th>日期</th><th>致送单位</th><th>主题</th><th>内容</th><th>资料文件</th><th>状态 / 操作</th></tr></thead><tbody id="body"></tbody></table><div id="empty" class="empty" hidden>没有符合当前条件的记录</div></div>
    <details id="unmatchedDetails"><summary>查看未匹配文件</summary><ul id="unmatchedList"></ul></details>
  </main>
  <dialog id="editDialog"><div class="dialog-head"><h2 id="editTitle">修改主体工作联系单</h2></div><form id="editForm"><div class="dialog-body"><label>日期<input id="editDate" type="date" required></label><label>致送单位<input id="editRecipient" maxlength="100" required></label><label>主题<input id="editSubject" maxlength="120" required></label><label>内容<textarea id="editContent" maxlength="10000" required></textarea></label></div><div class="dialog-actions"><button id="editCancel" class="secondary" type="button">取消</button><button id="editSave" type="submit">保存修改</button></div></form></dialog>
  <script type="application/json" id="summaryData">__DATA__</script>
  <script>
    const data=JSON.parse(document.getElementById('summaryData').textContent),$=id=>document.getElementById(id);
    const service=['http:','https:'].includes(location.protocol),rows=data.records||[];
    const fileHref=path=>(service?'/work-contact/':'./')+path.split('/').map(encodeURIComponent).join('/');
    function localDate(){const now=new Date();return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`}
    function cell(value){const td=document.createElement('td');td.textContent=value??'';return td}
    function numberLabel(row){return (row.sequence_no||row.document_code||'—')+(row.temporary_number?'（临时编号）':'')}
    function codeLabel(row){return (row.document_code||'—')+(row.temporary_number?'（临时编号）':'')}
    function button(label,action,className){const element=document.createElement('button');element.type='button';element.textContent=label;if(className)element.className=className;element.addEventListener('click',action);return element}
    async function post(route,payload){if(!service)throw new Error('请通过 serve_summary.py 或 EXE 打开页面');const response=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error||'操作失败');return result}
    async function openFolder(row){if(!row.folder_path)return;if(!service){location.href='./'+row.folder_path.split('/').map(encodeURIComponent).join('/')+'/';return}try{await post('/api/open-work-contact-path',{path:row.folder_path})}catch(error){alert(error.message)}}
    $('total').textContent=rows.length;$('complete').textContent=rows.filter(row=>row.status==='complete').length;$('warnings').textContent=rows.filter(row=>row.warnings.length).length;$('unmatchedCount').textContent=(data.unmatched_files||[]).length;
    $('unmatchedDetails').hidden=!(data.unmatched_files||[]).length;(data.unmatched_files||[]).forEach(path=>{const item=document.createElement('li');item.textContent=path;$('unmatchedList').append(item)});
    let activeRecord=null;
    function edit(row){activeRecord=row;$('editTitle').textContent=`修改 ${codeLabel(row)}`;$('editDate').value=row.folder_date;$('editRecipient').value=row['致送单位'];$('editSubject').value=row.subject;$('editContent').value=row['内容'];$('editDialog').showModal()}
    async function remove(row){if(!confirm(`确认把“${codeLabel(row)} ${row.subject}”移入 _trash？`))return;try{await post('/api/delete-work-contact',{dataset_revision:data.dataset_revision,record_id:row.record_id,folder_path:row.folder_path});location.reload()}catch(error){alert(`删除失败：${error.message}`)}}
    function render(){const query=$('search').value.trim().toLowerCase(),status=$('statusFilter').value;const visible=rows.filter(row=>(!status||row.status===status)&&(!query||[row.discipline,row.sequence_no,row.folder_date,row.document_code,row['致送单位'],row.subject,row['内容'],row.word_subject].join(' ').toLowerCase().includes(query)));const body=$('body');body.replaceChildren();visible.forEach((row,index)=>{const tr=document.createElement('tr'),numberCell=cell(numberLabel(row));numberCell.title=`原 Word 资料编号：${row.original_document_no||'未填写'}`;tr.append(cell(index+1),cell(row.discipline||'—'),numberCell,cell(row.folder_date),cell(row['致送单位']||'—'));const subject=cell('');subject.className='subject';if(row.folder_path)subject.append(button(row.subject,()=>openFolder(row),'subject-button'));else subject.textContent=row.subject;tr.append(subject);const content=cell(''),view=document.createElement('div');view.className='content';view.textContent=row['内容'];content.append(view);tr.append(content);const files=cell(''),fileWrap=document.createElement('div');fileWrap.className='files';(row.files||[]).forEach(file=>{const link=document.createElement('a');link.className='file';link.textContent=({source_word:'Word',auxiliary_word:'Word副本',issued_pdf:'PDF',signed_scan:'扫描件',attachment_pdf:'附件PDF'})[file.role]||'附件';link.title=file.name;link.href=fileHref(file.path);link.target='_blank';link.rel='noopener';fileWrap.append(link)});files.append(fileWrap);tr.append(files);const state=cell(''),statusLabel=document.createElement('div');statusLabel.className='status '+row.status;statusLabel.textContent=({complete:'资料齐全',incomplete:'资料不完整',needs_review:'待核对'})[row.status]||row.status;state.append(statusLabel);(row.warnings||[]).forEach(message=>{const note=document.createElement('span');note.className='warning';note.textContent=message;state.append(note)});if(row.folder_path){const actions=document.createElement('div');actions.className='actions';actions.append(button('修改',()=>edit(row)),button('删除',()=>remove(row),'delete'));state.append(actions)}else state.append(document.createTextNode('待整理目录'));tr.append(state);body.append(tr)});buildNewRow(body);$('visible').textContent=visible.length;$('empty').hidden=visible.length!==0}
    function buildNewRow(body){const tr=document.createElement('tr');tr.className='new-row';tr.append(cell('新增'));const categories=[...new Set(rows.map(row=>row.discipline).filter(Boolean))].sort(),categoryCell=cell(''),category=document.createElement('input'),suggestions=document.createElement('datalist');category.type='text';category.maxLength=30;category.placeholder='输入类别';category.value=categories[0]||'';suggestions.id='contactCategories';category.setAttribute('list',suggestions.id);categories.forEach(value=>{const option=document.createElement('option');option.value=value;suggestions.append(option)});categoryCell.append(category,suggestions);tr.append(categoryCell);const codeCell=cell('自动');tr.append(codeCell);const dateCell=cell(''),dateInput=document.createElement('input');dateInput.type='date';dateInput.value=localDate();dateCell.append(dateInput);tr.append(dateCell);const recipientCell=cell(''),recipient=document.createElement('input');recipient.placeholder='致送单位';recipientCell.append(recipient);tr.append(recipientCell);const subjectCell=cell(''),subject=document.createElement('input');subject.placeholder='主题';subjectCell.append(subject);tr.append(subjectCell);const contentCell=cell(''),content=document.createElement('textarea');content.placeholder='联系单内容';contentCell.append(content);tr.append(contentCell);tr.append(cell('保存后生成 Word 和 PDF'));const actionCell=cell(''),save=button('新增联系单',async()=>{save.disabled=true;try{await post('/api/create-work-contact',{dataset_revision:data.dataset_revision,discipline:category.value,folder_date:dateInput.value,recipient:recipient.value,subject:subject.value,content:content.value});location.reload()}catch(error){alert(`新增失败：${error.message}`);updateTemplate()}}),note=document.createElement('span');note.className='note';const updateTemplate=()=>{const ready=Boolean(category.value.trim())&&(data.generic_template_available||(data.template_categories||[]).includes(category.value.trim()));save.disabled=!ready;note.textContent=ready?'类别可手动输入；编号按类别自动生成':'请输入类别并放入可用模板'};category.addEventListener('input',updateTemplate);updateTemplate();actionCell.append(save,note);tr.append(actionCell);body.append(tr)}
    $('editCancel').addEventListener('click',()=>{$('editDialog').close();activeRecord=null});$('editForm').addEventListener('submit',async event=>{event.preventDefault();if(!activeRecord)return;const save=$('editSave');save.disabled=true;try{await post('/api/update-work-contact',{dataset_revision:data.dataset_revision,record_id:activeRecord.record_id,folder_date:$('editDate').value,recipient:$('editRecipient').value,subject:$('editSubject').value,content:$('editContent').value});location.reload()}catch(error){alert(`修改失败：${error.message}`);save.disabled=false}});
    $('refresh').addEventListener('click',async event=>{const control=event.currentTarget;control.disabled=true;try{await post('/api/refresh-work-contact',{});location.reload()}catch(error){alert(`刷新失败：${error.message}`);control.disabled=false}});$('search').addEventListener('input',render);$('statusFilter').addEventListener('change',render);render();
  </script>
</body>
</html>
'''
