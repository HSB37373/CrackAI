import json
import re
from pathlib import Path

import moderation as mod

DATA_DIR = Path(__file__).parent.parent / "data"


def _load():
    bad_words = json.loads((DATA_DIR / "bad_words.json").read_text(encoding="utf-8"))["words"]
    threat_data = json.loads((DATA_DIR / "threat_patterns.json").read_text(encoding="utf-8"))
    return bad_words, threat_data["patterns"], threat_data.get("high_threat", [])



def analyze(text: str, history: list[str]) -> dict:
    bad_words, threat_patterns, high_threat = _load()

    # ① 욕설·비속어 점수 (키워드)
    matched_bad = [w for w in bad_words if w in text]
    profanity_score = min(100, len(matched_bad) * 35)

    # 브라우저 STT가 욕설을 ***로 자동 검열한 경우 — 욕설 1개와 동일하게 처리
    if re.search(r'\*{2,}', text):
        matched_bad.append("(STT검열)")
        profanity_score = min(100, len(matched_bad) * 35)

    # ② 위협 표현 점수 (키워드)
    matched_threats = [p for p in threat_patterns if p in text]
    high = [p for p in matched_threats if p in high_threat]
    threat_score = min(100, len(matched_threats) * 28 + len(high) * 22)

    # ③ 분노 표현 점수 (규칙 기반)
    anger_score = 0
    if re.search(r"[!！]", text):
        anger_score += 15
    if re.search(r"[!！]{2,}", text):
        anger_score += 10
    if any(w in text for w in ["당장", "지금 당장", "빨리", "즉시", "바로"]):
        anger_score += 15
    if any(w in text for w in ["이따위", "이딴", "형편없", "엉터리", "개판"]):
        anger_score += 25
    if any(w in text for w in ["왜", "도대체", "대체", "어떻게 된 거야", "어떻게 된 거냐", "이게 뭐야"]):
        anger_score += 12
    if any(w in text for w in ["바꿔", "나와", "나오라고", "내보내", "담당자 바꿔", "책임자", "윗사람"]):
        anger_score += 18
    anger_score = min(100, anger_score)

    # ④ 키워드 기반 위험도 (욕설 30% → 35%로 재분배)
    keyword_score = round(
        profanity_score * 0.35
        + threat_score  * 0.40
        + anger_score   * 0.25
    )

    # ⑥ OpenAI Moderation API 결합
    mod_result = mod.moderate(text)

    if mod_result["available"]:
        # Moderation 60% + 키워드 40% 가중 평균
        risk_score = round(keyword_score * 0.4 + mod_result["mod_score"] * 0.6)
        # OpenAI가 유해로 판정하면 최소 주의(15점) 보장
        if mod_result["flagged"]:
            risk_score = max(risk_score, 15)
    else:
        risk_score = keyword_score

    return {
        "risk_score":        risk_score,
        "profanity_score":   profanity_score,
        "threat_score":      threat_score,
        "anger_score":       anger_score,
        "repetition_score":  0,
        "matched_bad_words": matched_bad,
        "matched_threats":   matched_threats,
        "level":             _level(risk_score),
        "repeat_count":      0,
        "moderation":        mod_result,
    }


def _level(score: int) -> str:
    if score < 15:
        return "normal"
    if score < 30:
        return "caution"
    if score < 55:
        return "danger"
    return "critical"


WARNING_MESSAGES = {
    "caution":  "원활한 상담을 위해 차분한 표현을 사용해 주시기 바랍니다.",
    "danger":   "폭언이 지속될 경우 담당 직원 보호를 위해 AI 상담으로 전환될 수 있습니다.",
    "critical": "폭언이 반복되어 지금부터 AI 음성 상담으로 전환합니다. 민원 내용은 계속 처리됩니다.",
}
