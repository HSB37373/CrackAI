"""
민원 AI 보호 시스템 — FastAPI 백엔드

실행: uvicorn main:app --reload --port 8000
"""

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

import toxicity_detector as td
import complaint_classifier as cc
import response_generator as rg

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
            "history": [],           # 발화 텍스트 목록
            "logs": [],              # 분석 로그
            "ai_activated": False,
            "ai_activation_score": None,
            "started_at": datetime.now().isoformat(),
            "profanity_total": 0,
            "threat_total": 0,
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
    if analysis["matched_threats"]:
        session["threat_total"] += 1

    session["logs"].append({
        "text": req.text,
        "risk_score": analysis["risk_score"],
        "level": analysis["level"],
        "complaint_type": complaint_type,
        "timestamp": datetime.now().isoformat(),
    })

    # 위험도 60점 이상이고 아직 AI 전환 안 됐으면 자동 전환
    if analysis["risk_score"] >= 30 and not session["ai_activated"]:
        session["ai_activated"] = True
        session["ai_activation_score"] = analysis["risk_score"]

    return {
        **analysis,
        "complaint_type": complaint_type,
        "department": department,
        "total_turns": len(history),
        "profanity_total": session["profanity_total"],
        "threat_total": session["threat_total"],
        "ai_activated": session["ai_activated"],
        "warning_message": td.WARNING_MESSAGES.get(analysis["level"]),
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
    import json
    from pathlib import Path as P
    faq = json.loads((P(__file__).parent / "data" / "civil_service_faq.json").read_text(encoding="utf-8"))
    return faq


# ---------------------------------------------------------------------------
# 정적 파일 (프론트엔드)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
