"""AC-13, AC-14: 텔레그램 메시지와 발송(모의 HTTP)."""
import copy
import json
from collections import Counter

from collector.notify import RESUME_TEXT, TelegramNotifier, format_alert, format_stop_notice
from conftest import ROOT

SAMPLE = json.loads((ROOT / "web/public/sample-data/alerts.json").read_text(encoding="utf-8"))


def sample(dest):
    return copy.deepcopy(next(a for a in SAMPLE["alerts"] if a["destination"] == dest and a["status"] == "active"))


def test_message_for_sample_dad(cfg):
    a = sample("DAD")
    text = format_alert(a, cfg)
    lines = text.split("\n")
    assert lines[0] == "<b>[특가·추가 인하] 다낭(베트남) 338,000원 (직전 알림 359,000원)</b>"
    assert lines[1] == "12/21(월) ~ 12/25(금) · 4박 · 인천(ICN) 출발"
    assert lines[2] == "비엣젯항공 · 직항 · 4시간 55분"
    assert lines[3] == "판정 근거(3개)"
    assert lines[4] == "- Google 평소 가격 하한(365,000원)보다 7.4% 저렴"
    assert lines[5] == "- 수집 이력 중앙값(423,000원)보다 20.1% 저렴"
    assert lines[6] == "- 최근 60일 가격 하위 10% 이하(60일 최저가 대비 -10.0%)"
    assert lines[7] == "비성수기 기준가(299,700원) 대비 +12.8%"
    assert lines[8].startswith('항공권 검색: <a href="https://www.google.com/travel/flights/search?tfs=')
    assert lines[9] == "호텔(12/21~12/25, 1박 요금)"
    assert lines[10] == "1. 사노우바 다낭 호텔 38,900원 · 평점 4.3 · 평소보다 21% 저렴"
    assert lines[12].startswith("3. ") and not lines[13].startswith("4. ")  # 상위 3개만
    assert "Google Hotels</a> · <a href=" in lines[13] and "아고다</a>" in lines[13]
    assert "&amp;hl=ko" in lines[8]  # 링크의 & 는 이스케이프한다
    assert len(lines) == 14  # site_url 이 비어 있으면 사이트 줄 없음
    assert len(text) < 4096


def test_message_for_links_only_and_new_kind(cfg):
    a = sample("FUK")
    text = format_alert(a, cfg)
    assert text.startswith("<b>[특가] 후쿠오카(일본) 219,000원</b>")
    assert "판정 근거(2개)" in text
    assert "- 비성수기 기준가(224,000원) 이하(-2.2%)" in text
    assert "호텔(" not in text and "호텔 검색: " in text
    assert "대비 +" not in text  # 기준 b 에 해당하면 대비 줄을 따로 표시하지 않는다


def test_site_line_and_stops_text(cfg):
    import dataclasses
    a = sample("FUK")
    a["fare"].update(stops=1, duration_minutes=None)
    text = format_alert(a, dataclasses.replace(cfg, site_url="https://example.github.io/deals/"))
    assert "경유 1회" in text.split("\n")[2] and "시간" not in text.split("\n")[2]
    assert text.split("\n")[-1] == "사이트: https://example.github.io/deals/#dest=FUK"


def test_values_are_html_escaped(cfg):
    a = sample("DAD")
    a["fare"]["city_ko"] = "<b>다낭</b>"
    a["fare"]["airlines"] = ["A&B <Air>"]
    a["hotels"]["items"][0]["name"] = "<script>alert(1)</script>"
    a["hotels"]["items"][0]["deal"] = "5 > 3"
    a["fare"]["search_url"] = 'https://example.com/?a=1&b="x"'
    text = format_alert(a, cfg)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "&lt;b&gt;다낭&lt;/b&gt;" in text and "A&amp;B &lt;Air&gt;" in text and "5 &gt; 3" in text
    assert 'href="https://example.com/?a=1&amp;b=&quot;x&quot;"' in text


def test_send_uses_mocked_http_only(cfg):
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload))
        return {"ok": True, "result": {}}

    n = TelegramNotifier("123:TOKEN", "999", post)
    ok, err = n.send(format_alert(sample("DAD"), cfg))
    assert (ok, err) == (True, None) and len(calls) == 1
    url, payload = calls[0]
    assert url == "https://api.telegram.org/bot123:TOKEN/sendMessage"
    assert payload["chat_id"] == "999" and payload["parse_mode"] == "HTML" and payload["disable_web_page_preview"] is True
    assert set(payload) == {"chat_id", "text", "parse_mode", "disable_web_page_preview"}
    assert "123:TOKEN" not in json.dumps(payload, ensure_ascii=False)
    for word in ("다낭", "338,000원", "4박", "비엣젯항공", "직항", "Google 평소 가격 하한", "google.com/travel/flights", "agoda.com"):
        assert word in payload["text"]


def test_missing_token_or_dry_run_makes_no_request():
    calls = []
    post = lambda *a: calls.append(a) or {"ok": True}  # noqa: E731
    for n in (TelegramNotifier(None, "1", post), TelegramNotifier("t", "", post), TelegramNotifier("t", "1", post, dry_run=True)):
        ok, err = n.send("x")
        assert ok is False and err and not n.enabled
    assert calls == []
    assert "설정되지 않음" in TelegramNotifier(None, None, post).skip_reason()


def test_send_failure_reports_reason_without_token():
    def boom(url, payload, timeout):
        raise RuntimeError(f"failed calling {url}")

    ok, err = TelegramNotifier("123:SECRET", "1", boom).send("x")
    assert ok is False and "SECRET" not in err and "***" in err
    ok, err = TelegramNotifier("123:SECRET", "1", lambda *a: {"ok": False, "description": "Bad Request: chat not found"}).send("x")
    assert ok is False and err == "Bad Request: chat not found"


def test_stop_and_resume_notice_text():
    text = format_stop_notice(3, "2026-11-19T09:24:48+09:00", Counter({"bot_check": 8, "network": 2}))
    assert text == (
        "[수집 중단] 항공권 수집이 3회 연속 실패했습니다. 마지막 성공: 2026-11-19 09:24. "
        "주요 원인: 봇 확인 페이지 응답. 다음 실행부터 정상 수집되면 재개 안내를 발송합니다."
    )
    assert "마지막 성공: 없음" in format_stop_notice(3, None, Counter())
    assert RESUME_TEXT == "[수집 재개] 항공권 수집이 다시 정상 처리되었습니다."
