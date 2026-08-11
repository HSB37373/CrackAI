import json
import os
from pathlib import Path

FAQ_PATH = Path(__file__).parent.parent / "data" / "civil_service_faq.json"


def _load_faq() -> dict:
    return json.loads(FAQ_PATH.read_text(encoding="utf-8"))


def get_response(complaint_type: str, question: str) -> str:
    """등록된 FAQ에서 답변을 찾아 반환한다."""
    faq = _load_faq()

    if complaint_type not in faq:
        return _general_response(question)

    info = faq[complaint_type]
    q = question

    # 키워드 매칭으로 FAQ 답변 탐색
    for item in info.get("faq", []):
        if any(kw in q for kw in item.get("keywords", [])):
            return item["answer"]

    # 매칭 없으면 기본 안내
    return _build_info_response(info)


def _build_info_response(info: dict) -> str:
    parts: list[str] = []
    if info.get("안내"):
        parts.append(info["안내"])
    if info.get("담당부서"):
        parts.append(f"담당 부서는 {info['담당부서']}입니다.")
    if info.get("처리기간"):
        parts.append(f"처리 기간은 {info['처리기간']}입니다.")
    if info.get("필요서류"):
        docs = ", ".join(info["필요서류"])
        parts.append(f"필요 서류는 {docs}입니다.")
    return " ".join(parts) if parts else _general_response("")


def _general_response(question: str) -> str:
    return "네, 말씀해 주세요."


def get_ai_response(complaint_type: str, question: str, context: str) -> str:
    """ANTHROPIC_API_KEY 환경변수가 있으면 Claude로 답변 생성, 없으면 FAQ 사용."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return get_response(complaint_type, question)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        system = (
            "당신은 공공기관 민원 AI 상담원입니다. "
            "반드시 아래 행정정보만을 근거로 답변하세요. "
            "모르는 내용은 '담당 부서에 문의해 주세요'라고 안내하세요. "
            "답변은 공식적이고 친절하며 2~3문장 이내로 작성하세요."
        )
        user = f"행정정보:\n{context}\n\n민원 종류: {complaint_type}\n민원인 질문: {question}"
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text
    except Exception:
        return get_response(complaint_type, question)


def get_faq_context(complaint_type: str) -> str:
    faq = _load_faq()
    if complaint_type not in faq:
        return ""
    info = faq[complaint_type]
    lines = [
        f"민원명: {info.get('민원명', '')}",
        f"담당부서: {info.get('담당부서', '')}",
        f"처리기간: {info.get('처리기간', '')}",
        f"필요서류: {', '.join(info.get('필요서류', []))}",
        f"안내: {info.get('안내', '')}",
    ]
    for item in info.get("faq", []):
        lines.append(f"Q: {item.get('keywords', [])} → {item.get('answer', '')}")
    return "\n".join(lines)
