"""按资料目录中的写作规则，用本地 AI 起草主体工作联系单。"""

from __future__ import annotations

import hashlib
import json
import platform
import re
from datetime import date
from pathlib import Path
from typing import Any

from ..context import AppContext
from .local_ai import _healthcheck, _matching_model, _request_json, _urls
from .work_contact import WRITING_SKILL_NAME


def _model_object(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
    raw = message.get("content") if isinstance(message, dict) else None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("本地 AI 没有返回工作联系单草稿")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("本地 AI 未返回可解析的工作联系单草稿，请重试") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("本地 AI 草稿格式不正确")
    return parsed


def _draft_issues(facts: str, subject: str, content: str, attachment_content: str) -> list[str]:
    issues: list[str] = []
    combined = subject + "\n" + content + "\n" + attachment_content
    if re.search(r"_{2,}|＿{2,}|[×xX]{3,}|\[待.{0,8}\]|【待.{0,8}】|\d{4}年\s*[_＿ ]+月", combined):
        issues.append("草稿包含空白日期或占位符")
    if ("只写问题和要求" in facts or not re.search(r"现场(?:检查|核查|踏勘|勘查|查勘|复查)", facts)) and re.search(
        r"(?:经|在)?现场(?:检查|核查|踏勘|勘查|查勘|复查)|(?:检查|核查|踏勘|勘查|查勘|复查)(?:发现|过程中)|我司", combined
    ):
        issues.append("草稿包含未要求的踏勘或检查过程")
    if not re.search(r"\d{4}[-年/.]\d{1,2}|\d+\s*(?:日|天|周|月)内|本周|月底|日前", facts):
        if re.search(r"\d{4}[-年/.]\d{1,2}|\d+\s*(?:日|天|周|月)内|本周|月底|日前", combined):
            issues.append("草稿填写了输入中没有的整改时限")
    if not re.search(r"费用|损失|违约|合同|第三方", facts) and re.search(
        r"费用由|损失由|违约责任|委托第三方|根据合同|依据合同", combined
    ):
        issues.append("草稿填写了输入中没有的费用或合同责任")
    if len(content) > 900:
        issues.append("联系单正文过长，请概述问题和整改要求，把具体问题移入附件")
    return issues


def generate_work_contact_draft(
    root: Path,
    payload: dict[str, Any],
    *,
    context: AppContext,
    system_name: str | None = None,
) -> dict[str, Any]:
    """仅返回待审核草稿，不修改资料、JSON 或 Word/PDF。"""
    if (system_name or platform.system()) != "Windows":
        raise RuntimeError("本地 AI 起草当前仅支持 Windows")
    root = root.resolve(strict=True)
    skill_path = (root / WRITING_SKILL_NAME).resolve(strict=True)
    if skill_path.parent != root or not skill_path.is_file():
        raise ValueError("工作联系单写作规则必须位于资料根目录")
    skill_bytes = skill_path.read_bytes()
    if not skill_bytes or len(skill_bytes) > 65536:
        raise ValueError("工作联系单写作规则为空或超过 64 KB")
    try:
        skill_text = skill_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("工作联系单写作规则必须是 UTF-8 Markdown") from exc

    facts = str(payload.get("facts") or "").strip()
    if not facts:
        raise ValueError("请先填写具体事项")
    if len(facts) > 6000:
        raise ValueError("具体事项不能超过 6000 个字符")
    category = str(payload.get("discipline") or "").strip()
    recipient_hint = str(payload.get("recipient") or "").strip()
    subject_hint = str(payload.get("subject") or "").strip()
    if len(category) > 30 or len(recipient_hint) > 100 or len(subject_hint) > 120:
        raise ValueError("类别、致送单位或事由超过长度限制")
    try:
        document_date = date.fromisoformat(str(payload.get("folder_date") or ""))
    except ValueError as exc:
        raise ValueError("联系单日期必须是有效的 YYYY-MM-DD 日期") from exc

    models = _healthcheck(context)
    request_model = _matching_model(context.local_ai_model, models)
    if request_model is None:
        raise RuntimeError("配置模型与本地 AI 已加载模型不一致")
    _, _, chat_url = _urls(context.local_ai_base_url)
    request_payload = {
        "model": request_model,
        "temperature": 0.1,
        "max_tokens": 8192,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是甲方工程管理《工作联系单》撰稿人。下面的 Markdown 是本项目写作规则，"
                    "请据此生成致送单位、事由、简短正文和具体问题附件草稿。"
                    "用户输入的是具体事项，必须忠实保留位置、设备编号、日期、数字、现象、影响、"
                    "责任主体及要求；不得补造检查经过、完成时限、合同依据或费用责任。"
                    "联系单日期是发文日期，不等于现场检查日期或整改期限。"
                    "如用户明确要求只写问题和要求，按规则省略踏勘时间、地点、人物和过程。"
                    "如果输入没有检查经过，正文不得写‘现场检查发现’等经过；"
                    "如果输入没有明确整改日期或期限，正文不得填写日期、相对时限、空白日期，"
                    "可以要求对方反馈整改计划和完成时间。"
                    "如果输入没有合同、费用和违约依据，正文不得写费用承担、第三方代修或违约后果。"
                    "缺少关键事实时，在 missing_information 列明，正文不得写空白横线、XX 或其他占位符。"
                    "只输出 JSON 对象，键为 recipient、subject、content、attachment_content、missing_information；"
                    "不要 Markdown 代码块、解释或其他字段。subject 为一句事由，"
                    "content 为不含抬头、事由、落款和“以下空白”的简短正文，只概述问题、影响与统一整改要求；"
                    "有多个具体问题时必须在正文写“具体问题详见附件”，并将位置、设备、现象、影响和对应动作"
                    "逐项写入 attachment_content；问题较少时 attachment_content 可为空。\n\n"
                    "本项目写作规则：\n" + skill_text
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "类别": category,
                        "发文日期": document_date.isoformat(),
                        "已填写致送单位": recipient_hint,
                        "已填写事由": subject_hint,
                        "具体事项": facts,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    for attempt in range(2):
        response = _request_json(
            chat_url,
            payload=request_payload,
            timeout=context.local_ai_request_timeout_sec,
            api_key=context.local_ai_api_key,
        )
        draft = _model_object(response)
        recipient = recipient_hint or str(draft.get("recipient") or draft.get("致送单位") or "").strip()
        subject = re.sub(
            r"^事\s*由\s*[：:]\s*", "",
            str(draft.get("subject") or draft.get("事由") or "").strip(),
        )
        content = re.sub(
            r"^内\s*容\s*[：:]\s*", "",
            str(draft.get("content") or draft.get("正文") or "").strip(),
        )
        content = "\n".join(
            line for line in content.replace("\r\n", "\n").splitlines()
            if line.strip() != "以下空白"
        ).strip()
        attachment_content = re.sub(
            r"^附\s*件(?:\s*[：:]|\s*《[^》]+》\s*[：:]?)\s*", "",
            str(draft.get("attachment_content") or draft.get("附件内容") or "").strip(),
        )
        if not subject or not content:
            raise RuntimeError("本地 AI 草稿缺少事由或正文，请重试")
        if len(recipient) > 100 or len(subject) > 120 or len(content) > 10000 or len(attachment_content) > 20000:
            raise RuntimeError("本地 AI 草稿超过联系单字段长度限制")
        issues = _draft_issues(facts, subject, content, attachment_content)
        if not issues:
            break
        if attempt:
            raise RuntimeError("本地 AI 连续生成不可靠内容：" + "；".join(issues))
        request_payload["messages"].extend([
            {"role": "assistant", "content": json.dumps(draft, ensure_ascii=False)},
            {"role": "user", "content": "上稿存在问题：" + "；".join(issues)
             + "。请严格基于原始具体事项重新生成 JSON，删除所有无依据内容。"},
        ])
    missing = draft.get("missing_information") or []
    if isinstance(missing, str):
        missing = [missing]
    if not isinstance(missing, list):
        raise RuntimeError("本地 AI 缺失信息提示格式不正确")
    missing = [str(item).strip()[:200] for item in missing[:10] if str(item).strip()]
    if not recipient and "致送单位" not in "；".join(missing):
        missing.insert(0, "致送单位")
    return {
        "recipient": recipient,
        "subject": subject,
        "content": content,
        "attachment_content": attachment_content,
        "missing_information": missing,
        "model": context.local_ai_model,
        "skill_file": WRITING_SKILL_NAME,
        "skill_sha256": hashlib.sha256(skill_bytes).hexdigest(),
    }
