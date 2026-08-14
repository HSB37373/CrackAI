import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def _load():
    bad_words = json.loads((DATA_DIR / "bad_words.json").read_text(encoding="utf-8"))["words"]
    threat_data = json.loads((DATA_DIR / "threat_patterns.json").read_text(encoding="utf-8"))
    return bad_words, threat_data["patterns"]


def analyze(text: str, history: list[str]) -> dict:
    bad_words, threat_patterns = _load()

    matched_bad = [w for w in bad_words if w in text]

    # 브라우저 STT가 욕설을 ***로 자동 검열한 경우 — 욕설 1회로 간주
    if re.search(r'\*{2,}', text):
        matched_bad.append("(STT검열)")

    matched_threats = [p for p in threat_patterns if p in text]

    level = _level(matched_bad, matched_threats)

    return {
        "risk_score":        0,
        "profanity_score":   0,
        "threat_score":      0,
        "anger_score":       0,
        "repetition_score":  0,
        "matched_bad_words": matched_bad,
        "matched_threats":   matched_threats,
        "level":             level,
        "repeat_count":      0,
    }


def _level(matched_bad: list, matched_threats: list) -> str:
    if matched_bad and matched_threats:
        return "critical"
    if matched_threats:
        return "danger"
    if matched_bad:
        return "caution"
    return "normal"


WARNING_MESSAGES = {
    "caution":  "원활한 상담을 위해 차분한 표현을 사용해 주시기 바랍니다.",
    "danger":   "폭언이 지속될 경우 담당 직원 보호를 위해 AI 상담으로 전환될 수 있습니다.",
    "critical": "폭언이 반복되어 지금부터 AI 음성 상담으로 전환합니다. 민원 내용은 계속 처리됩니다.",
}
