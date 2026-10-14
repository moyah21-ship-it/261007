#!/usr/bin/env python3
"""의사록 자동작성 end-to-end 파이프라인 (헤드리스 CLI).

Streamlit 화면 없이 녹취 → AI 추출(또는 모의) → 규칙검증(R1~R14) → 의사록 .docx 생성까지
한 번에 실행한다. 데모·CI·배치 생성용이며, 결과물은 output/ 에 저장된다.

사용:
    python generate.py                 # 기본 더미 회의, 모의 모드(키 없으면 자동)
    python generate.py --ai            # ANTHROPIC_API_KEY 가 있으면 Claude 추출
    python generate.py --template 하나생명_제8차형.docx

산출물:
    output/의사록_<차수>_초안.docx      # 담당자 확정 전 (R14: '초안' 표시)
    output/의사록_<차수>_확정.docx      # 담당자 확정 후 (최종본)

휴먼-인-더-루프 원칙(Q5): '확정' 산출물은 담당자가 내용을 검토·수정·확정했다는
가정하에 생성되는 것이며, 자동 생성 자체가 확정을 의미하지 않는다. 실제 운영에서는
Streamlit 화면의 [담당자 확정] 단계를 거쳐야 한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core import load_inputs
from core.config import OUTPUT_DIR, Settings, template_path
from core.extractor import ExtractionError, extract_mock, extract_with_claude, has_api_key
from core.render import build_context, render_docx
from core.rules import summarize, validate


def run(use_ai: bool, template: str | None, out_dir: Path) -> int:
    settings = Settings.load()
    if template:
        settings.template = template

    # 1) 입력 로드 (위원명단·회의정보·안건·녹취록 파싱)
    inp = load_inputs(settings=settings)
    ctx, agendas, transcript = inp.ctx, inp.agendas, inp.transcript
    if inp.skipped:
        print(f"⚠ 녹취록 매핑 실패 {len(inp.skipped)}줄: {', '.join(inp.skipped[:5])}"
              + (" ..." if len(inp.skipped) > 5 else ""))

    # 2) AI 추출 (키가 있고 --ai 이면 Claude, 아니면 모의 결과)
    if use_ai and has_api_key():
        print(f"● AI 추출: Claude ({settings.model})")
        try:
            result = extract_with_claude(ctx, agendas, transcript, settings)
        except ExtractionError as e:
            print(f"✗ AI 추출 실패: {e}\n  → 모의 결과로 폴백합니다.")
            result = extract_mock(agendas)
    else:
        if use_ai:
            print("● ANTHROPIC_API_KEY 가 없어 모의(mock) 모드로 실행합니다.")
        else:
            print("● 모의(mock) 모드")
        result = extract_mock(agendas)

    # 3) 업무규칙 검증 (R1~R14)
    findings = validate(result, ctx, agendas, transcript, settings)
    s = summarize(findings)
    print(f"● 규칙검증: 경고 {s['warnings']}건, 정보 {s['infos']}건, 기한 미정 후속조치 {s['open_due']}건")
    for f in findings:
        if f.level == "경고":
            print(f"   ⚠ [{f.rule}] {f.target}: {f.message}")

    # 4) 의사록 .docx 생성 (초안 + 확정)
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = template_path(settings)
    print(f"● 템플릿: {tpl.name}")
    session = result and ctx.info["session_no"]
    draft_ctx = build_context(result, ctx, agendas, transcript, confirmed=False)
    final_ctx = build_context(result, ctx, agendas, transcript, confirmed=True)
    draft_path = out_dir / f"의사록_{session}_초안.docx"
    final_path = out_dir / f"의사록_{session}_확정.docx"
    draft_path.write_bytes(render_docx(draft_ctx, tpl))
    final_path.write_bytes(render_docx(final_ctx, tpl))
    print(f"✓ 생성 완료:\n   - {draft_path}\n   - {final_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="의사록 자동작성 end-to-end 파이프라인")
    ap.add_argument("--ai", action="store_true", help="ANTHROPIC_API_KEY 가 있으면 Claude 로 추출")
    ap.add_argument("--template", default=None, help="사용할 템플릿 파일명 (templates/ 기준)")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 output/)")
    args = ap.parse_args(argv)
    out_dir = Path(args.out) if args.out else OUTPUT_DIR
    return run(args.ai, args.template, out_dir)


if __name__ == "__main__":
    sys.exit(main())
