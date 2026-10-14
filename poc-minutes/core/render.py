"""FR-08: 확정된 내용을 06_의사록양식.docx(docxtpl)에 채워 .docx로 만든다 (R14 초안 표시)."""
from __future__ import annotations

import io

import pandas as pd
from docxtpl import DocxTemplate

from .config import DECISION_LABELS, DEFAULT_FILES
from .meeting import MeetingContext
from .rules import decision_time, due_is_open

DRAFT_MARK = "[초안 – 담당자 확정 전, 최종본으로 사용 금지]"
FINAL_MARK = "[교육용 가상 자료]"


def _names(ctx: MeetingContext, ids: list[str]) -> str:
    return ", ".join(ctx.name(i) for i in ids)


def build_context(result: dict, ctx: MeetingContext, agendas: pd.DataFrame, transcript: pd.DataFrame,
                  confirmed: bool) -> dict:
    ov = ctx.overview()
    info = ctx.info
    meta = agendas.set_index("agenda_id")
    leave_by_id = {e["member_id"]: e["time"] for e in info["early_leave"]}

    present_text = f"{ov['present']}명 (출석률 {ov['attendance_rate']}%)"
    if info["early_leave"]:
        after = len(ctx.present_voting_at("23:59"))
        present_text += " ※ " + ", ".join(ov["early_leaves"]) + f", 이후 출석 {after}명"

    members = []
    for m in ctx.members.itertuples():
        if m.member_id in ctx.absent_ids:
            status = "불참"
        elif not m.is_voting:
            status = "출석(의결권 없음)"
        elif m.member_id in leave_by_id:
            status = f"출석({leave_by_id[m.member_id]} 이석)"
        else:
            status = "출석"
        members.append({"role": m.role, "name": m.name, "dept": m.dept, "position": m.position, "status": status})

    ag_ctx, follow_ups = [], []
    prev_present = len(ctx.present_voting_at_open)
    for a in result["agendas"]:
        aid = a["agenda_id"]
        row = meta.loc[aid]
        present = ctx.present_voting_at(decision_time(a, transcript))
        note = ""
        if row["agenda_type"] == "의결" and len(present) != prev_present:
            gone = [ctx.name(e["member_id"]) + f" 위원 이석({e['time']})" for e in info["early_leave"]
                    if e["member_id"] not in present and e["member_id"] in ctx.present_voting_at_open]
            ok = len(present) > len(ctx.voting_ids) * ctx.settings.quorum_ratio
            note = f"{', '.join(gone)}으로 표결 시점 출석위원은 {len(present)}명이며, 의결 정족수는 {'충족' if ok else '미충족'}됨."
        if row["agenda_type"] == "의결":
            prev_present = len(present)

        label = DECISION_LABELS.get(a["decision"], a["decision"] or "(미정)")
        detail_parts = []
        v = a["votes"]
        if row["agenda_type"] == "의결":
            n_for, n_ag, n_ab = len(v["for"]), len(v["against"]), len(v["abstain"])
            if n_for == len(present) and not n_ag and not n_ab:
                label += f" (출석 {len(present)}명 전원 찬성)"
            else:
                label += f" (출석 {len(present)}명 중 찬성 {n_for}명" + (f", 반대 {n_ag}명" if n_ag else "") + \
                         (f", 기권 {n_ab}명" if n_ab else "") + ")"
                detail_parts.append(f"찬성: {_names(ctx, v['for'])}" + (f" / 반대: {_names(ctx, v['against'])}" if n_ag else "")
                                    + (f" / 기권: {_names(ctx, v['abstain'])}" if n_ab else ""))
            if a.get("decision_condition"):
                detail_parts.append(f"조건: {a['decision_condition']}")
        if a.get("vote_note"):
            detail_parts.append(a["vote_note"])

        ag_ctx.append({
            "no": int(row["agenda_no"]), "type": row["agenda_type"], "title": row["title"],
            "presenter": row["presenter_dept"], "note": note, "summary": a["summary"],
            "discussions": [{"speaker": ctx.display_speaker(d["speaker_id"]), "type": d["type"], "content": d["content"]}
                            for d in a["discussions"]],
            "decision_text": label,
            "decision_detail": " ".join(p if p.endswith(".") else p + "." for p in detail_parts),
        })
        for f in a["follow_ups"]:
            remark = f.get("remark", "")
            if due_is_open(f["due"]):
                remark = "기한 확인 필요" + (f", {remark}" if remark else "")
            follow_ups.append({"no": len(follow_ups) + 1, "agenda": f"제{int(row['agenda_no'])}호", "task": f["task"],
                               "owner": f["owner_dept"], "due": f["due"] or "미정", "remark": remark})

    d = ctx.meeting_date
    return {
        "session_no": info["session_no"],
        "draft_mark": FINAL_MARK if confirmed else DRAFT_MARK,
        "meeting_datetime": f"{ctx.date_text()} {info['start_time']} ~ {info['end_time']} ({ov['duration_min']}분)",
        "location": info["location"],
        "chair_name": ctx.name(info["chair_id"]),
        "secretary_name": ctx.name(info["secretary_id"]),
        "total_members": ov["total"],
        "present_text": present_text,
        "absent_text": f"{ov['absent']}명 ({', '.join(n + ' 위원' for n in ov['absent_names'])})" if ov["absent"] else "없음",
        "quorum_text": f"{'충족' if ov['quorum_ok'] else '미충족'} (출석 {ov['present']}명 > 재적 {ov['total']}명의 과반 {ov['quorum_threshold']:g}명)",
        "members": members,
        "agendas": ag_ctx,
        "follow_ups": follow_ups,
        "sign_date": f"{d.year}년 {d.month}월 {d.day}일",
    }


def render_docx(context: dict, template_path=None) -> bytes:
    tpl = DocxTemplate(str(template_path or DEFAULT_FILES["template"]))
    tpl.render(context)
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()
