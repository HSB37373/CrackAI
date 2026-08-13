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
            "ai_threshold": 2,
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

    # AI 전환 조건 — 욕설 경고 횟수 기반
    threshold = session["ai_threshold"]
    warning_count = session["profanity_warning_count"]

    should_activate = False
    if threshold == 0 and analysis["matched_bad_words"]:
        should_activate = True  # 즉시 전환 (3회 이상 전과)
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
    return {
        "stats": stats,
        "total_faq": sum(s["faq_count"] for s in stats),
        "raw_api_exists": False,
        "raw_api_total": 0,
    }


@app.post("/admin/fetch")
async def admin_fetch():
    """서울 열린데이터광장 4개 API 수집 + FAQ 자동 생성."""
    import subprocess, sys
    from pathlib import Path as P
    script = str(P(__file__).parent / "scripts" / "fetch_and_generate.py")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, timeout=120,
        cwd=str(P(__file__).parent),
    )
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


@app.post("/admin/reload")
async def admin_reload():
    return await admin_faq_stats()



# ---------------------------------------------------------------------------
# 정적 파일 (프론트엔드)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
