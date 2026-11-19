"""표준 라이브러리 기반 HTTP 호출. hotels.py 와 notify.py 에 주입하는 기본 구현이다."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class HttpError(Exception):
    """주소(토큰·키 포함 가능)를 메시지에 포함하지 않는다."""


def _read(req: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("description", "")
        except Exception:
            pass
        raise HttpError(f"HTTP {e.code} {detail}".strip()) from None
    except urllib.error.URLError as e:
        raise HttpError(f"연결 오류: {type(e.reason).__name__}") from None
    except TimeoutError:
        raise HttpError("응답 시간 초과") from None
    try:
        data = json.loads(body)
    except ValueError:
        raise HttpError("JSON 이 아닌 응답") from None
    if not isinstance(data, dict):
        raise HttpError("예상하지 못한 응답 형식")
    return data


def get_json(url: str, params: dict, timeout: float = 30) -> dict:
    return _read(urllib.request.Request(url + "?" + urllib.parse.urlencode(params)), timeout)


def post_json(url: str, payload: dict, timeout: float = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _read(req, timeout)
