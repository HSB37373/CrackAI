"""
OpenAI Moderation API 연동 모듈

- 모델: omni-moderation-latest (무료)
- 환경변수 OPENAI_API_KEY 설정 시 활성화
- 키 없으면 자동으로 비활성화 (키워드 방식 단독 동작)

추후 GPT 기반 문맥 판별 추가 시 이 파일에 gpt_moderate() 함수 추가
"""

import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.openai.com/v1/moderations"


def is_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", ""))


def moderate(text: str) -> dict:
    """
    OpenAI Moderation API 호출.
    반환값:
        available     : API 사용 가능 여부
        harassment    : 일반 괴롭힘 점수 (0~100)
        threatening   : 위협성 점수 (0~100)
        mod_score     : 최종 조합 점수 (0~100)
        flagged       : OpenAI가 유해로 판정했는지 여부
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _empty(reason="no_api_key")

    try:
        payload = json.dumps({
            "model": "omni-moderation-latest",
            "input": text,
        }).encode("utf-8")

        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))

        scores = data["results"][0]["category_scores"]
        flagged = data["results"][0]["flagged"]

        harassment   = scores.get("harassment", 0)
        threatening  = scores.get("harassment/threatening", 0)

        # 기존 가중치와 동일한 비율로 점수 환산 (harassment→욕설 30%, threatening→위협 35%)
        mod_score = min(100, round(harassment * 30 + threatening * 35))

        return {
            "available":   True,
            "harassment":  round(harassment * 100),
            "threatening": round(threatening * 100),
            "mod_score":   mod_score,
            "flagged":     flagged,
        }

    except urllib.error.HTTPError as e:
        return _empty(reason=f"http_{e.code}")
    except Exception as e:
        return _empty(reason=str(e))


def _empty(reason: str = "") -> dict:
    return {
        "available":   False,
        "harassment":  0,
        "threatening": 0,
        "mod_score":   0,
        "flagged":     False,
        "reason":      reason,
    }


# ── 추후 GPT 기반 문맥 판별 추가 시 아래에 구현 ──────────────────────────
# def gpt_moderate(text: str, history: list[str]) -> dict:
#     """GPT를 이용한 문맥 기반 악성 판별 (유료)"""
#     pass
