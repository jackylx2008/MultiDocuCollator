"""生成主体工作联系单的独立 JSON 和只读 HTML 汇总。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..modules.file_utils import atomic_replace_text
from ..modules.summary_html import _json_for_script
from ..modules.work_contact import scan_work_contacts


JSON_NAME = "主体工作联系单数据.json"
HTML_NAME = "主体工作联系单汇总.html"


def build_work_contact_archive(root: Path) -> dict[str, Any]:
    root = root.resolve()
    records, unmatched = scan_work_contacts(root)
    json_path = root / JSON_NAME
    previous = json.loads(json_path.read_text(encoding="utf-8")) if json_path.is_file() else {}
    changed = records != previous.get("records") or unmatched != previous.get("unmatched_files")
    revision = int(previous.get("dataset_revision") or 0) + int(changed)
    data = {
        "schema_version": 1,
        "dataset_revision": revision,
        "data_root": str(root),
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "records": records,
        "unmatched_files": unmatched,
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
    :root{--navy:#17324d;--blue:#245b8f;--line:#d9e1e8;--bg:#f3f6f8;--muted:#667583}
    *{box-sizing:border-box}body{margin:0;color:#17212b;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
    header{padding:24px 28px 18px;color:white;background:linear-gradient(120deg,var(--navy),var(--blue))}h1{margin:0 0 8px;font-size:26px}header p{margin:0;opacity:.86}
    .workflow-nav{display:flex;gap:8px;margin-top:16px}.workflow-nav a{padding:8px 14px;border:1px solid #ffffff80;border-radius:7px;color:white;text-decoration:none}.workflow-nav a[aria-current="page"]{background:#ffffff2b;font-weight:700}
    main{padding:18px 22px 28px}.metrics{display:flex;gap:12px;margin-bottom:14px}.metric{min-width:140px;padding:13px 16px;border:1px solid var(--line);border-radius:10px;background:white}.metric b{display:block;margin-top:3px;color:var(--navy);font-size:22px}
    .toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:10px 10px 0 0;background:white}input,select,button{min-height:38px;padding:7px 10px;border:1px solid #b9c6d0;border-radius:7px;background:white;font:inherit}input[type=search]{flex:1;min-width:250px}button{color:white;border:0;background:var(--blue);cursor:pointer;font-weight:700}.count{margin-left:auto;color:var(--muted)}
    .table-wrap{max-height:calc(100vh - 300px);overflow:auto;border:1px solid var(--line);border-top:0;background:white}table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;font-size:13px}th{position:sticky;top:0;padding:9px 7px;color:white;background:var(--navy);text-align:left}td{padding:8px 7px;border-bottom:1px solid #e5eaee;vertical-align:top;overflow-wrap:anywhere}tbody tr:hover{background:#f7fbff}th:nth-child(1){width:4%}th:nth-child(2){width:9%}th:nth-child(3){width:8%}th:nth-child(4){width:13%}th:nth-child(5){width:18%}th:nth-child(6){width:27%}th:nth-child(7){width:11%}th:nth-child(8){width:10%}
    .content{max-height:9em;overflow:auto;white-space:pre-line;line-height:1.5}.files{display:flex;flex-wrap:wrap;gap:5px}.file{display:inline-block;max-width:100%;padding:4px 6px;border:1px solid #bed3e4;border-radius:5px;background:#f3f9fd;color:#174d7a;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file:hover{background:var(--blue);color:white}.subject{color:#174d7a;font-weight:600}.status{font-weight:700}.complete{color:#26734d}.incomplete{color:#a43333}.needs_review{color:#a15c00}.warning{display:block;margin-top:4px;color:#a15c00;font-size:12px}.empty{padding:40px;text-align:center;color:var(--muted)}
    @media(max-width:1100px){main{padding:10px}.table-wrap{max-height:none}table{min-width:1100px}}@media print{.workflow-nav,.toolbar{display:none}.table-wrap{max-height:none;overflow:visible}}
  </style>
</head>
<body>
  <header><h1>主体工作联系单汇总</h1><p>扫描原始 Word、PDF 和扫描件；首版提供查看与筛选。</p><nav class="workflow-nav" aria-label="工作流"><a id="hotelLink" href="../../02%20%E9%85%92%E5%BA%97%E9%9C%80%E6%B1%82%E5%B7%A5%E4%BD%9C%E8%81%94%E7%B3%BB%E5%8D%95/%E9%85%92%E5%BA%97%E9%9C%80%E6%B1%82%E5%B7%A5%E4%BD%9C%E8%81%94%E7%B3%BB%E5%8D%95%E6%B1%87%E6%80%BB.html">酒店需求单</a><a href="./主体工作联系单汇总.html" aria-current="page">主体工作联系单</a></nav></header>
  <main><section class="metrics"><div class="metric">联系单总数<b id="total"></b></div><div class="metric">资料齐全<b id="complete"></b></div><div class="metric">有提示记录<b id="warnings"></b></div><div class="metric">未匹配文件<b id="unmatchedCount"></b></div></section>
    <section class="toolbar"><input id="search" type="search" placeholder="搜索日期、编号、致送单位、主题、正文……" aria-label="搜索联系单"><select id="statusFilter" aria-label="按状态筛选"><option value="">全部状态</option><option value="complete">资料齐全</option><option value="incomplete">资料不完整</option><option value="needs_review">待核对</option></select><button id="refresh" type="button">重新扫描刷新</button><span class="count">当前显示 <b id="visible"></b> 条</span></section>
    <div class="table-wrap"><table><thead><tr><th>序号</th><th>日期</th><th>资料编号</th><th>致送单位</th><th>主题</th><th>内容</th><th>资料文件</th><th>状态 / 核对</th></tr></thead><tbody id="body"></tbody></table><div id="empty" class="empty" hidden>没有符合当前条件的记录</div></div><details id="unmatchedDetails"><summary>查看未匹配文件</summary><ul id="unmatchedList"></ul></details>
  </main>
  <script type="application/json" id="summaryData">__DATA__</script>
  <script>
    const data=JSON.parse(document.getElementById('summaryData').textContent),$=id=>document.getElementById(id);
    const service=location.protocol==='http:'||location.protocol==='https:';
    if(service){$('hotelLink').href='/';}
    const rows=data.records||[];$('total').textContent=rows.length;$('complete').textContent=rows.filter(row=>row.status==='complete').length;$('warnings').textContent=rows.filter(row=>row.warnings.length).length;$('unmatchedCount').textContent=(data.unmatched_files||[]).length;$('unmatchedDetails').hidden=!(data.unmatched_files||[]).length;(data.unmatched_files||[]).forEach(path=>{const li=document.createElement('li');li.textContent=path;$('unmatchedList').append(li)});
    function cell(text){const td=document.createElement('td');td.textContent=text??'';return td}
    function render(){const query=$('search').value.trim().toLowerCase(),status=$('statusFilter').value;const visible=rows.filter(row=>(!status||row.status===status)&&(!query||[row.folder_date,row.document_code,row['致送单位'],row.subject,row['内容'],row.word_subject].join(' ').toLowerCase().includes(query)));const body=$('body');body.replaceChildren();visible.forEach((row,index)=>{const tr=document.createElement('tr');tr.append(cell(index+1),cell(row.folder_date),cell(row.document_code||'—'),cell(row['致送单位']||'—'));const subject=cell(row.subject);subject.className='subject';tr.append(subject);const content=cell(''),contentView=document.createElement('div');contentView.className='content';contentView.textContent=row['内容'];content.append(contentView);tr.append(content);const files=cell(''),wrap=document.createElement('div');wrap.className='files';(row.files||[]).forEach(file=>{const a=document.createElement('a');a.className='file';a.textContent=file.role==='source_word'?'Word':file.role==='signed_scan'?'扫描件':'PDF';a.title=file.name;a.href=(service?'/work-contact/':'./')+file.path.split('/').map(encodeURIComponent).join('/');a.target='_blank';a.rel='noopener';wrap.append(a)});files.append(wrap);tr.append(files);const state=cell(({complete:'资料齐全',incomplete:'资料不完整',needs_review:'待核对'})[row.status]||row.status);state.className='status '+row.status;(row.warnings||[]).forEach(message=>{const note=document.createElement('span');note.className='warning';note.textContent=message;state.append(note)});tr.append(state);body.append(tr)});$('visible').textContent=visible.length;$('empty').hidden=visible.length!==0}
    $('search').addEventListener('input',render);$('statusFilter').addEventListener('change',render);$('refresh').addEventListener('click',async()=>{if(!service){alert('重新扫描请通过 serve_summary.py 打开页面');return}const button=$('refresh');button.disabled=true;button.textContent='正在扫描…';try{const response=await fetch('/api/refresh-work-contact',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const result=await response.json();if(!response.ok)throw new Error(result.error||'刷新失败');location.reload()}catch(error){alert(error.message);button.disabled=false;button.textContent='重新扫描刷新'}});render();
  </script>
</body>
</html>
'''
