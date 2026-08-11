"""
서울 열린데이터광장 4개 API 연동 → civil_service_faq.json 자동 생성

실행: python scripts/fetch_and_generate.py

API 구조:
  ① SearchFAQService         → 목록 109건 (SEQNO, 분류, 질문)
  ② SearchDetailsFAQService  → FAQ 상세 (QUEST + ANSWER)
  ③ SearchDetailsSeoulWorkmanualService → 업무매뉴얼 상세 (QUEST + ANSWER)
  ④ SearchFAQClassListService → 분류 코드 목록
"""

import json
import time
import xml.etree.ElementTree as ET
import urllib.request
from pathlib import Path

BASE = "http://openAPI.seoul.go.kr:8088"
OUT_PATH = Path(__file__).parent.parent / "data" / "civil_service_faq.json"

# ── API 키 (hex 원본 그대로 사용) ─────────────────────────────────────
KEY_LIST   = "4f756a6876666f7238356e62524557"   # ① 목록 조회
KEY_FAQ    = "7151504657666f7235317168557043"   # ② FAQ 상세
KEY_MANUAL = "57424c444f666f7237384a41536c6c"   # ③ 업무매뉴얼 상세
KEY_CLASS  = "456a647175666f72353179516d504f"   # ④ 분류 목록

# ── 5개 민원 카테고리 ─────────────────────────────────────────────────
CATEGORIES = {
    "불법주정차": {
        "민원명": "불법주정차 과태료 이의신청",
        "담당부서": "교통행정과",
        "연락처": "02-120",
        "처리기간": "접수 후 14일 이내",
        "필요서류": ["이의신청서", "차량등록증 사본", "증빙자료(사진 등)"],
        "안내": "불법주정차 과태료에 이의가 있으신 경우 고지서를 받은 날로부터 60일 이내에 이의신청을 하실 수 있습니다.",
        "_match": ["주차", "과태료", "주정차", "단속", "불법주차", "상습불법", "차로이탈", "수송", "교통"],
        "faq": [],
    },
    "주민등록": {
        "민원명": "주민등록등본·초본 발급",
        "담당부서": "민원여권과",
        "연락처": "02-120",
        "처리기간": "즉시 발급",
        "필요서류": ["신분증"],
        "안내": "주민등록등본과 초본은 주민센터 방문, 정부24 온라인, 무인민원발급기에서 발급받으실 수 있습니다.",
        "_match": ["주민등록", "등본", "초본", "신분증", "주민증"],
        "faq": [],
    },
    "여권": {
        "민원명": "여권 발급 신청",
        "담당부서": "민원여권과",
        "연락처": "02-120",
        "처리기간": "접수 후 3~5 근무일",
        "필요서류": ["여권 발급 신청서", "여권용 사진 1매", "신분증", "발급 수수료"],
        "안내": "여권은 주민센터 또는 구청 민원여권과에서 신청하실 수 있습니다.",
        "_match": ["여권", "passport", "출국", "해외", "비자"],
        "faq": [],
    },
    "쓰레기": {
        "민원명": "쓰레기 무단투기 신고",
        "담당부서": "환경위생과",
        "연락처": "02-120",
        "처리기간": "신고 후 5일 이내 현장 확인",
        "필요서류": ["신고서", "증빙 사진"],
        "안내": "쓰레기 무단투기는 과태료 부과 대상입니다. 사진과 함께 신고해 주시면 환경위생과에서 처리합니다.",
        "_match": ["쓰레기", "투기", "폐기물", "분리수거", "재활용", "1회용품", "환경", "녹색"],
        "faq": [],
    },
    "소음": {
        "민원명": "생활소음 민원",
        "담당부서": "환경위생과",
        "연락처": "02-120",
        "처리기간": "접수 후 7일 이내 처리",
        "필요서류": ["민원신청서"],
        "안내": "층간소음, 공사소음 등 생활소음 민원은 환경위생과 또는 층간소음이웃사이센터(1661-2642)로 신고하실 수 있습니다.",
        "_match": ["소음", "층간", "공사 소음", "시끄"],
        "faq": [],
    },
}

# ── 폴백 FAQ (API 매칭 부족 시 보충) ─────────────────────────────────
FALLBACK = {
    "불법주정차": [
        {"keywords": ["취소","이의","신청","어떻게"], "answer": "불법주정차 과태료 이의신청은 고지서를 받은 날로부터 60일 이내에 가능합니다. 이의신청서와 증빙자료를 교통행정과에 제출하시면 됩니다."},
        {"keywords": ["기간","언제","며칠"], "answer": "이의신청 기간은 과태료 고지서 수령일로부터 60일이며, 처리 기간은 접수 후 14일 이내입니다."},
        {"keywords": ["서류","준비","필요"], "answer": "필요 서류는 이의신청서, 차량등록증 사본, 증빙자료(사진 등)입니다."},
        {"keywords": ["온라인","인터넷"], "answer": "이의신청은 정부24 홈페이지 또는 교통행정과 방문 접수 모두 가능합니다."},
    ],
    "주민등록": [
        {"keywords": ["발급","어떻게","방법"], "answer": "주민등록등본은 정부24, 주민센터 방문, 무인민원발급기에서 발급받으실 수 있습니다."},
        {"keywords": ["온라인","인터넷"], "answer": "정부24(www.gov.kr)에서 공동인증서로 로그인 후 발급 가능하며 수수료는 무료입니다."},
        {"keywords": ["수수료","비용"], "answer": "주민센터 방문 시 400원, 온라인 발급 시 무료입니다."},
    ],
    "여권": [
        {"keywords": ["발급","신청","어떻게"], "answer": "여권 발급은 가까운 주민센터 또는 구청 민원여권과를 방문하여 신청하실 수 있습니다."},
        {"keywords": ["기간","얼마","며칠"], "answer": "일반여권은 접수 후 3~5 근무일, 긴급여권은 1~2 근무일 내에 발급됩니다."},
        {"keywords": ["수수료","비용"], "answer": "10년 복수여권 기준 53,000원, 5년 여권은 45,000원입니다."},
    ],
    "쓰레기": [
        {"keywords": ["신고","어떻게"], "answer": "쓰레기 무단투기는 자치구 환경위생과 또는 120다산콜센터, '서울 스마트 불편신고' 앱으로 신고하실 수 있습니다."},
        {"keywords": ["과태료","얼마"], "answer": "쓰레기 무단투기 과태료는 5만원~100만원까지 부과될 수 있습니다."},
    ],
    "소음": [
        {"keywords": ["층간소음","신고"], "answer": "층간소음은 층간소음이웃사이센터(1661-2642)에 신고하거나 자치구 환경위생과에 민원을 접수하실 수 있습니다."},
        {"keywords": ["공사","소음"], "answer": "공사장 소음은 환경위생과에 신고하시면 됩니다. 평일 오전 7시~오후 6시를 초과한 경우 즉시 조치가 이루어집니다."},
    ],
}


def fetch_xml(url: str) -> ET.Element:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return ET.fromstring(r.read().decode("utf-8"))


def row_to_dict(row: ET.Element) -> dict:
    return {c.tag: (c.text or "").strip() for c in row}


# ── ① 목록 전체 수집 ─────────────────────────────────────────────────
def fetch_list() -> list[dict]:
    print("① 목록 수집 중 (SearchFAQService)...")
    root = fetch_xml(f"{BASE}/{KEY_LIST}/xml/SearchFAQService/1/109/")
    total = root.findtext("list_total_count") or "?"
    rows = [row_to_dict(r) for r in root.findall("row")]
    print(f"   → {len(rows)}/{total}건")
    return rows


# ── ② FAQ 상세 조회 ───────────────────────────────────────────────────
def fetch_faq_detail(seqno: str) -> dict | None:
    root = fetch_xml(f"{BASE}/{KEY_FAQ}/xml/SearchDetailsFAQService/1/1/F/{seqno}/")
    rows = root.findall("row")
    return row_to_dict(rows[0]) if rows else None


# ── ③ 업무매뉴얼 상세 조회 ───────────────────────────────────────────
def fetch_manual_detail(faq_tp: str, seqno: str) -> dict | None:
    root = fetch_xml(f"{BASE}/{KEY_MANUAL}/xml/SearchDetailsSeoulWorkmanualService/1/1/{faq_tp}/{seqno}")
    rows = root.findall("row")
    return row_to_dict(rows[0]) if rows else None


# ── 카테고리 분류 ─────────────────────────────────────────────────────
def classify(text: str) -> str | None:
    for cat, info in CATEGORIES.items():
        if any(kw in text for kw in info["_match"]):
            return cat
    return None


def extract_keywords(text: str) -> list[str]:
    stop = {"은","는","이","가","을","를","의","에","도","요","어요","나요","어떻게","뭔가요","합니까"}
    tokens = [t.strip("[]()？?") for t in text.split() if len(t.strip("[]()？?")) >= 2]
    return [t for t in tokens if t not in stop][:4]


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    items = fetch_list()

    # 카테고리 관련 항목만 필터
    relevant = []
    for item in items:
        combined = item.get("QUEST","") + " " + item.get("LCODE_NAME","")
        cat = classify(combined)
        if cat:
            relevant.append((cat, item))

    print(f"\n② 카테고리 매칭: {len(relevant)}건 / {len(items)}건")

    # 상세 조회로 ANSWER 가져오기
    print("\n③ 상세 조회 중...")
    faq_tp_map: dict[str, list] = {cat: [] for cat in CATEGORIES}

    for cat, item in relevant:
        seqno  = item.get("FAQ_SEQNO","")
        faq_tp = item.get("FAQ_TP","F")
        quest  = item.get("QUEST","")

        try:
            if faq_tp == "F":
                detail = fetch_faq_detail(seqno)
            else:  # S or J
                detail = fetch_manual_detail(faq_tp, seqno)
        except Exception as e:
            print(f"   [오류] {quest[:30]}: {e}")
            detail = None

        answer = ""
        if detail:
            answer = detail.get("ANSWER","").strip()

        if answer:
            faq_tp_map[cat].append({
                "keywords": extract_keywords(quest),
                "answer": answer[:400],
            })
            print(f"   [{cat}] {quest[:40]} → 답변 {len(answer)}자")
        else:
            print(f"   [{cat}] {quest[:40]} → 답변 없음")

        time.sleep(0.1)  # API 부하 방지

    # 결과 조립
    result = {}
    for cat, info in CATEGORIES.items():
        entry = {k: v for k, v in info.items() if not k.startswith("_")}
        api_faqs   = faq_tp_map[cat]
        fallback   = FALLBACK.get(cat, [])
        entry["faq"] = api_faqs + fallback
        result[cat] = entry

    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 저장 완료: {OUT_PATH}")
    for cat, entry in result.items():
        api_cnt = len(faq_tp_map[cat])
        total   = len(entry["faq"])
        print(f"   {cat}: API {api_cnt}개 + 폴백 {total-api_cnt}개 = 총 {total}개")


if __name__ == "__main__":
    main()
