"""핵심 로직 테스트: 파싱·개요·AI 추출(가짜 클라이언트)·규칙·출력·화자 매핑."""
import json
from copy import deepcopy
from types import SimpleNamespace

from core import load_inputs, loader
from core.compare import compare, load_answer, score
from core.config import DEFAULT_FILES
from core.extractor import extract_mock, extract_with_claude
from core.render import build_context, render_docx
from core.rules import validate
from core.speakers import suggest

INP = load_inputs()


def test_parse_and_overview():
    assert len(INP.transcript) == 38 and INP.transcript["speaker_id"].isna().sum() == 0
    ov = INP.ctx.overview()
    assert (ov["total"], ov["present"], ov["attendance_rate"], ov["quorum_ok"], ov["duration_min"]) == (7, 6, 85.7, True, 25)
    assert len(INP.ctx.present_voting_at("14:22:50")) == 5   # 오세린 이석 반영
    assert len(INP.ctx.present_voting_at("14:15:15")) == 6


class FakeClient:
    """첫 응답은 깨진 JSON, 두 번째는 정상 JSON을 돌려주는 가짜 Claude 클라이언트."""
    def __init__(self, good_text):
        self.calls, self.good = 0, good_text
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        text = "분석 결과입니다: {agendas: 깨짐" if self.calls == 1 else f"```json\n{self.good}\n```"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_ai_path_retries_and_parses():
    good = DEFAULT_FILES["mock"].read_text(encoding="utf-8")
    client = FakeClient(good)
    res = extract_with_claude(INP.ctx, INP.agendas, INP.transcript, INP.ctx.settings, client=client)
    assert client.calls == 2 and len(res["agendas"]) == 4
    assert score(compare(res, load_answer())) == (16, 16)


def test_rules_catch_injected_errors():
    res = extract_mock(INP.agendas)
    bad = deepcopy(res)
    bad["agendas"][1]["summary"] += " 미완료율 3.5%."                   # R7 정정 전 수치
    bad["agendas"][3]["votes"]["for"].append("M04")                     # R3 이석자 표결
    bad["agendas"][3]["discussions"][0]["speaker_id"] = "M07"           # R12 불참자 발언
    bad["agendas"][3]["discussions"][1]["source_lines"] = []            # R10 근거 누락
    bad["agendas"][2]["decision"] = "보고접수"                           # R5 유형 불일치
    bad["agendas"][3]["follow_ups"][0]["due"] = "다음 주 금요일"          # R8 상대 날짜
    rules = {f.rule for f in validate(bad, INP.ctx, INP.agendas, INP.transcript, INP.ctx.settings) if f.level == "경고"}
    assert {"R3", "R4", "R5", "R7", "R8", "R10", "R12"} <= rules, rules


def test_render_matches_answer_fields():
    res = extract_mock(INP.agendas)
    ctx = build_context(res, INP.ctx, INP.agendas, INP.transcript, confirmed=True)
    ans = load_answer()
    for k in ("meeting_datetime", "present_text", "absent_text", "quorum_text", "sign_date"):
        assert ctx[k] == ans[k], k
    assert [a["decision_text"] for a in ctx["agendas"]] == [a["decision_text"] for a in ans["agendas"]]
    assert [f["due"] for f in ctx["follow_ups"]] == [f["due"] for f in ans["follow_ups"]]
    assert render_docx(ctx)[:2] == b"PK"
    draft = build_context(res, INP.ctx, INP.agendas, INP.transcript, confirmed=False)
    assert "초안" in draft["draft_mark"]


def test_speaker_suggestion():
    anon, _ = loader.parse_transcript(DEFAULT_FILES["transcript_anon"], INP.ctx.members)
    sug = dict(zip(suggest(anon, INP.ctx, INP.agendas)["speaker_label"], suggest(anon, INP.ctx, INP.agendas)["member_id"]))
    assert sug == {"화자1": "S01", "화자2": "M01", "화자3": "M03", "화자4": "M02", "화자5": "M05", "화자6": "M04", "화자7": "M06"}
