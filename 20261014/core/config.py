"""설정값 모음 (FR-12: 정족수·의결 기준, 경로, 모델을 코드와 분리).

정족수·의결 기준은 교육용 가정값입니다. 실제 위원회 운영규정에 맞게
settings.json 의 값만 바꾸면 판정 로직이 함께 바뀝니다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
PROMPT_DIR = ROOT / "prompts"
TEMPLATE_DIR = ROOT / "templates"
SETTINGS_FILE = ROOT / "settings.json"

DEFAULT_FILES = {
    "members": DATA_DIR / "01_위원명단.csv",
    "meeting": DATA_DIR / "02_회의정보.csv",
    "agendas": DATA_DIR / "03_안건목록.csv",
    "transcript": DATA_DIR / "04-1_회의녹취록_발언자표시.txt",
    "transcript_anon": DATA_DIR / "04-2_회의녹취록_화자번호.txt",
    "template": DATA_DIR / "06_의사록양식.docx",
    "answer": DATA_DIR / "07-1_의사록_정답데이터.json",
    "mock": DATA_DIR / "mock_result.json",
}


@dataclass
class Settings:
    # R1 개회 정족수: 출석 의결권 위원 수 > 재적 의결권 위원 수 × quorum_ratio
    quorum_ratio: float = 0.5
    # R2 의결 요건: 찬성 수 > 표결 시점 출석 의결권 위원 수 × pass_ratio
    pass_ratio: float = 0.5
    # 사용할 Claude 모델 (환경변수 ANTHROPIC_MODEL 이 있으면 그 값이 우선)
    model: str = "claude-sonnet-5-5"
    max_tokens: int = 8000
    # 사용할 의사록 양식 템플릿 파일명 (templates/ 폴더 기준). 회사·위원회별로 교체 가능.
    template: str = "금소위_기본.docx"
    discussion_types: list[str] = field(default_factory=lambda: ["질의", "의견", "답변", "요청"])

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        env_model = os.getenv("ANTHROPIC_MODEL")
        if env_model:
            s.model = env_model
        return s

    def to_dict(self) -> dict:
        return asdict(self)


def template_path(settings: "Settings | None" = None) -> Path:
    """선택된 양식 템플릿의 경로. templates/ 에 없으면 기본 양식으로 폴백한다."""
    s = settings or Settings.load()
    p = TEMPLATE_DIR / s.template
    return p if p.exists() else DEFAULT_FILES["template"]


DECISION_CODES = {
    "보고": ["보고접수"],
    "의결": ["원안가결", "수정가결", "조건부가결", "부결", "보류"],
}
PASSED_CODES = {"원안가결", "수정가결", "조건부가결"}
DECISION_LABELS = {
    "보고접수": "보고 접수",
    "원안가결": "원안 가결",
    "수정가결": "수정 가결",
    "조건부가결": "수정 조건부 가결",
    "부결": "부결",
    "보류": "보류",
}
