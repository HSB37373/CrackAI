import json
from pathlib import Path
from datetime import datetime, timedelta

BLACKLIST_PATH = Path(__file__).parent.parent / "data" / "blacklist.json"
EXPIRY = timedelta(days=182)  # 6개월

# 6개월 내 누적 전과 횟수별 상담원 통화 제한 시간
_BAN_HOURS = {1: 1, 2: 3}  # 1회→1시간, 2회→3시간, 3회+→24시간

def _ban_duration(recent_count: int) -> timedelta:
    return timedelta(hours=_BAN_HOURS.get(recent_count, 24))


def _load() -> dict:
    if not BLACKLIST_PATH.exists():
        return {"callers": {}}
    return json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    BLACKLIST_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse_date(date_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _recent_count(caller: dict) -> int:
    """6개월 이내 악성민원 건수만 반환."""
    cutoff = datetime.now() - EXPIRY
    return sum(
        1 for h in caller.get("history", [])
        if (d := _parse_date(h.get("date", ""))) and d > cutoff
    )


def get_caller(phone: str) -> dict | None:
    return _load()["callers"].get(phone)


def get_threshold(phone: str) -> int:
    """욕설 경고 허용 횟수. 6개월 이내 이력 기준."""
    caller = get_caller(phone)
    if not caller:
        return 3
    count = _recent_count(caller)
    if count <= 0:
        return 3
    elif count == 1:
        return 2
    elif count == 2:
        return 1
    else:  # 6개월 내 3회 이상 → 즉시 전환
        return 0


def get_recent_offense_count(phone: str) -> int:
    caller = get_caller(phone)
    return _recent_count(caller) if caller else 0


def get_ban_status(phone: str) -> dict:
    """현재 진행 중인 통화 제한 여부와 남은 시간을 반환."""
    caller = get_caller(phone)
    if not caller:
        return {"is_banned": False, "expires_at": None, "remaining_seconds": 0, "ban_hours": 0}

    now = datetime.now()
    for h in reversed(caller.get("history", [])):
        ban_str = h.get("ban_expires")
        if not ban_str:
            continue
        ban_dt = _parse_date(ban_str)
        if ban_dt and ban_dt > now:
            remaining = int((ban_dt - now).total_seconds())
            return {
                "is_banned": True,
                "expires_at": ban_dt.isoformat(),
                "remaining_seconds": remaining,
                "ban_hours": _BAN_HOURS.get(_recent_count(caller), 24),
            }
    return {"is_banned": False, "expires_at": None, "remaining_seconds": 0, "ban_hours": 0}


def record_offense(phone: str, name: str, session_id: str, max_risk: int) -> dict:
    data = _load()
    if phone not in data["callers"]:
        data["callers"][phone] = {
            "name": name,
            "phone": phone,
            "history": [],
        }
    caller = data["callers"][phone]
    caller["name"] = name
    caller["last_offense"] = datetime.now().isoformat()
    caller["history"].append({
        "date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "max_risk": max_risk,
    })
    # 새 이력 포함한 6개월 내 횟수로 패널티 시간 결정
    new_count = _recent_count(caller)
    ban_expires = datetime.now() + _ban_duration(new_count)
    caller["history"][-1]["ban_expires"] = ban_expires.strftime("%Y-%m-%dT%H:%M:%S")
    _save(data)
    return caller
