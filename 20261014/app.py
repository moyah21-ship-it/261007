"""AI 기반 금융소비자보호위원회 의사록 자동작성 PoC (Streamlit).

실행:  streamlit run app.py
※ 교육용 가상 자료 전용. 실제 회사자료·개인정보·고객정보를 넣지 마세요.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv가 없어도 환경변수로 동작
    pass

from core import load_inputs, loader
from core.compare import compare, load_answer, score
from core.config import DECISION_CODES, DECISION_LABELS, DEFAULT_FILES, OUTPUT_DIR, Settings, template_path
from core.extractor import ExtractionError, extract_mock, extract_with_claude, has_api_key
from core.render import build_context, render_docx
from core.rules import summarize, validate
from core.speakers import apply_mapping, suggest

st.set_page_config(page_title="의사록 자동작성 PoC", page_icon="📝", layout="wide")
ss = st.session_state
ss.setdefault("ver", 0)            # 추출 결과가 새로 들어올 때마다 증가 → 편집 위젯 초기화
ss.setdefault("base_result", None)  # AI(또는 모의) 원본 결과
ss.setdefault("mode_used", None)
ss.setdefault("confirmed_hash", None)
ss.setdefault("mapping", {})


def result_hash(r: dict) -> str:
    return hashlib.md5(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def parse_lines(s) -> list[int]:
    return [int(x) for x in str(s).replace(" ", "").split(",") if x.strip().isdigit()]


# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    st.header("입력 자료")
    st.caption("업로드하지 않으면 data/ 폴더의 더미데이터를 사용합니다.")
    up_members = st.file_uploader("위원명단 (01, CSV)", type=["csv"])
    up_meeting = st.file_uploader("회의정보 (02, CSV)", type=["csv"])
    up_agendas = st.file_uploader("안건목록 (03, CSV)", type=["csv"])
    tr_kind = st.radio("녹취록", ["발언자 표시형 (04-1)", "화자번호형 (04-2, 확장)"], index=0)
    up_tr = st.file_uploader("녹취록 직접 업로드 (TXT)", type=["txt"])

    st.header("분석 모드")
    key_ok = has_api_key()
    mode = st.radio("모드", ["AI (Claude API)", "모의 (정답데이터)"], index=0 if key_ok else 1,
                    help="API 키(.env의 ANTHROPIC_API_KEY)가 없으면 모의 모드로 시연합니다.")
    if mode.startswith("AI") and not key_ok:
        st.error("API 키가 없습니다. .env 파일에 ANTHROPIC_API_KEY를 넣거나 모의 모드를 선택하세요.")
    st.caption(f"API 키: {'설정됨' if key_ok else '없음'}")

    st.header("판정 기준 (가정값)")
    settings = Settings.load()
    settings.quorum_ratio = st.number_input("개회 정족수: 재적의 몇 배 초과 출석", 0.0, 1.0, settings.quorum_ratio, 0.05)
    settings.pass_ratio = st.number_input("가결: 출석의 몇 배 초과 찬성", 0.0, 1.0, settings.pass_ratio, 0.05)
    st.caption("실제 위원회 운영규정에 맞게 settings.json 값을 바꾸면 기본값이 바뀝니다.")

    if st.button("처음부터 다시", width="stretch"):
        for k in list(ss.keys()):
            del ss[k]
        st.rerun()

st.title("📝 금융소비자보호위원회 의사록 자동작성")
st.warning("교육용 PoC — 가상(더미) 자료만 사용하세요. 실제 회사자료·개인정보·고객정보는 입력 금지.", icon="⚠️")

# ------------------------------------------------------------------ 입력 불러오기
try:
    tr_src = up_tr or (DEFAULT_FILES["transcript_anon"] if tr_kind.startswith("화자") else DEFAULT_FILES["transcript"])
    inp = load_inputs(up_members, up_meeting, up_agendas, tr_src, settings)
except Exception as e:  # 파일 형식 오류 등
    st.error(f"입력 파일을 읽지 못했습니다: {e}")
    st.stop()

ctx, agendas = inp.ctx, inp.agendas
transcript = apply_mapping(inp.transcript, ss.mapping) if ss.mapping else inp.transcript
unmapped = int(transcript["speaker_id"].isna().sum())
answer = load_answer()
is_dummy_meeting = bool(answer) and answer.get("session_no") == ctx.info.get("session_no")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["① 회의 개요", "② AI 추출", "③ 규칙 검증", "④ 검토·출력", "⑤ 화자 매핑 (확장)"])
voting = ctx.voting_ids
attendee_opts = [f"{m} {ctx.display_speaker(m)}" for m in ctx.attendees] + ["ALL 전체"]


def opt_of(mid):
    return next((o for o in attendee_opts if o.split()[0] == mid), mid)


def id_of(opt):
    return str(opt).split()[0] if opt else opt


def who(mid):
    return ctx.display_speaker(mid) + (f" ({mid})" if isinstance(mid, str) and mid and mid != "ALL" else "")


# ------------------------------------------------------------------ ⑤ 화자 매핑 (먼저 계산: 녹취록에 반영)
with tab5:
    st.subheader("화자 매핑 제안")
    raw_unmapped = int(inp.transcript["speaker_id"].isna().sum())
    if raw_unmapped == 0:
        st.info("현재 녹취록은 발언자가 모두 위원명단과 매핑되어 있습니다. 사이드바에서 '화자번호형 (04-2)'을 선택하면 이 기능을 시험할 수 있습니다.")
    else:
        st.caption("발언 내용(진행 멘트, 설명 요청 직후 발언, 이석 언급, 소속 표현)과 소거법으로 제안합니다. 담당자가 확정해야 반영됩니다.")
        sug = suggest(inp.transcript, ctx, agendas)
        st.dataframe(sug.drop(columns=["member_id"]), hide_index=True, width="stretch")
        chosen = {}
        cols = st.columns(4)
        for i, r in enumerate(sug.itertuples()):
            opts = [""] + ctx.attendees
            default = ss.mapping.get(r.speaker_label, r.member_id)
            chosen[r.speaker_label] = cols[i % 4].selectbox(
                r.speaker_label, opts, index=opts.index(default) if default in opts else 0,
                format_func=lambda m: "(선택)" if not m else who(m), key=f"map_{r.speaker_label}")
        c1, c2 = st.columns([1, 3])
        if c1.button("매핑 확정", type="primary"):
            vals = [v for v in chosen.values() if v]
            if len(vals) != len(set(vals)):
                st.error("같은 위원이 두 화자에 지정되었습니다.")
            elif not all(chosen.values()):
                st.error("모든 화자를 지정해 주세요.")
            else:
                ss.mapping = chosen
                st.rerun()
        if ss.mapping:
            c2.success("매핑이 확정되어 녹취록에 반영되었습니다.")

# ------------------------------------------------------------------ ① 회의 개요
with tab1:
    ov = ctx.overview()
    st.subheader(f"{ctx.info['session_no']} 금융소비자보호위원회 · {ctx.date_text()} {ctx.info['start_time']}~{ctx.info['end_time']}")
    m = st.columns(6)
    m[0].metric("재적(의결권)", f"{ov['total']}명")
    m[1].metric("출석", f"{ov['present']}명")
    m[2].metric("불참", f"{ov['absent']}명", help=", ".join(ov["absent_names"]))
    m[3].metric("이석", f"{len(ov['early_leaves'])}명", help=", ".join(ov["early_leaves"]))
    m[4].metric("출석률", f"{ov['attendance_rate']}%")
    m[5].metric("개회 정족수", "충족" if ov["quorum_ok"] else "미충족", help=f"{ov['quorum_threshold']:g}명 초과 출석")
    if ov["early_leaves"]:
        st.caption("이석: " + ", ".join(ov["early_leaves"]) + " — 이석 이후 안건의 표결에서 제외됩니다.")
    if inp.skipped:
        st.warning(f"형식이 맞지 않아 건너뛴 줄 {len(inp.skipped)}개: " + " / ".join(inp.skipped[:3]))
    st.markdown(f"**녹취록** {len(transcript)}줄 · 매핑 실패 {unmapped}줄")
    view = transcript.copy()
    view["발언자"] = view["speaker_id"].map(lambda x: who(x) if isinstance(x, str) and x else "❌ 미매핑")
    styled = view[["line_no", "time", "speaker_label", "발언자", "utterance"]].style.apply(
        lambda r: ["background-color: #fde2e1" if r["발언자"].startswith("❌") else "" for _ in r], axis=1)
    st.dataframe(styled, hide_index=True, width="stretch", height=420)
    if unmapped:
        st.error("매핑되지 않은 발언자가 있습니다. ⑤ 화자 매핑 탭에서 확정한 뒤 AI 분석을 실행하세요.")

# ------------------------------------------------------------------ ② AI 추출 (실행 버튼)
with tab2:
    st.subheader("AI 추출")
    c1, c2 = st.columns([1, 3])
    label = "AI 분석 실행" if mode.startswith("AI") else "모의 결과 불러오기"
    run = c1.button(label, type="primary", disabled=bool(unmapped) or (mode.startswith("AI") and not key_ok))
    if mode.startswith("모의") and not is_dummy_meeting:
        c2.warning("모의 결과는 기본 더미 회의(2026년 제9차) 기준입니다. 다른 회의는 AI 모드를 사용하세요.")
    if run:
        try:
            with st.spinner("녹취록을 분석하고 있습니다… (1분 이내)"):
                if mode.startswith("AI"):
                    res = extract_with_claude(ctx, agendas, transcript, settings)
                else:
                    res = extract_mock(agendas)
            ss.base_result, ss.mode_used = res, mode
            ss.ver += 1
            ss.confirmed_hash = None
            st.rerun()
        except ExtractionError as e:
            st.error(str(e))
        except Exception as e:  # 네트워크·인증 오류 등
            st.error(f"AI 호출 중 오류가 발생했습니다: {e}. 사이드바에서 모의 모드로 전환해 시연할 수 있습니다.")

if ss.base_result is None:
    for t in (tab3, tab4):
        with t:
            st.info("② AI 추출 탭에서 분석을 먼저 실행하세요.")
    with tab2:
        st.info(f"[{label}] 버튼을 누르면 안건별 요지·발언·처리 결과·후속조치가 추출됩니다.")
    st.stop()

base = ss.base_result
v = ss.ver
meta = agendas.set_index("agenda_id")
line_text = dict(zip(transcript["line_no"], "[" + transcript["time"] + "] " + transcript["speaker_label"] + ": " + transcript["utterance"]))

# ------------------------------------------------------------------ ④ 검토·수정 (현재 결과를 만든다)
current = {"agendas": []}
with tab4:
    st.subheader("검토·수정")
    st.caption("AI 결과는 초안입니다. 표에서 직접 고친 뒤 아래에서 확정하세요. (원문 줄번호는 쉼표로 구분)")
    sub = st.tabs([f"제{int(meta.loc[a['agenda_id'], 'agenda_no'])}호" for a in base["agendas"]])
    for a, t in zip(base["agendas"], sub):
        aid = a["agenda_id"]
        row = meta.loc[aid]
        with t:
            st.markdown(f"**[{row['agenda_type']}] {row['title']}** · 제안: {row['presenter_dept']}")
            summary = st.text_area("제안설명 요지", a["summary"], key=f"sum_{aid}_{v}", height=90)
            codes = DECISION_CODES.get(row["agenda_type"], [])
            opts = codes if a["decision"] in codes or not a["decision"] else [a["decision"]] + codes
            c1, c2 = st.columns([1, 2])
            decision = c1.selectbox("처리 결과", opts, index=opts.index(a["decision"]) if a["decision"] in opts else 0,
                                    format_func=lambda c: DECISION_LABELS.get(c, c), key=f"dec_{aid}_{v}")
            condition = c2.text_input("수정·조건 내용", a.get("decision_condition", ""), key=f"cond_{aid}_{v}")
            votes = {"for": [], "against": [], "abstain": []}
            if row["agenda_type"] == "의결":
                vc = st.columns(3)
                for col, k, lab in zip(vc, ("for", "against", "abstain"), ("찬성", "반대", "기권")):
                    votes[k] = col.multiselect(lab, voting, default=[x for x in a["votes"][k] if x in voting],
                                               format_func=ctx.name, key=f"vote_{k}_{aid}_{v}")
            vote_note = st.text_input("반대 사유·부대의견", a.get("vote_note", ""), key=f"vnote_{aid}_{v}")

            st.markdown("**주요 질의 및 의견**")
            ddf = pd.DataFrame([{"발언자": opt_of(d["speaker_id"]), "유형": d["type"], "요지": d["content"],
                                 "근거 줄": ", ".join(map(str, d["source_lines"]))} for d in a["discussions"]],
                               columns=["발언자", "유형", "요지", "근거 줄"])
            ddf_e = st.data_editor(ddf, key=f"disc_{aid}_{v}", num_rows="dynamic", width="stretch", hide_index=True,
                                   column_config={
                                       "발언자": st.column_config.SelectboxColumn(options=attendee_opts, required=True, width="medium"),
                                       "유형": st.column_config.SelectboxColumn(options=settings.discussion_types, required=True, width="small"),
                                       "요지": st.column_config.TextColumn(width="large"),
                                       "근거 줄": st.column_config.TextColumn(width="small")})
            with st.expander("원문 대조 (근거 줄 펼쳐 보기)"):
                for r in ddf_e.to_dict("records"):
                    st.markdown(f"**{who(id_of(r['발언자']))} · {r['유형']}** — {r['요지']}")
                    for n in parse_lines(r["근거 줄"]):
                        st.caption(f"{n}. {line_text.get(n, '(없는 줄)')}")

            st.markdown("**후속조치**")
            fdf = pd.DataFrame([{"조치 내용": f["task"], "담당 부서": f["owner_dept"], "기한": f["due"],
                                 "비고": f.get("remark", ""), "근거 줄": ", ".join(map(str, f["source_lines"]))}
                                for f in a["follow_ups"]], columns=["조치 내용", "담당 부서", "기한", "비고", "근거 줄"])
            fdf_e = st.data_editor(fdf, key=f"fu_{aid}_{v}", num_rows="dynamic", width="stretch", hide_index=True,
                                   column_config={"조치 내용": st.column_config.TextColumn(width="large"),
                                                  "기한": st.column_config.TextColumn(help="YYYY-MM-DD 또는 미정")})
        current["agendas"].append({
            "agenda_id": aid, "summary": summary, "decision": decision, "decision_condition": condition,
            "decision_line": a.get("decision_line"), "votes": votes, "vote_note": vote_note,
            "discussions": [{"speaker_id": id_of(r["발언자"]), "type": r["유형"], "content": r["요지"] or "",
                             "source_lines": parse_lines(r["근거 줄"])} for r in ddf_e.to_dict("records") if r.get("요지")],
            "follow_ups": [{"task": r["조치 내용"] or "", "owner_dept": r["담당 부서"] or "", "due": r["기한"] or "",
                            "remark": r["비고"] or "", "source_lines": parse_lines(r["근거 줄"])}
                           for r in fdf_e.to_dict("records") if r.get("조치 내용")],
            "_missing": a.get("_missing", False),
        })

findings = validate(current, ctx, agendas, transcript, settings)
fsum = summarize(findings)
cur_hash = result_hash(current)
confirmed = ss.confirmed_hash == cur_hash

# ------------------------------------------------------------------ ② 결과 보기
with tab2:
    edited = result_hash(base) != cur_hash
    st.success(f"{ss.mode_used} 결과 · 안건 {len(base['agendas'])}건" + (" · ④에서 수정됨" if edited else ""))
    for a in current["agendas"]:
        row = meta.loc[a["agenda_id"]]
        with st.expander(f"제{int(row['agenda_no'])}호 [{row['agenda_type']}] {row['title']} → {DECISION_LABELS.get(a['decision'], a['decision'])}", expanded=True):
            st.markdown(f"**요지** {a['summary']}")
            if a["discussions"]:
                st.dataframe(pd.DataFrame([{"발언자": who(d["speaker_id"]), "유형": d["type"], "요지": d["content"],
                                            "원문": " / ".join(line_text.get(n, "") for n in d["source_lines"])}
                                           for d in a["discussions"]]), hide_index=True, width="stretch")
            if a["follow_ups"]:
                st.markdown("**후속조치**")
                st.dataframe(pd.DataFrame([{"조치": f["task"], "담당": f["owner_dept"], "기한": f["due"], "비고": f["remark"]}
                                           for f in a["follow_ups"]]), hide_index=True, width="stretch")

# ------------------------------------------------------------------ ③ 규칙 검증
with tab3:
    st.subheader("규칙 검증 (R1~R14)")
    m = st.columns(3)
    m[0].metric("경고", f"{fsum['warnings']}건")
    m[1].metric("기한 확인 필요", f"{fsum['open_due']}건")
    m[2].metric("확정 상태", "확정" if confirmed else "초안 (R14)")
    only_warn = st.toggle("경고만 보기", value=False)
    fdf_all = pd.DataFrame([f.to_dict() for f in findings])
    if only_warn:
        fdf_all = fdf_all[fdf_all["level"] == "경고"]
    fdf_all = fdf_all.rename(columns={"rule": "규칙", "level": "구분", "agenda": "안건", "target": "대상", "message": "내용"})
    st.dataframe(fdf_all.style.apply(lambda r: ["background-color: #fff3cd" if r["구분"] == "경고" else "" for _ in r], axis=1),
                 hide_index=True, width="stretch")
    st.caption("경고는 ④ 검토·출력 탭에서 고치거나, 사실관계를 확인한 뒤 확정 시 '확인함'으로 처리합니다.")

# ------------------------------------------------------------------ ④ 확정·출력·비교
with tab4:
    st.divider()
    st.subheader("확정 및 의사록 생성")
    if fsum["warnings"]:
        st.warning(f"남은 경고 {fsum['warnings']}건 — ③ 규칙 검증 탭에서 내용을 확인하세요.")
    ack = st.checkbox("남은 경고와 원문 대조를 확인했습니다.", value=confirmed, disabled=fsum["warnings"] == 0 and not confirmed)
    c1, c2, c3 = st.columns(3)
    if c1.button("확정", type="primary", disabled=bool(fsum["warnings"]) and not ack):
        ss.confirmed_hash = cur_hash
        st.rerun()
    if confirmed and c2.button("확정 취소"):
        ss.confirmed_hash = None
        st.rerun()
    st.caption("확정 전 출력물에는 상단에 '초안' 표시가 붙습니다. 확정 후 내용을 고치면 다시 초안이 됩니다.")

    context = build_context(current, ctx, agendas, transcript, confirmed)
    try:
        doc_bytes = render_docx(context, template_path(settings))
        state = "확정" if confirmed else "초안"
        fname = f"의사록_{ctx.info['session_no'].replace(' ', '')}_{state}.docx"
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / fname).write_bytes(doc_bytes)
        c3.download_button(f"의사록 다운로드 ({state})", doc_bytes, file_name=fname, type="primary" if confirmed else "secondary",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except Exception as e:
        st.error(f"의사록 생성 중 오류: {e}")

    if is_dummy_meeting:
        st.subheader("정답 예시와 비교 (FR-11)")
        cmp = compare(current, answer)
        ok, total = score(cmp)
        st.metric("일치 항목", f"{ok} / {total}")
        st.dataframe(cmp.style.apply(lambda r: ["background-color: #fde2e1" if r["일치"] == "X" else "" for _ in r], axis=1),
                     hide_index=True, width="stretch")
