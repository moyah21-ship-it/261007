"""Streamlit 화면 동작 테스트 (모의 모드, 헤드리스)."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run_mock():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    btn = [b for b in at.button if b.label == "모의 결과 불러오기"][0]
    btn.click().run()
    assert not at.exception, at.exception
    return at


def test_mock_flow_and_confirm():
    at = run_mock()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["경고"] == "2건"
    assert metrics["일치 항목"] == "16 / 16"
    assert metrics["확정 상태"].startswith("초안")
    at.checkbox[0].check().run()
    [b for b in at.button if b.label == "확정"][0].click().run()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["확정 상태"] == "확정"


def test_edit_resets_confirmation():
    at = run_mock()
    at.checkbox[0].check().run()
    [b for b in at.button if b.label == "확정"][0].click().run()
    at.text_area[0].input("요지를 수정함.").run()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["확정 상태"].startswith("초안")


def test_anonymous_transcript_mapping():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.radio[0].set_value("화자번호형 (04-2, 확장)").run()
    assert not at.exception, at.exception
    assert any("매핑 실패 37줄" in m.value for m in at.markdown)
    [b for b in at.button if b.label == "매핑 확정"][0].click().run()
    assert not at.exception, at.exception
    assert any("매핑 실패 0줄" in m.value for m in at.markdown)
    [b for b in at.button if b.label == "모의 결과 불러오기"][0].click().run()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["일치 항목"] == "16 / 16"
