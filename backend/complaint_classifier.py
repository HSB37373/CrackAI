KEYWORDS: dict[str, list[str]] = {
    "불법주정차": ["주차", "과태료", "주정차", "단속", "딱지", "불법주차", "주차위반", "주정차위반"],
    "주민등록": ["등본", "초본", "주민등록", "주민증", "등록증", "주민등록증", "주민등록등본", "주민등록초본"],
    "여권": ["여권", "passport", "출국", "해외여행", "여권발급", "재발급"],
    "쓰레기": ["쓰레기", "무단투기", "폐기물", "분리수거", "음식물쓰레기", "쓰레기봉투", "투기"],
    "소음": ["소음", "시끄럽", "층간소음", "공사소음", "소음민원", "층간", "소리"],
}

DEPT_MAP: dict[str, str] = {
    "불법주정차": "교통행정과",
    "주민등록": "민원여권과",
    "여권": "민원여권과",
    "쓰레기": "환경위생과",
    "소음": "환경위생과",
    "기타": "민원안내실",
}


def classify(text: str) -> str:
    scores: dict[str, int] = {}
    for category, words in KEYWORDS.items():
        matched = sum(1 for w in words if w in text)
        if matched:
            scores[category] = matched
    if not scores:
        return "기타"
    return max(scores, key=lambda k: scores[k])


def get_department(category: str) -> str:
    return DEPT_MAP.get(category, "민원안내실")
