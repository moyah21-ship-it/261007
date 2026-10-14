"""07-1 정답데이터(의사록 양식용)를 AI 추출 스키마(mock_result.json)로 변환하는 1회성 도구."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
ans = json.loads((ROOT / "data/07-1_의사록_정답데이터.json").read_text(encoding="utf-8"))
decision_line = {1: 11, 2: 17, 3: 25, 4: 37}
condition = {3: "제12조 판매 모니터링 주기를 '월 단위 표본 점검'으로 수정하여 시행함."}
vote_note = {4: "반대 사유(배하람 위원): 고령자용 핵심설명서 미마련. 부대의견: 상품본부는 고령자용 핵심설명서를 2026. 12. 15.까지 마련하여 소비자보호부의 확인을 받을 것."}
out = {"_note": "교육용 모의(mock) 결과 — 07-1 정답데이터 기준. API 키가 없을 때 AI 추출 대신 사용됩니다.", "agendas": []}
for a in ans["agendas"]:
    no = a["no"]
    fus = [{"task": f["task"], "owner_dept": f["owner"], "due": f["due"], "remark": "" if f["remark"] == "기한 확인 필요" else f["remark"],
            "source_lines": f["source_lines"]} for f in ans["follow_ups"] if f["agenda"] == f"제{no}호"]
    out["agendas"].append({
        "agenda_id": f"AG-0{no}", "summary": a["summary"],
        "discussions": [{k: d[k] for k in ("speaker_id", "type", "content", "source_lines")} for d in a["discussions"]],
        "decision": a["decision"], "decision_condition": condition.get(no, ""), "decision_line": decision_line[no],
        "votes": a["votes"], "vote_note": vote_note.get(no, ""), "follow_ups": fus})
(ROOT / "data/mock_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok", sum(len(a["follow_ups"]) for a in out["agendas"]), "follow-ups")
