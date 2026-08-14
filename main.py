"""
민원 AI 보호 시스템 — FastAPI 백엔드

실행: uvicorn main:app --reload --port 8000
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

FAQ_PATH = Path(__file__).parent / "data" / "civil_service_faq.json"

import toxicity_detector as td
import complaint_classifier as cc
import response_generator as rg
import caller_registry as cr

app = FastAPI(title="민원 AI 보호 시스템")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 인메모리 세션 저장소 (해커톤용)
sessions: dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "id": session_id,
            "history": [],
            "logs": [],
            "ai_activated": False,
            "ai_activation_score": None,
            "started_at": datetime.now().isoformat(),
            "profanity_total": 0,
            "threat_total": 0,
            "caller_name": "",
            "caller_phone": "",
            "caller_offense_count": 0,
            "profanity_warning_count": 0,
            "ai_threshold": 3,
            "offense_recorded": False,
        }
    return sessions[session_id]


# ---------------------------------------------------------------------------
# API 엔드포인트
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    text: str
    session_id: str = "default"


class RespondRequest(BaseModel):
    complaint_type: str
    question: str
    session_id: str = "default"
    use_ai: bool = False


class CallerRegisterRequest(BaseModel):
    session_id: str
    name: str
    phone: str



@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    session = get_session(req.session_id)
    history = session["history"]

    analysis = td.analyze(req.text, history)
    complaint_type = cc.classify(req.text)
    department = cc.get_department(complaint_type)

    # 세션 업데이트
    history.append(req.text)
    if analysis["matched_bad_words"]:
        session["profanity_total"] += 1
        session["profanity_warning_count"] += 1
    if analysis["matched_threats"]:
        session["threat_total"] += 1

    session["logs"].append({
        "text": req.text,
        "risk_score": analysis["risk_score"],
        "level": analysis["level"],
        "complaint_type": complaint_type,
        "timestamp": datetime.now().isoformat(),
    })

    # AI 전환 조건 — 욕설 감지 횟수 기반 (3회)
    threshold = session["ai_threshold"]
    warning_count = session["profanity_warning_count"]

    should_activate = False
    if threshold == 0 and analysis["matched_bad_words"]:
        should_activate = True  # 즉시 전환 (3회 이상 전과)
    elif "(STT검열)" in analysis.get("matched_bad_words", []):
        should_activate = True  # STT 검열(***) 감지 시 즉시 전환
    elif threshold > 0 and warning_count >= threshold:
        should_activate = True

    if should_activate and not session["ai_activated"]:
        session["ai_activated"] = True
        session["ai_activation_score"] = analysis["risk_score"]
        phone = session.get("caller_phone", "")
        if phone and not session["offense_recorded"]:
            cr.record_offense(phone, session["caller_name"], req.session_id, analysis["risk_score"])
            session["offense_recorded"] = True

    warnings_remaining = max(0, threshold - warning_count) if threshold > 0 else 0

    return {
        **analysis,
        "complaint_type": complaint_type,
        "department": department,
        "total_turns": len(history),
        "profanity_total": session["profanity_total"],
        "threat_total": session["threat_total"],
        "ai_activated": session["ai_activated"],
        "warning_message": td.WARNING_MESSAGES.get(analysis["level"]),
        "profanity_warning_count": warning_count,
        "ai_threshold": threshold,
        "warnings_remaining": warnings_remaining,
        "caller_offense_count": session["caller_offense_count"],
    }


@app.post("/caller/register")
async def register_caller(req: CallerRegisterRequest):
    session = get_session(req.session_id)
    session["caller_name"] = req.name
    session["caller_phone"] = req.phone

    recent_count = cr.get_recent_offense_count(req.phone)
    threshold = cr.get_threshold(req.phone)

    session["ai_threshold"] = threshold
    session["caller_offense_count"] = recent_count

    # AI 전환 상태이고 아직 전과 미기록이면 자동 저장
    if session.get("ai_activated") and not session.get("offense_recorded"):
        cr.record_offense(
            req.phone, req.name, req.session_id,
            session.get("ai_activation_score", 50)
        )
        session["offense_recorded"] = True
        recent_count = cr.get_recent_offense_count(req.phone)

    caller = cr.get_caller(req.phone)
    return {
        "name": req.name,
        "phone": req.phone,
        "offense_count": recent_count,
        "ai_threshold": threshold,
        "ban_status": cr.get_ban_status(req.phone),
        "history": caller.get("history", []) if caller else [],
    }


@app.get("/caller/{phone}")
async def get_caller_info(phone: str):
    caller = cr.get_caller(phone)
    if not caller:
        return {"found": False, "offense_count": 0, "ai_threshold": 3, "history": []}
    return {
        "found": True,
        "name": caller["name"],
        "phone": caller["phone"],
        "offense_count": cr.get_recent_offense_count(phone),
        "ai_threshold": cr.get_threshold(phone),
        "ban_status": cr.get_ban_status(phone),
        "last_offense": caller.get("last_offense"),
        "history": caller.get("history", []),
    }


@app.post("/respond")
async def respond(req: RespondRequest):
    session = get_session(req.session_id)
    context = rg.get_faq_context(req.complaint_type)

    if req.use_ai:
        response = rg.get_ai_response(req.complaint_type, req.question, context)
    else:
        response = rg.get_response(req.complaint_type, req.question)

    session["logs"].append({
        "type": "ai_response",
        "complaint_type": req.complaint_type,
        "response": response,
        "timestamp": datetime.now().isoformat(),
    })

    return {
        "response": response,
        "complaint_type": req.complaint_type,
        "department": cc.get_department(req.complaint_type),
    }


@app.get("/summary/{session_id}")
async def get_summary(session_id: str):
    session = get_session(session_id)
    logs = session["logs"]
    utterances = [l for l in logs if "text" in l]

    # 가장 많이 등장한 민원 종류
    types = [l.get("complaint_type", "기타") for l in utterances]
    main_type = max(set(types), key=types.count) if types else "기타"
    max_risk = max((l.get("risk_score", 0) for l in utterances), default=0)

    # AI 응답 목록
    ai_responses = [l["response"] for l in logs if l.get("type") == "ai_response"]

    return {
        "session_id": session_id,
        "started_at": session["started_at"],
        "total_turns": len(utterances),
        "main_complaint_type": main_type,
        "department": cc.get_department(main_type),
        "max_risk_score": max_risk,
        "profanity_total": session["profanity_total"],
        "threat_total": session["threat_total"],
        "ai_activated": session["ai_activated"],
        "ai_activation_score": session["ai_activation_score"],
        "ai_responses": ai_responses,
        "consultation_log": [
            {"text": l["text"], "risk_score": l.get("risk_score", 0), "timestamp": l.get("timestamp")}
            for l in utterances
        ],
    }


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"ok": True}


@app.get("/faq")
async def get_faq():
    return json.loads(FAQ_PATH.read_text(encoding="utf-8"))


class RouteRequest(BaseModel):
    text: str
    session_id: str = "default"


@app.post("/route")
async def route_call(req: RouteRequest):
    """자연어 민원 텍스트에서 라우팅 브리핑 추출."""
    brief = cc.build_routing_brief(req.text)
    return brief


# ---------------------------------------------------------------------------
# 페이지 라우트
# ---------------------------------------------------------------------------

@app.get("/chatbot")
async def chatbot_page():
    return FileResponse("static/chatbot.html")


@app.get("/admin")
async def admin_page():
    return FileResponse("static/admin.html")


@app.get("/admin/faq-stats")
async def admin_faq_stats():
    from pathlib import Path as P
    faq_path = P(__file__).parent / "data" / "civil_service_faq.json"
    faq = json.loads(faq_path.read_text(encoding="utf-8"))
    stats = []
    for cat, data in faq.items():
        stats.append({
            "category": cat,
            "민원명": data.get("민원명", ""),
            "담당부서": data.get("담당부서", ""),
            "faq_count": len(data.get("faq", [])),
            "has_안내": bool(data.get("안내")),
        })

    # 화성소통봇 JSONL 통계
    jsonl_path = P(__file__).parent / "data" / "hscity_output" / "hscity_rag.jsonl"
    jsonl_count = 0
    jsonl_categories: dict[str, int] = {}
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                jsonl_count += 1
                cat = doc.get("category", "기타")
                jsonl_categories[cat] = jsonl_categories.get(cat, 0) + 1
            except Exception:
                pass

    return {
        "stats": stats,
        "total_faq": sum(s["faq_count"] for s in stats),
        "hscity_rag_count": jsonl_count,
        "hscity_categories": jsonl_categories,
    }


@app.post("/admin/crawl")
async def admin_crawl():
    """화성소통봇 크롤러를 진짜 백그라운드로 실행 후 즉시 응답 (프록시 타임아웃 방지)."""
    import asyncio, sys
    from pathlib import Path as P
    script = str(P(__file__).parent / "scripts" / "crawl_hscity.py")
    log_path = P(__file__).parent / "data" / "hscity_output" / "crawl.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")
    await asyncio.create_subprocess_exec(
        sys.executable, script,
        stdout=log_file,
        stderr=log_file,
        cwd=str(P(__file__).parent),
    )
    return {
        "ok": True,
        "stdout": "크롤링이 백그라운드에서 시작됐습니다.\n완료까지 10분 이상 걸릴 수 있습니다.\n완료 후 '통계 재로드' 버튼을 눌러 결과를 확인하세요.",
        "stderr": "",
    }


@app.get("/admin/crawl-log")
async def admin_crawl_log():
    """진행 중인 크롤링 로그 확인."""
    from pathlib import Path as P
    log_path = P(__file__).parent / "data" / "hscity_output" / "crawl.log"
    if not log_path.exists():
        return {"log": "로그 없음"}
    return {"log": log_path.read_text(encoding="utf-8", errors="replace")[-3000:]}


@app.post("/admin/crawl-test")
async def admin_crawl_test():
    """화성소통봇 크롤러 테스트 (세정 메뉴만)."""
    import asyncio, sys
    from pathlib import Path as P
    script = str(P(__file__).parent / "scripts" / "crawl_hscity.py")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script, "--test",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(P(__file__).parent),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        return {
            "ok": proc.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "stdout": "", "stderr": "시간 초과 (120초)"}


@app.get("/admin/rag-docs")
async def admin_rag_docs(limit: int = 20):
    """수집된 RAG 문서 미리보기."""
    from pathlib import Path as P
    jsonl_path = P(__file__).parent / "data" / "hscity_output" / "hscity_rag.jsonl"
    if not jsonl_path.exists():
        return {"docs": [], "total": 0}
    docs = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            docs.append(json.loads(line))
        except Exception:
            pass
    return {"docs": docs[:limit], "total": len(docs)}


@app.post("/admin/reload")
async def admin_reload():
    return await admin_faq_stats()


@app.get("/admin/blacklist")
async def admin_blacklist():
    data = cr._load()
    callers = []
    for phone, caller in data.get("callers", {}).items():
        recent = cr.get_recent_offense_count(phone)
        ban = cr.get_ban_status(phone)
        callers.append({
            "name": caller.get("name", "미확인"),
            "phone": phone,
            "total_offenses": len(caller.get("history", [])),
            "recent_offenses": recent,
            "last_offense": caller.get("last_offense", ""),
            "is_banned": ban["is_banned"],
            "ban_expires_at": ban["expires_at"],
            "remaining_seconds": ban["remaining_seconds"],
            "ban_hours": ban["ban_hours"],
        })
    callers.sort(key=lambda x: x["last_offense"], reverse=True)
    return {"callers": callers, "total": len(callers)}


@app.delete("/admin/blacklist/{phone}")
async def admin_delete_caller(phone: str):
    data = cr._load()
    if phone in data.get("callers", {}):
        del data["callers"][phone]
        cr._save(data)
        return {"ok": True}
    return {"ok": False, "msg": "not found"}



# ---------------------------------------------------------------------------
# 정적 파일 (프론트엔드)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
