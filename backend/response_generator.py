import json
import os
import re
from pathlib import Path

FAQ_PATH = Path(__file__).parent.parent / "data" / "civil_service_faq.json"
RAG_PATH = Path(__file__).parent.parent / "data" / "hscity_output" / "hscity_rag.jsonl"

# ── RAG 문서 로드 (한 번만) ───────────────────────────────────────────────────
_rag_docs: list[dict] = []

def _load_rag() -> list[dict]:
    global _rag_docs
    if _rag_docs:
        return _rag_docs
    if not RAG_PATH.exists():
        return []
    docs = []
    for line in RAG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                docs.append(json.loads(line))
            except Exception:
                pass
    _rag_docs = docs
    return docs


def _load_faq() -> dict:
    return json.loads(FAQ_PATH.read_text(encoding="utf-8"))


# ── RAG 검색 (키워드 기반) ────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    """공백·특수문자 제거해서 한국어 비교 편의 확보."""
    return re.sub(r"[\s ·>]", "", text)


_PARTICLES = ("이에요", "예요", "이에요", "이어요", "이야", "이랑", "에서",
              "에게", "으로", "이랑", "부터", "까지", "이나", "나요", "어요",
              "이요", "가요", "이가", "이를", "이은", "이는", "하고", "하는",
              "가", "이", "을", "를", "은", "는", "의", "에", "도", "만", "로")


def _strip_particle(word: str) -> str:
    """한국어 조사/어미를 뒤에서 제거."""
    for p in sorted(_PARTICLES, key=len, reverse=True):
        if word.endswith(p) and len(word) - len(p) >= 2:
            return word[: -len(p)]
    return word


def _extract_tokens(question: str) -> list[str]:
    stopwords = {
        "이", "가", "을", "를", "은", "는", "의", "에", "도", "요",
        "어요", "나요", "합니다", "어떻게", "하고", "싶다", "싶어요",
        "해주세요", "알려주세요", "좀", "제가", "저는", "어디서",
        "어디에", "했는데", "있나요", "있어요", "하는데", "하면", "해서",
        "인데요", "인데", "좀요", "뭐예요", "뭔가요", "뭐죠", "해줘",
        "거예요", "싶은데", "알고싶어요", "알고싶어",
    }
    raw = re.split(r"[\s,\.!?]", question)
    tokens = []
    for t in raw:
        if len(t) < 2 or t in stopwords:
            continue
        stripped = _strip_particle(t)
        tokens.append(stripped if len(stripped) >= 2 else t)
    return tokens


# complaint_type → 화성소통봇 카테고리 힌트
_CATEGORY_HINT: dict[str, list[str]] = {
    "불법주정차": ["교통·차량", "교통차량"],
    "주민등록":   ["행정일반"],
    "여권":       ["행정일반"],
    "쓰레기":     ["환경"],
    "소음":       ["환경", "행정일반"],
}


def _search_rag(question: str, top_k: int = 3, complaint_type: str = "") -> list[dict]:
    docs = _load_rag()
    if not docs:
        return []

    tokens = _extract_tokens(question)
    q_norm = _normalize(question)

    if not tokens and not q_norm:
        return []

    # 카테고리 힌트: complaint_type이 있으면 해당 카테고리 문서를 우선
    hint_cats = _CATEGORY_HINT.get(complaint_type, [])

    # 긴 토큰은 3~4자 서브스트링으로도 쪼개서 추가 검색
    expanded_tokens = list(tokens)
    for t in tokens:
        if len(t) >= 5:
            for size in (4, 3):
                for i in range(len(t) - size + 1):
                    sub = t[i:i+size]
                    if sub not in expanded_tokens:
                        expanded_tokens.append(sub)

    scored = []
    for doc in docs:
        path    = doc.get("path", "")
        title   = doc.get("title", "")
        content = doc.get("content", "")[:400]
        cat     = doc.get("category", "")

        path_norm    = _normalize(path)
        title_norm   = _normalize(title)
        content_norm = _normalize(content)

        score = 0

        # 카테고리 힌트 부스트
        if hint_cats and any(_normalize(h) in _normalize(cat) for h in hint_cats):
            score += 4

        for t in expanded_tokens:
            t_norm = _normalize(t)
            if not t_norm or len(t_norm) < 2:
                continue
            weight = 1 if len(t) <= 4 else 1   # 서브스트링은 가중치 낮게
            if t_norm in path_norm:
                score += 3 * weight
            elif t_norm in title_norm:
                score += 2 * weight
            elif t_norm in content_norm:
                score += 1 * weight

        # 질문 전체 vs 경로
        if len(q_norm) >= 4 and (q_norm in path_norm or path_norm in q_norm):
            score += 5

        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: -x[0])
    # 카테고리 힌트 없이 점수가 너무 낮으면 제외 (관련 없는 문서 방지)
    min_score = 3 if not hint_cats else 2
    return [d for s, d in scored[:top_k] if s >= min_score]


def _format_rag_answer(docs: list[dict]) -> str:
    """RAG 문서를 음성 친화적 답변으로 변환."""
    if not docs:
        return ""
    best = docs[0]
    content = best.get("content", "").strip()
    if not content:
        return ""

    # 이모지, 특수문자 정리 (음성 TTS에 적합하게)
    content = re.sub(r"[🔹💡👉🏠📌✅❌🙂]", "", content)
    content = re.sub(r"┗|┃|┏|┓|┗|┛", "", content)
    content = re.sub(r"\n{2,}", "\n", content).strip()

    path = best.get("path", "")
    category = best.get("category", "")

    lines = [f"{path} 안내입니다." if path else ""]
    lines.append(content[:400])
    return "\n".join(l for l in lines if l).strip()


# ── 공개 API ──────────────────────────────────────────────────────────────────
def get_response(complaint_type: str, question: str) -> str:
    """RAG 검색 → FAQ 폴백 순서로 답변 반환."""
    # 1순위: 화성소통봇 RAG 검색 (complaint_type 힌트 활용)
    rag_results = _search_rag(question, complaint_type=complaint_type)
    if rag_results:
        answer = _format_rag_answer(rag_results)
        if answer:
            return answer

    # 2순위: 기존 civil_service_faq.json
    faq = _load_faq()
    if complaint_type in faq:
        info = faq[complaint_type]
        for item in info.get("faq", []):
            if any(kw in question for kw in item.get("keywords", [])):
                return item["answer"]
        return _build_info_response(info)

    return _general_response(question)


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
    """ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 있으면 LLM으로 답변, 없으면 RAG 사용."""
    # OpenAI 우선
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            system = (
                "당신은 화성시 공공기관 민원 AI 상담원입니다. "
                "반드시 아래 행정정보만을 근거로 답변하세요. "
                "모르는 내용은 '담당 부서에 문의해 주세요'라고 안내하세요. "
                "답변은 공식적이고 친절하며 2~3문장 이내로 작성하세요."
            )
            user = f"행정정보:\n{context}\n\n민원 종류: {complaint_type}\n민원인 질문: {question}"
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=300,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content
        except Exception:
            pass

    # Claude (Anthropic)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            system = (
                "당신은 화성시 공공기관 민원 AI 상담원입니다. "
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
            pass

    # API 키 없음 → RAG 직접 사용
    return get_response(complaint_type, question)


def get_faq_context(complaint_type: str) -> str:
    """LLM에 넘길 컨텍스트: RAG 검색 결과 + FAQ."""
    # RAG에서 관련 문서 가져오기
    rag_docs = _search_rag(complaint_type, top_k=5, complaint_type=complaint_type)
    rag_context = "\n".join(
        f"[{d.get('path','')}]\n{d.get('content','')[:300]}"
        for d in rag_docs
    )

    # 기존 FAQ 컨텍스트
    faq = _load_faq()
    faq_lines = []
    if complaint_type in faq:
        info = faq[complaint_type]
        faq_lines = [
            f"민원명: {info.get('민원명', '')}",
            f"담당부서: {info.get('담당부서', '')}",
            f"연락처: {info.get('연락처', '')}",
            f"처리기간: {info.get('처리기간', '')}",
            f"필요서류: {', '.join(info.get('필요서류', []))}",
            f"안내: {info.get('안내', '')}",
        ]
        if info.get("응대기준"):
            faq_lines.append(f"응대기준: {info['응대기준']}")
        for item in info.get("faq", []):
            faq_lines.append(f"Q: {item.get('keywords', [])} → {item.get('answer', '')}")

    parts = []
    if rag_context:
        parts.append(f"=== 화성소통봇 행정정보 ===\n{rag_context}")
    if faq_lines:
        parts.append(f"=== FAQ ===\n" + "\n".join(faq_lines))
    return "\n\n".join(parts)
