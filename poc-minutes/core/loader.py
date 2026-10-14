"""FR-01~FR-03: 기준정보 불러오기, 녹취록 파싱, 발언자 매핑."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

LINE_RE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:：]+?)\s*[:：]\s*(.*)$")
ALL_SPEAKER = "ALL"  # (전체) 발언 — 이견 없음 등


def _read_bytes(src) -> bytes:
    """경로(str/Path) 또는 업로드 파일 객체에서 bytes를 읽는다."""
    if src is None:
        raise ValueError("파일이 지정되지 않았습니다.")
    if isinstance(src, (str, Path)):
        return Path(src).read_bytes()
    if hasattr(src, "getvalue"):
        return src.getvalue()
    return src.read()


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949만 지원). "
                     "문서보안(DRM)으로 암호화된 파일인지 확인해 주세요.")


def read_csv(src) -> pd.DataFrame:
    text = _decode(_read_bytes(src))
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


def load_members(src) -> pd.DataFrame:
    df = read_csv(src)
    required = {"member_id", "name", "role", "dept", "position", "is_voting"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"위원명단에 필수 컬럼이 없습니다: {sorted(missing)}")
    if "alias" not in df.columns:
        df["alias"] = ""
    df["is_voting"] = df["is_voting"].str.upper().eq("Y")
    return df


def load_meeting(src) -> dict:
    df = read_csv(src)
    if df.empty:
        raise ValueError("회의정보가 비어 있습니다.")
    row = df.iloc[0].to_dict()
    row["absent_ids"] = [x.strip() for x in str(row.get("absent_ids", "")).split(",") if x.strip()]
    leaves = []
    for item in str(row.get("early_leave", "")).split(","):
        item = item.strip()
        if "@" in item:
            mid, t = item.split("@", 1)
            leaves.append({"member_id": mid.strip(), "time": t.strip()})
    row["early_leave"] = leaves
    return row


def load_agendas(src) -> pd.DataFrame:
    df = read_csv(src)
    df["agenda_no"] = df["agenda_no"].astype(int)
    return df.sort_values("agenda_no").reset_index(drop=True)


@dataclass
class Utterance:
    line_no: int
    time: str
    speaker_label: str
    speaker_id: str | None
    utterance: str


def normalize_time(t: str) -> str:
    parts = t.split(":")
    if len(parts) == 2:
        parts.append("00")
    return ":".join(p.zfill(2) for p in parts)


def match_speaker(label: str, members: pd.DataFrame) -> str | None:
    """발언자 표기(예: '위원 서지후', '위원장', '간사 차민서')를 member_id로 바꾼다 (R11)."""
    label = label.strip()
    if label in ("(전체)", "전체", "일동"):
        return ALL_SPEAKER
    tokens = label.replace("(", " ").replace(")", " ").split()
    # 1) 이름 일치
    for _, m in members.iterrows():
        if m["name"] and (m["name"] in tokens or m["name"] == label):
            return m["member_id"]
    # 2) 호칭(alias) 일치
    for _, m in members.iterrows():
        if m["alias"] and m["alias"] == label:
            return m["member_id"]
    # 3) 역할이 유일한 경우(위원장, 간사)
    for role in ("위원장", "간사"):
        if label == role or (role in tokens and len(tokens) == 1):
            hit = members[members["role"] == role]
            if len(hit) == 1:
                return hit.iloc[0]["member_id"]
    return None


def parse_transcript(src, members: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """녹취록을 줄 단위로 파싱. 반환: (발언 표, 형식이 맞지 않아 건너뛴 줄 목록)."""
    text = _decode(_read_bytes(src))
    rows, skipped = [], []
    n = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("※"):
            continue
        m = LINE_RE.match(line)
        if not m:
            skipped.append(line)
            continue
        n += 1
        t, label, body = m.groups()
        rows.append(Utterance(n, normalize_time(t), label.strip(), match_speaker(label, members), body.strip()).__dict__)
    df = pd.DataFrame(rows, columns=["line_no", "time", "speaker_label", "speaker_id", "utterance"])
    return df, skipped


def transcript_for_prompt(df: pd.DataFrame) -> str:
    return "\n".join(f"{r.line_no}\t[{r.time}] {r.speaker_label}({r.speaker_id or '미매핑'}): {r.utterance}"
                     for r in df.itertuples())
