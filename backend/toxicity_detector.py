import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def _load():
    bad_words = json.loads((DATA_DIR / "bad_words.json").read_text(encoding="utf-8"))["words"]
    threat_data = json.loads((DATA_DIR / "threat_patterns.json").read_text(encoding="utf-8"))
    return bad_words, threat_data["patterns"], threat_data.get("high_threat", [])


def _is_similar(a: str, b: str) -> bool:
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return False
    return len(wa & wb) / max(len(wa), len(wb)) > 0.4


def analyze(text: str, history: list[str]) -> dict:
    bad_words, threat_patterns, high_threat = _load()

    # ① 욕설·비속어 점수
    matched_bad = [w for w in bad_words if w in text]
    profanity_score = min(100, len(matched_bad) * 35)

    # ② 위협 표현 점수
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
    if any(w in text for w in ["바꿔", "나와", "나오라고", "내보내"]):
        anger_score += 18
    anger_score = min(100, anger_score)

    # ④ 반복 발화 점수
    recent = history[-6:] if history else []
    repeat_count = sum(1 for h in recent if _is_similar(h, text))
    repetition_score = min(100, repeat_count * 22)

    # 최종 위험도
    risk_score = round(
        profanity_score * 0.30
        + threat_score * 0.35
        + anger_score * 0.20
        + repetition_score * 0.15
    )

    return {
        "risk_score": risk_score,
        "profanity_score": profanity_score,
        "threat_score": threat_score,
        "anger_score": anger_score,
        "repetition_score": repetition_score,
        "matched_bad_words": matched_bad,
        "matched_threats": matched_threats,
        "level": _level(risk_score),
        "repeat_count": repeat_count,
    }


def _level(score: int) -> str:
    if score < 15:
        return "normal"
    if score < 30:
        return "caution"
    if score < 55:
        return "danger"
    return "critical"


# 단계별 안내 메시지
WARNING_MESSAGES = {
    "caution": "원활한 상담을 위해 차분한 표현을 사용해 주시기 바랍니다.",
    "danger": "폭언이 지속될 경우 담당 직원 보호를 위해 AI 상담으로 전환될 수 있습니다.",
    "critical": "폭언이 반복되어 지금부터 AI 음성 상담으로 전환합니다. 민원 내용은 계속 처리됩니다.",
}
