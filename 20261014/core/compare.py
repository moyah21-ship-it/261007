"""FR-11: 생성 결과를 07-1 정답데이터와 비교."""
from __future__ import annotations

import json

import pandas as pd

from .config import DEFAULT_FILES


def load_answer(path=None) -> dict | None:
    p = path or DEFAULT_FILES["answer"]
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def compare(result: dict, answer: dict) -> pd.DataFrame:
    rows = []
    ans_by_no = {a["no"]: a for a in answer["agendas"]}
    for i, a in enumerate(result["agendas"], 1):
        exp = ans_by_no.get(i)
        if not exp:
            continue
        got_votes = f"{len(a['votes']['for'])}:{len(a['votes']['against'])}:{len(a['votes']['abstain'])}"
        exp_votes = f"{len(exp['votes']['for'])}:{len(exp['votes']['against'])}:{len(exp['votes']['abstain'])}"
        exp_fu = sum(1 for f in answer["follow_ups"] if f["agenda"] == f"제{i}호")
        for item, got, want in [("처리 결과", a["decision"], exp["decision"]),
                                ("표결(찬:반:기권)", got_votes, exp_votes),
                                ("후속조치 수", len(a["follow_ups"]), exp_fu),
                                ("주요 발언 수", len(a["discussions"]), len(exp["discussions"]))]:
            rows.append({"안건": f"제{i}호", "항목": item, "생성 결과": str(got), "정답": str(want),
                         "일치": "O" if str(got) == str(want) else "X"})
    return pd.DataFrame(rows)


def score(df: pd.DataFrame) -> tuple[int, int]:
    return int((df["일치"] == "O").sum()), len(df)
