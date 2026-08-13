import re

KEYWORDS: dict[str, list[str]] = {
    "불법주정차": [
        "주차", "과태료", "주정차", "단속", "딱지", "불법주차", "주차위반", "주정차위반",
        "벌금", "주차딱지", "주차단속", "차 세워", "차를 세워", "주차비",
    ],
    "주민등록": [
        "등본", "초본", "주민등록", "주민증", "등록증", "주민등록증", "주민등록등본", "주민등록초본",
        "신분증", "신분 증명", "거주지 증명", "거주 확인",
    ],
    "여권": [
        "여권", "passport", "출국", "해외여행", "여권발급", "재발급",
        "해외", "비자", "출입국", "국제", "외국 나가",
    ],
    "쓰레기": [
        "쓰레기", "무단투기", "폐기물", "분리수거", "음식물쓰레기", "쓰레기봉투", "투기",
        "불법투기", "쓰레기 버린", "버린 사람", "재활용",
    ],
    "소음": [
        "소음", "시끄럽", "층간소음", "공사소음", "소음민원", "층간", "소리",
        "시끄러워", "소리가 너무", "윗집", "아랫집", "옆집", "공사 소리",
    ],
}

DEPT_MAP: dict[str, str] = {
    "불법주정차": "교통행정과",
    "주민등록": "민원여권과",
    "여권": "민원여권과",
    "쓰레기": "환경위생과",
    "소음": "환경위생과",
    "기타": "민원안내실",
}

SUB_TYPE_MAP: dict[str, list[tuple[str, list[str]]]] = {
    "불법주정차": [
        ("어린이보호구역 불법주정차", ["어린이", "어린이집", "학교", "스쿨존", "어린이보호"]),
        ("과태료 이의신청", ["이의", "이의신청", "취소", "부당", "억울"]),
        ("반복 불법주정차 신고", ["반복", "매일", "항상", "계속", "자꾸", "또", "밤마다"]),
        ("주차단속 요청", ["단속", "딱지", "신고"]),
        ("주차위반 과태료 문의", ["과태료", "벌금", "얼마"]),
    ],
    "쓰레기": [
        ("어린이보호구역 인근 투기", ["어린이", "어린이집", "학교"]),
        ("무단투기 신고", ["신고", "투기", "버린", "불법"]),
        ("분리수거 문의", ["분리수거", "재활용", "음식물"]),
        ("쓰레기 수거 요청", ["수거", "치워", "청소"]),
    ],
    "소음": [
        ("층간소음 민원", ["층간", "위층", "아래층", "윗집", "아랫집"]),
        ("공사장 소음 신고", ["공사", "공사장", "공사 소리"]),
        ("생활소음 민원", ["소음", "시끄럽", "소리"]),
    ],
    "주민등록": [
        ("주민등록등본 발급", ["등본"]),
        ("주민등록초본 발급", ["초본"]),
        ("전입신고", ["이사", "전입", "이사 왔"]),
        ("전출신고", ["전출", "이사 가"]),
    ],
    "여권": [
        ("여권 신규 발급", ["신규", "처음", "새로"]),
        ("여권 재발급", ["재발급", "갱신", "만료", "기간 지났", "기간이 지났"]),
        ("여권 발급 문의", ["발급", "방법", "어떻게"]),
    ],
}

# 화성시 행정구역
_LOCATIONS = [
    "동탄", "병점", "향남", "봉담", "남양", "우정", "장안", "팔탄", "마도",
    "송산", "서신", "새솔동", "반월동", "기산동", "황계동", "진안동",
    "반송동", "석우동", "청계동", "오산동", "능동", "중동", "상리동",
]

_HIGH_URGENCY = ["어린이", "어린이집", "스쿨존", "사고", "다쳤", "긴급", "화재", "폭발", "위험", "부상"]
_MED_URGENCY  = ["반복", "매일", "항상", "계속", "자꾸", "밤마다", "또"]

_SUMMARY_TEMPLATES: dict[str, str] = {
    "불법주정차": "{location}불법주정차 관련 민원이 접수됨. {urgency_str}교통행정과 조치 필요.",
    "쓰레기":     "{location}쓰레기 무단투기 민원이 접수됨. {urgency_str}환경위생과 현장 확인 필요.",
    "소음":       "{location}생활소음 민원이 접수됨. {urgency_str}환경위생과 조치 필요.",
    "주민등록":   "주민등록 관련 민원이 접수됨. 민원여권과 안내 필요.",
    "여권":       "여권 발급 관련 민원이 접수됨. 민원여권과 안내 필요.",
    "기타":       "민원 내용이 접수됨. 담당 부서 배정 필요.",
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


def get_sub_type(text: str, category: str) -> str:
    for sub_name, keywords in SUB_TYPE_MAP.get(category, []):
        if any(k in text for k in keywords):
            return sub_name
    return category + " 일반 문의"


def extract_location(text: str) -> str:
    for loc in _LOCATIONS:
        if loc in text:
            return loc
    m = re.search(r'[가-힣]+[동읍면리]', text)
    return m.group() if m else ""


def get_urgency(text: str) -> str:
    if any(w in text for w in _HIGH_URGENCY):
        return "높음"
    if any(w in text for w in _MED_URGENCY):
        return "중간"
    return "보통"


def build_routing_brief(text: str) -> dict:
    category = classify(text)
    sub_type = get_sub_type(text, category)
    location = extract_location(text)
    urgency = get_urgency(text)
    department = get_department(category)

    location_str = f"{location} " if location else ""
    urgency_str = "반복 발생 중. " if urgency == "중간" else ("고위험 상황 포함. " if urgency == "높음" else "")
    template = _SUMMARY_TEMPLATES.get(category, _SUMMARY_TEMPLATES["기타"])
    summary = template.format(location=location_str, urgency_str=urgency_str)

    return {
        "complaint_type": category,
        "sub_type": sub_type,
        "location": location,
        "urgency": urgency,
        "department": department,
        "summary": summary,
    }
