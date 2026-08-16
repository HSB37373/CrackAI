"""
화성소통봇 전체 메뉴 크롤러

Usage:
  python scripts/crawl_hscity.py           # 전체 크롤링
  python scripts/crawl_hscity.py --resume  # 체크포인트에서 재시작
  python scripts/crawl_hscity.py --test    # 세정 메뉴만 테스트

Output (data/hscity_output/):
  nodes.json, edges.json
  hscity_chatbot.json, hscity_chatbot.csv
  hscity_rag.jsonl
"""

import argparse
import csv
import html
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

# ── 상수 ──────────────────────────────────────────────────────────────────────
BASE_URL    = "https://g.answerny.ai/chatbot/projects/hscity/iChatResponse.jsp"
SESSION_URL = "https://g.answerny.ai/chatbot/projects/hscity/iChatSessionRequest.jsp"
PAGE_URL    = "https://g.answerny.ai/chatbot/projects/hscity/chatbot_hscity.html"
PROJECT_ID = "b220ad8b9841"
SOURCE_URL = PAGE_URL

OUT_DIR          = Path(__file__).parent.parent / "data" / "hscity_output"
CHECKPOINT_NODES = OUT_DIR / "checkpoint_nodes.json"
CHECKPOINT_EDGES = OUT_DIR / "checkpoint_edges.json"

SKIP_NAMES = {"🏠처음으로", "처음으로", "콜센터 문의", "폭력·학대 피해지원"}
SKIP_PREFIXES = ("btn_처음으로", "btn_전화", "btn_콜센터")

# 세정만 확인됨. 나머지는 초기 응답에서 자동 발견하고, 실패 시 이 목록 사용
FALLBACK_ROOTS = [
    {"name": "고유가 피해지원금 안내", "query": "btn_최상위_고유가피해지원금안내_default"},
    {"name": "제주도 물 때",          "query": "btn_최상위_제주도물때_default"},
    {"name": "세정",                  "query": "btn_최상위_세정_default"},
    {"name": "교통·차량",             "query": "btn_최상위_교통차량_default"},
    {"name": "행정일반",              "query": "btn_최상위_행정일반_default"},
    {"name": "환경",                  "query": "btn_최상위_환경_default"},
    {"name": "보건·복지",             "query": "btn_최상위_보건복지_default"},
    {"name": "문화·관광",             "query": "btn_최상위_문화관광_default"},
    {"name": "정책광장",              "query": "btn_최상위_정책광장_default"},
]


# ── HTML 정제 ─────────────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    if _BS4:
        soup = BeautifulSoup(text, "html.parser")
        lines = soup.get_text("\n").splitlines()
    else:
        text = re.sub(r"<[^>]+>", " ", text)
        lines = text.splitlines()
    return "\n".join(line.strip() for line in lines if line.strip())


# ── 세션 초기화 + sessionKey 자동 획득 ───────────────────────────────────────
def init_session() -> tuple[requests.Session, str]:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
        "Referer": PAGE_URL,
        "Accept": "application/json, */*",
        "Content-Type": "application/json; charset=utf-8",
    })

    # 챗봇 페이지 접속 → JSESSIONID 쿠키 획득
    try:
        sess.get(PAGE_URL, timeout=20)
    except Exception as e:
        print(f"[SESSION] 페이지 접속 실패 (무시): {e}")

    # iChatSessionRequest.jsp POST → sessionKey 발급 (공식 방식)
    try:
        r = sess.post(SESSION_URL, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("isSuccess") and data.get("sessionKey"):
            sk = data["sessionKey"]
            print(f"[SESSION] sessionKey 발급 완료: {sk[:16]}...")
            return sess, sk
        print(f"[SESSION] 발급 실패: {data.get('errorMessage', data)}")
    except Exception as e:
        print(f"[SESSION] iChatSessionRequest 실패: {e}")

    import uuid
    sk = uuid.uuid4().hex
    print(f"[SESSION] fallback 랜덤 sessionKey: {sk[:12]}...")
    return sess, sk


# ── API 요청 ──────────────────────────────────────────────────────────────────
def api_call(sess: requests.Session, query: str, session_key: str, max_retry: int = 4) -> dict:
    params = {
        "query": query,
        "sessionKey": session_key,
        "projectId": PROJECT_ID,
        "_": int(time.time() * 1000),
    }
    for attempt in range(max_retry):
        try:
            r = sess.get(BASE_URL, params=params, timeout=20)
            r.raise_for_status()
            outer = r.json()
            if not outer.get("isSuccess", False):
                raise RuntimeError(f"API error: {outer.get('errorMessage', '')}")
            raw = outer.get("answer", "{}")
            try:
                answer = json.loads(raw)
            except json.JSONDecodeError:
                answer = {"message": raw, "cards": []}
            return {"outer": outer, "answer": answer}
        except Exception as e:
            if attempt == max_retry - 1:
                raise
            wait = 2 ** attempt
            print(f"  [RETRY {attempt+1}/{max_retry}] {e} | {wait}s 대기")
            time.sleep(wait)


# ── 버튼 파싱 ─────────────────────────────────────────────────────────────────
def extract_nav_buttons(answer: dict) -> list[dict]:
    result = []
    for cw in answer.get("cards", []):
        card = cw.get("card", {})
        buttons = card.get("buttons", {}).get("button", [])
        if isinstance(buttons, dict):
            buttons = [buttons]
        for b in buttons:
            result.append({
                "buttonname":   b.get("buttonname", "").strip(),
                "hidden_query": b.get("hidden_query", "").strip(),
                "url":          b.get("url", "").strip(),
            })
    return result


def extract_util_buttons(answer: dict) -> list[dict]:
    obj = answer.get("buttons2", {})
    if isinstance(obj, list):
        # buttons2가 이미 리스트 형태인 경우
        buttons = obj
    elif isinstance(obj, dict):
        buttons = obj.get("button", [])
    else:
        return []
    if isinstance(buttons, dict):
        buttons = [buttons]
    return [
        {
            "buttonname":   b.get("buttonname", "").strip(),
            "hidden_query": b.get("hidden_query", "").strip(),
            "url":          b.get("url", "").strip(),
        }
        for b in buttons if isinstance(b, dict)
    ]


def skip(query: str, name: str) -> bool:
    if name in SKIP_NAMES:
        return True
    return any(query.startswith(p) for p in SKIP_PREFIXES)


# ── 최상위 메뉴 자동 발견 ─────────────────────────────────────────────────────
def discover_roots(sess: requests.Session, session_key: str) -> list[dict]:
    for init_q in ("btn_처음으로", "", "hello"):
        try:
            result = api_call(sess, init_q, session_key)
            buttons = extract_nav_buttons(result["answer"])
            if buttons:
                roots = [{"name": b["buttonname"], "query": b["hidden_query"]}
                         for b in buttons if b["hidden_query"] and not skip(b["hidden_query"], b["buttonname"])]
                if roots:
                    print(f"[DISCOVER] 초기 응답에서 최상위 {len(roots)}개 메뉴 발견")
                    return roots
        except Exception:
            pass
    print("[DISCOVER] 자동 발견 실패 → 기본 시드 사용")
    return FALLBACK_ROOTS


# ── 크롤러 ────────────────────────────────────────────────────────────────────
class Crawler:
    def __init__(self, sess: requests.Session, session_key: str, resume: bool = False):
        self.sess = sess
        self.session_key = session_key
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.failed: list[str] = []

        OUT_DIR.mkdir(parents=True, exist_ok=True)

        if resume and CHECKPOINT_NODES.exists() and CHECKPOINT_EDGES.exists():
            self.nodes = json.loads(CHECKPOINT_NODES.read_text(encoding="utf-8"))
            self.edges = json.loads(CHECKPOINT_EDGES.read_text(encoding="utf-8"))
            print(f"[RESUME] 노드 {len(self.nodes)}개, 엣지 {len(self.edges)}개 복원")

    def checkpoint(self):
        CHECKPOINT_NODES.write_text(json.dumps(self.nodes, ensure_ascii=False, indent=2), encoding="utf-8")
        CHECKPOINT_EDGES.write_text(json.dumps(self.edges, ensure_ascii=False, indent=2), encoding="utf-8")

    def crawl(self, query: str, path: list[str], name: str, depth: int = 0):
        if not query or query in self.nodes:
            return

        indent = "  " * depth
        print(f"{indent}[GET] {query}")

        try:
            result = api_call(self.sess, query, self.session_key)
        except Exception as e:
            print(f"{indent}[ERROR] {e}")
            self.failed.append(query)
            return

        answer      = result["answer"]
        msg_raw     = answer.get("message", "")
        msg_clean   = clean_text(msg_raw)
        nav_buttons = extract_nav_buttons(answer)
        util_buttons= extract_util_buttons(answer)
        ext_urls    = [b["url"] for b in nav_buttons if b["url"]]

        self.nodes[query] = {
            "query":          query,
            "message_raw":    msg_raw,
            "message_clean":  msg_clean,
            "path":           path,
            "depth":          depth,
            "button_name":    name,
            "children":       nav_buttons,
            "utility_buttons":util_buttons,
            "external_urls":  ext_urls,
            "crawl_timestamp":datetime.utcnow().isoformat(),
        }

        child_count = sum(1 for b in nav_buttons if b["hidden_query"] and not skip(b["hidden_query"], b["buttonname"]))
        print(f"{indent}[OK] {name!r} | children={child_count} | msg={len(msg_clean)}자")

        for b in nav_buttons:
            if b["hidden_query"]:
                self.edges.append({
                    "parent_query": query,
                    "child_query":  b["hidden_query"],
                    "button_name":  b["buttonname"],
                    "url":          b["url"],
                })

        if len(self.nodes) % 20 == 0:
            self.checkpoint()

        for b in nav_buttons:
            cq, cn = b["hidden_query"], b["buttonname"]
            if not cq or cq in self.nodes or skip(cq, cn):
                continue
            time.sleep(random.uniform(0.2, 0.6))
            self.crawl(cq, path + [cn], cn, depth + 1)

    def crawl_all(self, roots: list[dict]):
        for root in roots:
            print(f"\n[ROOT] {root['name']} ({root['query']})")
            self.crawl(root["query"], [root["name"]], root["name"], 0)
        self.checkpoint()


# ── 저장 ─────────────────────────────────────────────────────────────────────
def save_all(nodes: dict, edges: list) -> int:
    node_list = list(nodes.values())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUT_DIR / "nodes.json").write_text(
        json.dumps(node_list, ensure_ascii=False, indent=2), encoding="utf-8")

    (OUT_DIR / "edges.json").write_text(
        json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8")

    (OUT_DIR / "hscity_chatbot.json").write_text(
        json.dumps(node_list, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV
    if node_list:
        with open(OUT_DIR / "hscity_chatbot.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "root", "path", "depth", "button_name", "query",
                "message", "child_count", "utility_buttons", "external_urls",
            ])
            w.writeheader()
            for n in node_list:
                pl = n.get("path", [])
                w.writerow({
                    "root":          pl[0] if pl else "",
                    "path":          " > ".join(pl),
                    "depth":         n["depth"],
                    "button_name":   n["button_name"],
                    "query":         n["query"],
                    "message":       n["message_clean"][:300],
                    "child_count":   len(n.get("children", [])),
                    "utility_buttons": "|".join(b["buttonname"] for b in n.get("utility_buttons", [])),
                    "external_urls": "|".join(n.get("external_urls", [])),
                })

    # JSONL (RAG)
    rag_count = 0
    with open(OUT_DIR / "hscity_rag.jsonl", "w", encoding="utf-8") as f:
        for i, n in enumerate(node_list):
            if not n.get("message_clean"):
                continue
            pl = n.get("path", [])
            doc = {
                "id":         f"hscity_{i:06d}",
                "category":   pl[0] if pl else "",
                "path":       " > ".join(pl),
                "title":      n["button_name"],
                "content":    n["message_clean"],
                "source":     "화성소통봇",
                "source_url": SOURCE_URL,
                "query":      n["query"],
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            rag_count += 1

    print(f"\n[저장 완료] {OUT_DIR}")
    print(f"  nodes / edges : {len(node_list)} / {len(edges)}")
    print(f"  hscity_rag.jsonl : {rag_count}개 문서")
    return rag_count


def print_report(nodes: dict, edges: list, failed: list):
    node_list = list(nodes.values())
    max_depth = max((n["depth"] for n in node_list), default=0)
    roots: dict[str, int] = {}
    for n in node_list:
        r = (n.get("path") or ["?"])[0]
        roots[r] = roots.get(r, 0) + 1
    has_msg = sum(1 for n in node_list if n.get("message_clean"))

    print("\n" + "=" * 52)
    print("  화성소통봇 크롤링 완료 리포트")
    print("=" * 52)
    print(f"  총 고유 query     : {len(nodes)}")
    print(f"  총 edge           : {len(edges)}")
    print(f"  message 있는 노드 : {has_msg}")
    print(f"  실패 query        : {len(failed)}")
    print(f"  최대 depth        : {max_depth}")
    print(f"\n  최상위 메뉴별 노드:")
    for r, cnt in sorted(roots.items(), key=lambda x: -x[1]):
        print(f"    {r}: {cnt}")
    print("=" * 52)


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="화성소통봇 크롤러")
    ap.add_argument("--resume",   action="store_true", help="체크포인트에서 재시작")
    ap.add_argument("--test",     action="store_true", help="세정 메뉴만 테스트")
    ap.add_argument("--category", type=str, default="", help="특정 카테고리만 크롤링 (예: 교통·차량)")
    args = ap.parse_args()

    print("=" * 52)
    print("  화성소통봇 크롤러 시작")
    print("=" * 52)

    sess, sk = init_session()

    if args.test:
        roots = [{"name": "세정", "query": "btn_최상위_세정_default"}]
        print("[TEST] 세정 메뉴만 탐색")
    elif args.category:
        matched = [r for r in FALLBACK_ROOTS if args.category in r["name"]]
        if not matched:
            print(f"[ERROR] '{args.category}' 카테고리를 찾을 수 없습니다.")
            print(f"사용 가능: {[r['name'] for r in FALLBACK_ROOTS]}")
            sys.exit(1)
        roots = matched
        print(f"[CATEGORY] '{args.category}' 메뉴만 탐색")
    else:
        roots = discover_roots(sess, sk)

    print(f"\n[대상] {len(roots)}개 최상위 메뉴:")
    for r in roots:
        print(f"  {r['name']} → {r['query']}")

    crawler = Crawler(sess, sk, resume=args.resume)
    crawler.crawl_all(roots)
    save_all(crawler.nodes, crawler.edges)
    print_report(crawler.nodes, crawler.edges, crawler.failed)


if __name__ == "__main__":
    main()
