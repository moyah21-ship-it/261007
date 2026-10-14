"""의사록 자동작성 PoC 핵심 로직."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import loader
from .config import DEFAULT_FILES, Settings
from .meeting import MeetingContext


@dataclass
class Inputs:
    ctx: MeetingContext
    agendas: pd.DataFrame
    transcript: pd.DataFrame
    skipped: list[str]


def load_inputs(members=None, meeting=None, agendas=None, transcript=None, settings: Settings | None = None) -> Inputs:
    settings = settings or Settings.load()
    mem = loader.load_members(members or DEFAULT_FILES["members"])
    info = loader.load_meeting(meeting or DEFAULT_FILES["meeting"])
    ag = loader.load_agendas(agendas or DEFAULT_FILES["agendas"])
    tr, skipped = loader.parse_transcript(transcript or DEFAULT_FILES["transcript"], mem)
    return Inputs(MeetingContext(info, mem, settings), ag, tr, skipped)
