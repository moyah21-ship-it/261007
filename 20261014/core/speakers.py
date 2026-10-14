"""FR-13 (확장): '화자1, 화자2'로만 된 녹취록의 화자를 위원명단에 매핑 제안.

발언 맥락 단서로 점수를 매기고, 남는 화자는 소거법으로 채운다.
제안일 뿐이며 담당자가 화면에서 확정해야 한다.
"""
from __future__ import annotations

import re
from collections import defaultdict

import pandas as pd

from .loader import ALL_SPEAKER
from .meeting import MeetingContext

CHAIR_CUES = ("설명해 주십시오", "보고해 주십시오", "표결하겠습니다", "가결되었습니다", "보고 접수",
              "마치겠습니다", "이견 있으신", "다음은 제")
SECRETARY_CUES = ("시작하겠습니다", "보고드립니다", "전달하겠습니다", "정족수는 계속 충족")


def suggest(transcript: pd.DataFrame, ctx: MeetingContext, agendas: pd.DataFrame) -> pd.DataFrame:
    labels = [l for l in dict.fromkeys(transcript["speaker_label"]) if l not in ("(전체)", "전체")]
    lines = transcript.to_dict("records")
    members = ctx.members.set_index("member_id")
    chair, secretary = ctx.info["chair_id"], ctx.info["secretary_id"]
    score: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    why: dict[tuple[str, str], list[str]] = defaultdict(list)

    def add(label, mid, pts, reason):
        score[label][mid] += pts
        if reason not in why[(label, mid)]:
            why[(label, mid)].append(reason)

    dept_to_member = {r.dept: r.member_id for r in ctx.members.itertuples()}
    for i, r in enumerate(lines):
        lab, text = r["speaker_label"], r["utterance"]
        if lab not in labels:
            continue
        c = sum(cue in text for cue in CHAIR_CUES)
        if c:
            add(lab, chair, 2 * c, "회의 진행·표결 선언 발언")
        s = sum(cue in text for cue in SECRETARY_CUES)
        if s:
            add(lab, secretary, 3 * s, "개회 보고·전달 등 간사 역할 발언")
        # 제안부서 호명 직후 첫 발언자 = 그 부서 설명자
        m = re.search(r"(\S+?)에서 (설명|보고)해 주십시오", text)
        if m and i + 1 < len(lines):
            dept = m.group(1)
            nxt = lines[i + 1]["speaker_label"]
            mid = dept_to_member.get(dept)
            if mid is None:  # 안건목록의 제안부서 → presenter_id
                hit = agendas[agendas["presenter_dept"] == dept]
                mid = hit.iloc[0]["presenter_id"] if len(hit) else None
            if mid and nxt in labels:
                add(nxt, mid, 4, f"'{dept}' 설명 요청 직후 첫 발언")
        # 이석 선언 → 다음 발언에서 이름이 불림
        if "이석하겠습니다" in text:
            for j in range(i + 1, min(i + 3, len(lines))):
                for mm in ctx.members.itertuples():
                    if f"{mm.name} 위원 이석" in lines[j]["utterance"]:
                        add(lab, mm.member_id, 5, f"이석 선언 후 '{mm.name} 위원 이석' 언급")
        # 소속 단서 (저희 쪽 / ~ 차원에서)
        for mm in ctx.members.itertuples():
            core = mm.dept.replace("본부", "").replace("팀", "")
            keys = {core, core.replace("사업", "")} - {""}
            for k in keys:
                if f"{k} 차원" in text or (k in text and "저희" in text):
                    add(lab, mm.member_id, 3, f"'{k}' 소속을 드러내는 표현")

    # 탐욕 배정: 점수 높은 (화자, 위원) 쌍부터
    pairs = sorted(((sc, lab, mid) for lab in score for mid, sc in score[lab].items()), reverse=True)
    assigned: dict[str, str] = {}
    used: set[str] = set()
    for sc, lab, mid in pairs:
        if lab in assigned or mid in used or mid in ctx.absent_ids:
            continue
        assigned[lab] = mid
        used.add(mid)
    # 소거법: 남은 화자 1명 ↔ 남은 출석자 1명
    left_labels = [l for l in labels if l not in assigned]
    left_members = [m for m in ctx.attendees if m not in used and m != ALL_SPEAKER]
    if len(left_labels) == 1 and len(left_members) == 1:
        assigned[left_labels[0]] = left_members[0]
        why[(left_labels[0], left_members[0])].append("소거법(남은 출석자 1명)")

    rows = []
    for lab in labels:
        mid = assigned.get(lab)
        cnt = int((transcript["speaker_label"] == lab).sum())
        rows.append({"speaker_label": lab, "발언 수": cnt,
                     "제안 위원": f"{members.loc[mid, 'name']} ({mid})" if mid else "",
                     "member_id": mid or "",
                     "근거": "; ".join(why.get((lab, mid), [])) if mid else "단서 부족 — 직접 지정",
                     "신뢰도": "높음" if mid and score[lab].get(mid, 0) >= 4 else ("보통" if mid else "낮음")})
    return pd.DataFrame(rows)


def apply_mapping(transcript: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    df = transcript.copy()
    df["speaker_id"] = df.apply(lambda r: mapping.get(r["speaker_label"]) or r["speaker_id"], axis=1)
    return df
