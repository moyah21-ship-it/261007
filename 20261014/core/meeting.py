"""FR-04: 회의 개요 계산 (R1 정족수, R3 이석 반영, R13 기본 통계)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from .config import Settings
from .loader import normalize_time

WEEKDAYS = "월화수목금토일"


@dataclass
class MeetingContext:
    info: dict
    members: pd.DataFrame
    settings: Settings

    # ---- 기본 집합 ----
    @property
    def voting_ids(self) -> list[str]:
        return self.members.loc[self.members["is_voting"], "member_id"].tolist()

    @property
    def absent_ids(self) -> list[str]:
        return list(self.info["absent_ids"])

    @property
    def present_voting_at_open(self) -> list[str]:
        return [m for m in self.voting_ids if m not in self.absent_ids]

    @property
    def attendees(self) -> list[str]:
        """개회 시 출석자 전체(의결권 없는 간사 포함)."""
        return [m for m in self.members["member_id"] if m not in self.absent_ids]

    def present_voting_at(self, time: str | None) -> list[str]:
        """해당 시각에 자리에 있는 의결권 위원 (R3: 이석 시각 이후 제외)."""
        ids = self.present_voting_at_open
        if not time:
            return ids
        t = normalize_time(time)
        gone = {e["member_id"] for e in self.info["early_leave"] if normalize_time(e["time"]) <= t}
        return [m for m in ids if m not in gone]

    # ---- 표시용 ----
    def name(self, mid: str) -> str:
        hit = self.members[self.members["member_id"] == mid]
        return hit.iloc[0]["name"] if len(hit) else mid

    def display_speaker(self, mid: str | None) -> str:
        if not isinstance(mid, str) or not mid:  # None·NaN(미매핑) 처리
            return "(미확인)"
        if mid == "ALL":
            return "전체"
        hit = self.members[self.members["member_id"] == mid]
        if not len(hit):
            return mid
        role = hit.iloc[0]["role"]
        if role in ("위원장", "간사"):
            return role
        return f"{hit.iloc[0]['name']} {role}"

    @property
    def meeting_date(self) -> dt.date:
        return dt.date.fromisoformat(self.info["meeting_date"])

    def overview(self) -> dict:
        total = len(self.voting_ids)
        present = len(self.present_voting_at_open)
        threshold = total * self.settings.quorum_ratio
        start = dt.datetime.strptime(self.info["start_time"], "%H:%M")
        end = dt.datetime.strptime(self.info["end_time"], "%H:%M")
        minutes = int((end - start).total_seconds() // 60)
        leaves = [f"{self.name(e['member_id'])} 위원 {e['time']} 이석" for e in self.info["early_leave"]]
        return {
            "total": total,
            "present": present,
            "absent": len(self.absent_ids),
            "absent_names": [self.name(m) for m in self.absent_ids],
            "early_leaves": leaves,
            "attendance_rate": round(present / total * 100, 1) if total else 0.0,
            "quorum_threshold": threshold,
            "quorum_ok": present > threshold,  # R1
            "duration_min": minutes,
        }

    def date_text(self) -> str:
        d = self.meeting_date
        return f"{d.year}. {d.month}. {d.day}.({WEEKDAYS[d.weekday()]})"
