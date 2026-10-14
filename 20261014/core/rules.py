"""FR-07: 업무규칙 R1~R14 검증. AI 결과를 그대로 믿지 않고 위반 항목을 경고로 돌려준다."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, asdict

import pandas as pd

from .config import DECISION_CODES, PASSED_CODES, Settings
from .loader import ALL_SPEAKER
from .meeting import MeetingContext

RELATIVE_WORDS = ("다음 주", "다음주", "이번 주", "이번주", "월 말", "월말", "말까지", "내일", "모레", "익월", "차주")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%p|%|건|명|일)?")


@dataclass
class Finding:
    rule: str
    level: str      # 경고 | 정보
    agenda: str     # 'AG-01' 또는 '회의'
    target: str     # 대상 항목
    message: str

    def to_dict(self):
        return asdict(self)


def line_time(transcript: pd.DataFrame, line_no) -> str | None:
    if line_no is None:
        return None
    hit = transcript[transcript["line_no"] == int(line_no)]
    return hit.iloc[0]["time"] if len(hit) else None


def decision_time(agenda: dict, transcript: pd.DataFrame) -> str | None:
    """표결(결과 선언) 시각. decision_line 이 없으면 근거 줄 중 가장 뒤의 줄."""
    line = agenda.get("decision_line")
    if not line:
        lines = [n for d in agenda["discussions"] for n in d["source_lines"]]
        lines += [n for f in agenda["follow_ups"] for n in f["source_lines"]]
        line = max(lines) if lines else None
    return line_time(transcript, line)


def present_at_vote(agenda: dict, ctx: MeetingContext, transcript: pd.DataFrame) -> list[str]:
    return ctx.present_voting_at(decision_time(agenda, transcript))


def due_is_open(due: str) -> bool:
    return (not due) or due.strip().startswith("미정")


def validate(result: dict, ctx: MeetingContext, agendas: pd.DataFrame, transcript: pd.DataFrame,
             settings: Settings) -> list[Finding]:
    out: list[Finding] = []
    ov = ctx.overview()
    meta = agendas.set_index("agenda_id")
    max_line = int(transcript["line_no"].max()) if len(transcript) else 0
    attendees = set(ctx.attendees) | {ALL_SPEAKER}

    # R1 개회 정족수
    out.append(Finding("R1", "정보" if ov["quorum_ok"] else "경고", "회의", "개회 정족수",
                       f"출석 {ov['present']}명 / 재적 {ov['total']}명 (기준: {ov['quorum_threshold']:g}명 초과) → "
                       + ("충족" if ov["quorum_ok"] else "미충족")))
    # R11 발언자 매핑
    unmapped = transcript[transcript["speaker_id"].isna()]
    if len(unmapped):
        out.append(Finding("R11", "경고", "회의", "발언자 매핑",
                           f"위원명단과 매핑되지 않은 발언 {len(unmapped)}줄: " +
                           ", ".join(sorted(set(unmapped["speaker_label"])))[:200]))
    # R13 기본 통계
    out.append(Finding("R13", "정보", "회의", "기본 통계",
                       f"출석률 {ov['attendance_rate']}%, 회의 소요시간 {ov['duration_min']}분"))

    # R7 정정 발언: '정정' 직전에 나온 수치가 결과에 남아 있으면 경고
    corrected = []
    for r in transcript.itertuples():
        if "정정" in r.utterance:
            before = r.utterance.split("정정")[0]
            nums = NUM_RE.findall(before)
            if nums:
                corrected.append((r.line_no, nums[-1].strip()))

    for a in result["agendas"]:
        aid = a["agenda_id"]
        atype = meta.loc[aid, "agenda_type"] if aid in meta.index else ""
        label = f"제{meta.loc[aid, 'agenda_no']}호" if aid in meta.index else aid

        if a.get("_missing"):
            out.append(Finding("R5", "경고", aid, label, "AI 결과에 이 안건이 없습니다. 직접 입력해 주세요."))

        # R5 안건 유형별 결과
        if not a["decision"]:
            out.append(Finding("R5", "경고", aid, label, "처리 결과가 비어 있습니다."))
        elif a["decision"] not in DECISION_CODES.get(atype, []):
            out.append(Finding("R5", "경고", aid, label,
                               f"{atype}안건에 맞지 않는 결과 '{a['decision']}' (허용: {', '.join(DECISION_CODES.get(atype, []))})"))

        votes = a["votes"]
        n_for, n_against, n_abs = len(votes["for"]), len(votes["against"]), len(votes["abstain"])
        if atype == "의결":
            present = present_at_vote(a, ctx, transcript)
            # R3 이석 반영 + R4 표결 합계
            voters = votes["for"] + votes["against"] + votes["abstain"]
            outsiders = [v for v in voters if v not in present]
            if outsiders:
                out.append(Finding("R3", "경고", aid, label,
                                   "표결 시점에 자리에 없는 위원이 표결자로 들어 있습니다: " + ", ".join(ctx.name(v) for v in outsiders)))
            if len(voters) != len(set(voters)):
                out.append(Finding("R4", "경고", aid, label, "같은 위원이 두 번 이상 표결자로 들어 있습니다."))
            if n_for + n_against + n_abs != len(present):
                out.append(Finding("R4", "경고", aid, label,
                                   f"찬성 {n_for}+반대 {n_against}+기권 {n_abs} = {n_for + n_against + n_abs}명이 "
                                   f"표결 시점 출석 {len(present)}명과 다릅니다."))
            # R2 의결 요건
            passed = n_for > len(present) * settings.pass_ratio
            if a["decision"] in PASSED_CODES and not passed:
                out.append(Finding("R2", "경고", aid, label,
                                   f"찬성 {n_for}명이 기준({len(present) * settings.pass_ratio:g}명 초과)에 못 미치는데 '가결'로 되어 있습니다."))
            elif a["decision"] == "부결" and passed:
                out.append(Finding("R2", "경고", aid, label, f"찬성 {n_for}명으로 가결 요건을 충족하는데 '부결'로 되어 있습니다."))
            else:
                out.append(Finding("R2", "정보", aid, label,
                                   f"표결 시점 출석 {len(present)}명 중 찬성 {n_for}·반대 {n_against}·기권 {n_abs} → 판정 일치"))
            if a["decision"] in ("수정가결", "조건부가결") and not a.get("decision_condition"):
                out.append(Finding("R5", "경고", aid, label, "수정·조건부 가결인데 조건 내용이 비어 있습니다."))
        elif n_for + n_against + n_abs:
            out.append(Finding("R4", "경고", aid, label, "보고안건에 표결 정보가 들어 있습니다."))

        # R6 발언 분류 / R10 원문 근거 / R12 출석 이상
        for i, d in enumerate(a["discussions"], 1):
            who = ctx.display_speaker(d["speaker_id"])
            tgt = f"{label} 발언 {i} ({who})"
            if d["type"] not in settings.discussion_types:
                out.append(Finding("R6", "경고", aid, tgt, f"발언 유형 '{d['type']}'은 허용되지 않습니다."))
            if not d["source_lines"]:
                out.append(Finding("R10", "경고", aid, tgt, "원문 근거 줄번호가 없습니다."))
            elif any(n < 1 or n > max_line for n in d["source_lines"]):
                out.append(Finding("R10", "경고", aid, tgt, "녹취록 범위를 벗어난 줄번호가 있습니다."))
            if d["speaker_id"] not in attendees:
                out.append(Finding("R12", "경고", aid, tgt, "출석 명단에 없는 사람이 발언자로 추출되었습니다."))

        # R8 날짜 / R9 후속조치 완결성
        for i, f in enumerate(a["follow_ups"], 1):
            tgt = f"{label} 후속조치 {i}: {f['task'][:24]}"
            if not f["task"] or not f["owner_dept"]:
                out.append(Finding("R9", "경고", aid, tgt, "조치 내용 또는 담당 부서가 비어 있습니다."))
            if due_is_open(f["due"]):
                out.append(Finding("R9", "경고", aid, tgt, "기한 확인 필요 — 회의에서 기한이 정해지지 않았습니다."))
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["due"]):
                try:
                    if dt.date.fromisoformat(f["due"]) < ctx.meeting_date:
                        out.append(Finding("R8", "경고", aid, tgt, f"기한 {f['due']}이 회의일보다 앞섭니다."))
                except ValueError:
                    out.append(Finding("R8", "경고", aid, tgt, f"존재하지 않는 날짜입니다: {f['due']}"))
            elif any(w in f["due"] for w in RELATIVE_WORDS):
                out.append(Finding("R8", "경고", aid, tgt, f"상대 날짜 '{f['due']}'를 날짜로 환산해 주세요."))
            if not f["source_lines"]:
                out.append(Finding("R10", "경고", aid, tgt, "원문 근거 줄번호가 없습니다."))

        # R7 정정 전 수치가 남아 있는지
        texts = " ".join([a["summary"]] + [d["content"] for d in a["discussions"]])
        for line_no, num in corrected:
            if num and num in texts:
                out.append(Finding("R7", "경고", aid, label, f"{line_no}번 줄에서 정정된 수치 '{num}'가 그대로 남아 있습니다."))
    return out


def summarize(findings: list[Finding]) -> dict:
    warn = [f for f in findings if f.level == "경고"]
    return {"warnings": len(warn), "infos": len(findings) - len(warn),
            "open_due": sum(1 for f in warn if f.rule == "R9" and "기한" in f.message)}
