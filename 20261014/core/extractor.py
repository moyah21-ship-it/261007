"""FR-05, FR-06: Claude API로 안건별 내용 추출 / API 키가 없으면 모의 모드."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy

import pandas as pd

from .config import DEFAULT_FILES, PROMPT_DIR, Settings
from .loader import transcript_for_prompt
from .meeting import WEEKDAYS, MeetingContext


class ExtractionError(RuntimeError):
    pass


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------- 결과 정리
def _empty_agenda(agenda_id: str) -> dict:
    return {"agenda_id": agenda_id, "summary": "", "discussions": [], "decision": "",
            "decision_condition": "", "decision_line": None,
            "votes": {"for": [], "against": [], "abstain": []}, "vote_note": "", "follow_ups": []}


def normalize(result: dict, agendas: pd.DataFrame) -> dict:
    """AI 결과의 빠진 키를 채우고 안건목록 순서에 맞춘다."""
    if not isinstance(result, dict) or not isinstance(result.get("agendas"), list):
        raise ExtractionError("결과에 'agendas' 목록이 없습니다.")
    by_id = {a.get("agenda_id"): a for a in result["agendas"] if isinstance(a, dict)}
    out = []
    for aid in agendas["agenda_id"]:
        a = _empty_agenda(aid)
        a.update({k: v for k, v in by_id.get(aid, {}).items() if v is not None})
        a["votes"] = {k: list(a.get("votes", {}).get(k, []) or []) for k in ("for", "against", "abstain")}
        a["discussions"] = [
            {"speaker_id": d.get("speaker_id"), "type": d.get("type", ""), "content": d.get("content", ""),
             "source_lines": [int(x) for x in d.get("source_lines", []) or [] if str(x).isdigit()]}
            for d in a.get("discussions", []) or []]
        a["follow_ups"] = [
            {"task": f.get("task", ""), "owner_dept": f.get("owner_dept", ""), "due": f.get("due", "") or "",
             "remark": f.get("remark", "") or "",
             "source_lines": [int(x) for x in f.get("source_lines", []) or [] if str(x).isdigit()]}
            for f in a.get("follow_ups", []) or []]
        a["_missing"] = aid not in by_id
        out.append(a)
    return {"agendas": out}


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise ExtractionError("응답에서 JSON을 찾지 못했습니다.")
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"JSON 형식 오류: {e}") from e


# ---------------------------------------------------------------- 프롬프트
def build_prompt(ctx: MeetingContext, agendas: pd.DataFrame, transcript: pd.DataFrame) -> tuple[str, str]:
    tpl = (PROMPT_DIR / "extract_prompt.md").read_text(encoding="utf-8")
    system = tpl.format(meeting_date=ctx.info["meeting_date"], weekday=WEEKDAYS[ctx.meeting_date.weekday()])
    members = "\n".join(f"{r.member_id}\t{r.name}\t{r.role}\t{r.dept}\t{'의결권' if r.is_voting else '의결권없음'}"
                        for r in ctx.members.itertuples())
    leaves = ", ".join(f"{ctx.name(e['member_id'])}({e['member_id']}) {e['time']} 이석" for e in ctx.info["early_leave"]) or "없음"
    absent = ", ".join(f"{ctx.name(m)}({m})" for m in ctx.absent_ids) or "없음"
    ag = "\n".join(f"{r.agenda_id}\t제{r.agenda_no}호\t{r.agenda_type}\t{r.title}\t{r.presenter_dept}"
                   for r in agendas.itertuples())
    user = (f"[회의] {ctx.info['session_no']} / {ctx.info['meeting_date']} {ctx.info['start_time']}~{ctx.info['end_time']}\n"
            f"[불참] {absent}\n[이석] {leaves}\n\n[위원명단]\n{members}\n\n[안건목록]\n{ag}\n\n"
            f"[녹취록]\n{transcript_for_prompt(transcript)}")
    return system, user


# ---------------------------------------------------------------- 실행
def extract_with_claude(ctx: MeetingContext, agendas: pd.DataFrame, transcript: pd.DataFrame,
                        settings: Settings, client=None) -> dict:
    """Claude API 호출. JSON 형식 오류면 1회 재요청한다."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    system, user = build_prompt(ctx, agendas, transcript)
    messages = [{"role": "user", "content": user}]
    last_err = None
    for _ in range(2):
        resp = client.messages.create(model=settings.model, max_tokens=settings.max_tokens,
                                      system=system, messages=messages)
        text = "".join(getattr(b, "text", "") for b in resp.content)
        try:
            return normalize(_parse_json(text), agendas)
        except ExtractionError as e:
            last_err = e
            messages = messages + [{"role": "assistant", "content": text},
                                   {"role": "user", "content": f"출력이 올바른 JSON이 아닙니다({e}). 지정한 형식의 JSON만 다시 출력해 주세요."}]
    raise ExtractionError(f"AI 응답을 해석하지 못했습니다: {last_err}. 사이드바에서 모의 모드로 전환해 시연할 수 있습니다.")


def extract_mock(agendas: pd.DataFrame, path=None) -> dict:
    data = json.loads((path or DEFAULT_FILES["mock"]).read_text(encoding="utf-8"))
    return normalize(deepcopy(data), agendas)
