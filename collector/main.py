"""수집 실행: 조회 -> 기준가 -> 판정 -> 알림 상태 -> 호텔 -> 텔레그램 -> 저장.

사용:
  uv run python -m collector.main [--dry-run] [--limit N] [--destinations KIX,CJU]
                                  [--max-queries N] [--max-requests N] [--out DIR]
"""
from __future__ import annotations

import argparse
import copy
import os
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import flights as fl
from .alerts import Outcome, active_alert, trim_alerts, update_alerts
from .baseline import refresh_baseline
from .config import KST, ROOT, Combo, Config, Destination, iso_kst, load_config, make_run_id
from .hotels import HotelFinder
from .http import get_json, post_json
from .judge import build_fare, pick_best_and_deal, to_combo
from .notify import RESUME_TEXT, TelegramNotifier, format_alert, format_stop_notice, won
from .store import DataStore, empty_entry, history_point

MAX_ERRORS = 50
PERIOD_OVER_REASON = "출발 가능 기간이 끝나 조회 대상이 없음"


@dataclass
class Deps:
    """외부 의존성. 테스트에서는 모두 모의 객체로 바꾼다."""

    fetch: Callable[[Any, float], str] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    rng: Callable[[], float] = random.random
    now: Callable[[], datetime] = lambda: datetime.now(KST)
    http_get: Callable[[str, dict, float], dict] = get_json
    http_post: Callable[[str, dict, float], dict] = post_json
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    out: Callable[[str], None] = print


@dataclass
class RunState:
    """실행 1회의 집계. 조회(대표·확대)와 기준가 조회를 구분해 센다."""

    cfg: Config
    client: fl.FlightClient
    now: Callable[[], datetime]
    max_queries: int | None = None
    planned: int = 0
    attempted: int = 0
    succeeded: int = 0
    no_result: int = 0
    failed: int = 0
    baseline_queries: int = 0
    consecutive_failures: int = 0
    aborted_reason: str | None = None
    errors: list[dict] = field(default_factory=list)
    error_kinds: Counter = field(default_factory=Counter)
    # 목적지 -> {조합: (조회 결과, 수집 시각)}
    results: dict[str, dict[Combo, tuple[fl.QueryResult, str]]] = field(default_factory=dict)
    dest_attempted: Counter = field(default_factory=Counter)
    dest_failed: Counter = field(default_factory=Counter)
    expanded: list[str] = field(default_factory=list)
    # 목적지 -> 이번 실행에서 조회 대상이었던 조합 / 응답을 받은(성공 또는 결과 없음) 조합
    planned_combos: dict[str, set[Combo]] = field(default_factory=dict)
    resolved: dict[str, set[Combo]] = field(default_factory=dict)
    incomplete: bool = False      # 상한·중단으로 조회를 끝까지 하지 못함
    period_over: bool = False     # 출발 가능한 조합이 남지 않음
    clock: Callable[[], float] | None = None
    deadline: float | None = None  # clock 기준 실행 시간 상한

    @property
    def total_queries(self) -> int:
        return self.attempted + self.baseline_queries

    def can_query(self) -> bool:
        if self.aborted_reason is not None:
            return False
        if self.max_queries is not None and self.total_queries >= self.max_queries:
            return False
        if self.deadline is not None and self.clock is not None and self.clock() >= self.deadline:
            minutes = int(self.cfg.max_run_minutes)
            self.aborted_reason = f"실행 시간 상한 {minutes}분을 초과해 남은 조회를 생략함"
            return False
        return self.client.has_budget()

    def add_error(self, kind: str, message: str, dest: str | None = None, depart: str | None = None, ret: str | None = None):
        self.error_kinds[kind] += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(
                {"destination": dest, "depart_date": depart, "return_date": ret, "kind": kind, "message": message[:300]}
            )

    def search(self, origin: str, dest: str, depart, ret, is_baseline: bool = False) -> fl.QueryResult:
        """조회 1건을 실행하고 집계한다. 재시도 후 실패가 연속 N건이면 aborted_reason 을 기록한다."""
        res = self.client.search(origin, dest, depart, ret)
        if is_baseline:
            self.baseline_queries += 1
        else:
            self.attempted += 1
            self.dest_attempted[dest] += 1
        if res.status in (fl.OK, fl.NO_RESULT):
            self.consecutive_failures = 0
            if not is_baseline:
                if res.status == fl.OK:
                    self.succeeded += 1
                else:
                    self.no_result += 1
        else:
            self.consecutive_failures += 1
            if not is_baseline:
                self.failed += 1
                self.dest_failed[dest] += 1
            prefix = "기준가 조회: " if is_baseline else ""
            self.add_error(res.status, prefix + res.message, dest, depart.isoformat(), ret.isoformat())
            limit = self.cfg.abort_after_failures
            if self.consecutive_failures >= limit:
                self.aborted_reason = f"조회 실패가 연속 {limit}건 발생해 남은 조회를 생략함"
        return res


def select_expansion(state: RunState, dests: list[Destination], rep_combos: list[Combo], alerts: list[dict]) -> list[Destination]:
    """확대 대상: 대표 조합 최저가 하위 N개 목적지 + active 알림이 있는 목적지. 대표 조합 가격이 없으면 제외한다."""
    rep_min: dict[str, int] = {}
    for d in dests:
        prices = [
            r.flight.price_krw
            for c, (r, _) in state.results.get(d.code, {}).items()
            if c in rep_combos and r.flight is not None
        ]
        if prices:
            rep_min[d.code] = min(prices)
    order = {d.code: i for i, d in enumerate(dests)}
    ranked = sorted(rep_min, key=lambda c: (rep_min[c], order[c]))
    chosen = ranked[: state.cfg.expand_top_n]
    for d in dests:
        if d.code in rep_min and d.code not in chosen and active_alert(alerts, d.code) is not None:
            chosen.append(d.code)
    by_code = {d.code: d for d in dests}
    return [by_code[c] for c in chosen]


def collect(state: RunState, dests: list[Destination], alerts: list[dict], today) -> None:
    """대표 조합 조회 후 확대 조회를 한다."""
    cfg = state.cfg
    all_combos = cfg.all_combos(today)
    if not all_combos:
        state.period_over = True
        return
    reps = cfg.representative_combos(today)
    state.planned = len(reps) * len(dests)
    for d in dests:
        state.planned_combos[d.code] = set(reps)

    def one(d: Destination, c: Combo) -> None:
        res = state.search(d.origin, d.code, c.depart, c.return_date)
        if res.status in (fl.OK, fl.NO_RESULT):
            state.resolved.setdefault(d.code, set()).add(c)
        if res.status == fl.OK:
            state.results.setdefault(d.code, {})[c] = (res, iso_kst(state.now()))

    for c in reps:  # 조합 단위로 조회해 중단되더라도 목적지별 결과가 고르게 남도록 한다
        for d in dests:
            if not state.can_query():
                state.incomplete = True
                return
            one(d, c)

    rest = [c for c in all_combos if c not in reps]
    targets = select_expansion(state, dests, reps, alerts)
    state.planned += len(rest) * len(targets)
    for d in targets:
        state.planned_combos[d.code] |= set(rest)
    for d in targets:
        for c in rest:
            if not state.can_query():
                state.incomplete = True
                return
            if d.code not in state.expanded:
                state.expanded.append(d.code)
            one(d, c)


def classify(state: RunState) -> str:
    """실행 결과. 가격을 1건도 얻지 못하면 failed, 결과 없음 비율이 상한을 넘으면 ok 로 분류하지 않는다."""
    if state.period_over:
        return "ok"
    if state.attempted == 0 or state.succeeded == 0:
        return "failed"
    if state.failed == 0 and state.no_result <= state.cfg.max_no_result_ratio * state.attempted:
        return "ok"
    ok = state.succeeded + state.no_result
    return "partial" if ok >= state.cfg.failed_ratio * state.attempted else "failed"


def note_no_result_anomaly(state: RunState) -> None:
    """결과 없음이 비정상적으로 많으면 errors 에 기록한다(응답 형식 변경·조회 제한 가능성)."""
    if state.attempted == 0 or state.no_result == 0:
        return
    if state.succeeded == 0 and state.failed == 0:
        state.add_error("other", f"모든 조회({state.no_result}건)에서 항공편을 찾지 못해 이전 값을 유지함. 응답 형식 변경 또는 조회 제한 가능성 있음")
    elif state.no_result > state.cfg.max_no_result_ratio * state.attempted:
        state.add_error("other", f"결과 없음이 {state.no_result}건으로 시도 {state.attempted}건의 {int(state.cfg.max_no_result_ratio * 100)}%를 초과함")


def _combo_key(rec: dict) -> Combo:
    return Combo(date.fromisoformat(rec["depart_date"]), int(rec["nights"]))


def build_entries(
    state: RunState,
    cfg: Config,
    selected: list[Destination],
    prev_latest: dict[str, dict],
    baseline: list[dict],
    histories: dict[str, list[dict]],
    run_id: str,
    today,
) -> tuple[list[dict], dict[str, Outcome], set[str]]:
    """목적지별 latest 항목, 알림 판단용 결과, 이력이 바뀐 목적지 코드를 만든다.

    - 이번 실행의 조회 대상이 아닌 목적지: 이전 항목을 변경하지 않는다.
    - 조회 대상이지만 가격을 1건도 얻지 못한 목적지: 이전 값을 유지하고 stale=true 로 표시한다.
    - 가격을 얻은 목적지: 이번 실행에서 응답을 받지 못한 조합(실패·생략)은 이전 실행의 값을 유지한다.
    """
    valid = set(cfg.all_combos(today))
    reps = set(cfg.representative_combos(today))
    base = {(b["origin"], b["destination"], b["nights"]): b["price_krw"] for b in baseline}
    selected_codes = set() if state.period_over else {d.code for d in selected}
    entries: list[dict] = []
    outcomes: dict[str, Outcome] = {}
    changed: set[str] = set()
    for d in cfg.destinations:
        prev = prev_latest.get(d.code)
        has_prev = prev is not None and bool(prev.get("best") or prev.get("combos"))
        got = state.results.get(d.code, {})
        if d.code not in selected_codes:
            if prev is not None:
                entries.append({**copy.deepcopy(prev), **d.place(), "is_domestic": d.is_domestic})
            else:
                entries.append(empty_entry(d, stale=False))
            continue
        if not got:
            if has_prev:
                entry = {**copy.deepcopy(prev), **d.place(), "is_domestic": d.is_domestic, "stale": True}
            else:
                entry = empty_entry(d, stale=state.dest_failed[d.code] > 0)
            entries.append(entry)
            outcomes[d.code] = Outcome(refreshed=False)
            continue
        own = [
            p["rep_price_krw"]
            for p in histories.get(d.code, [])
            if p.get("run_id") != run_id and p.get("rep_price_krw") is not None
        ]
        fares = [
            build_fare(d, c, res, at, c in reps, base.get((d.origin, d.code, c.nights)), own, cfg)
            for c, (res, at) in sorted(got.items())
        ]
        # 이번 실행에서 응답을 받지 못한 조합: 중단·상한이면 남은 전체 조합, 아니면 조회 대상 중 실패한 조합
        scope = valid if state.incomplete else state.planned_combos.get(d.code, set())
        unresolved = (scope & valid) - state.resolved.get(d.code, set())
        kept_fares: list[dict] = []
        if has_prev and unresolved:
            for key in ("best", "deal"):
                f = prev.get(key)
                if f and _combo_key(f) in unresolved and all(_combo_key(f) != _combo_key(k) for k in kept_fares):
                    kept_fares.append(copy.deepcopy(f))
        new_best, _ = pick_best_and_deal(fares)
        best, deal = pick_best_and_deal(fares + kept_fares)
        combos = {}
        if has_prev and unresolved:
            for c in prev.get("combos", []):
                if _combo_key(c) in unresolved:
                    combos[_combo_key(c)] = copy.deepcopy(c)
        for f in kept_fares:
            combos.setdefault(_combo_key(f), to_combo(f))
        kept_count = len(combos)
        for f in fares:
            combos[_combo_key(f)] = to_combo(f)
        # best 는 전체 기록이 있는 요금 중에서만 정할 수 있으므로, 그보다 낮은 이전 조합 값은 제외한다
        combo_list = [c for _, c in sorted(combos.items()) if c["price_krw"] >= best["price_krw"]]
        entry = empty_entry(d, stale=False)
        entry.update(
            expanded=d.code in state.expanded or bool(kept_count and prev.get("expanded")),
            last_success_at=max(f["collected_at"] for f in fares),
            best=best,
            deal=deal,
            combos=combo_list,
        )
        entries.append(entry)
        outcomes[d.code] = Outcome(
            refreshed=True, deal=deal, deal_carried=deal is not None and not any(deal is f for f in fares)
        )
        rep_prices = [f["price_krw"] for f in fares if f["is_representative"]]
        points = [p for p in histories.get(d.code, []) if p.get("run_id") != run_id]
        points.append(history_point(run_id, new_best, min(rep_prices) if rep_prices else None, len(fares)))
        histories[d.code] = points
        changed.add(d.code)
    return entries, outcomes, changed


def reconcile(entries: list[dict], alerts: list[dict], cfg: Config, now_iso: str) -> None:
    """불변 조건(deal != null <=> active 알림 존재)을 보장한다. 목록에서 빠진 목적지의 active 알림은 종료한다."""
    by_code = {e["destination"]: e for e in entries}
    for a in alerts:
        if a["status"] != "active":
            continue
        e = by_code.get(a["destination"])
        if e is None or e["deal"] is None:
            a.update(status="ended", ended_at=now_iso, current_fare=None, current_checked_at=now_iso)
    for e in entries:
        if e["deal"] is not None and active_alert(alerts, e["destination"]) is None:
            e["deal"] = None


def send_alerts(
    state: RunState, to_send: list[dict], dests: dict[str, Destination], finder: HotelFinder,
    notifier: TelegramNotifier, cfg: Config, deps: Deps, dry_run: bool,
) -> int:
    """발송 대상 알림의 호텔을 조회하고 텔레그램으로 보낸다. 발송한 건수를 돌려준다."""
    sent = 0
    for alert in to_send:
        d = dests[alert["destination"]]
        if alert["hotels"]["source"] != "serpapi":
            alert["hotels"] = finder.lookup(d.hotel_query, alert["fare"], iso_kst(state.now()))
        text = format_alert(alert, cfg)
        n = alert["notification"]
        if not notifier.enabled:
            n.update(sent=False, sent_at=None, error=notifier.skip_reason())
            if dry_run:
                deps.out("--- 발송하지 않은 알림 메시지 ---\n" + text)
            continue
        n["attempts"] += 1
        ok, err = notifier.send(text)
        if ok:
            n.update(sent=True, sent_at=iso_kst(state.now()), error=None)
            sent += 1
        else:
            n.update(sent=False, sent_at=None, error=err)
            state.add_error("telegram", f"알림 발송 실패: {err}", alert["destination"])
    for msg in finder.errors:
        state.add_error("hotel", msg)
    return sent


def update_status(
    status: dict, state: RunState, run: dict, notifier: TelegramNotifier, cfg: Config, now_iso: str
) -> None:
    """연속 실패 횟수, 수집 중단·재개 안내, 실행 목록을 갱신한다."""
    result = run["result"]
    if result == "failed":
        status["consecutive_failures"] += 1
    else:
        status["consecutive_failures"] = 0
        if not state.period_over:
            status["last_success_at"] = run["finished_at"]
    threshold = cfg.stop_after_failed_runs
    if result == "failed" and status["consecutive_failures"] >= threshold and not status["stop_notice_sent"]:
        text = format_stop_notice(threshold, status["last_success_at"], state.error_kinds)
        if notifier.enabled:
            ok, err = notifier.send(text, html=False)
            if ok:
                status["stop_notice_sent"] = True
            else:
                state.add_error("telegram", f"수집 중단 안내 발송 실패: {err}")
    elif result != "failed" and status["stop_notice_sent"]:
        if notifier.enabled:
            ok, err = notifier.send(RESUME_TEXT, html=False)
            if ok:
                status["stop_notice_sent"] = False
            else:
                state.add_error("telegram", f"수집 재개 안내 발송 실패: {err}")
    run["errors"] = state.errors[:MAX_ERRORS]
    status["state"] = "stopped" if status["consecutive_failures"] >= threshold else result
    status["updated_at"] = now_iso
    status["last_run"] = run
    status["runs"] = ([run] + [r for r in status.get("runs", []) if r.get("run_id") != run["run_id"]])[: cfg.keep_runs]


def print_summary(deps: Deps, run: dict, entries: list[dict], selected: list[Destination], state: RunState, write_dir) -> None:
    q = run["queries"]
    deps.out(f"실행 {run['run_id']} 결과: {run['result']} (소요 {run['duration_seconds']}초)")
    deps.out(
        f"조회: 계획 {q['planned']} / 시도 {q['attempted']} / 성공 {q['succeeded']} / 결과 없음 {q['no_result']}"
        f" / 실패 {q['failed']} / 생략 {q['skipped']} / 봇 확인 {q['bot_checks']} / 재시도 {q['retries']}"
        f" / 기준가 조회 {run['baseline_queries']} / HTTP 요청 {state.client.requests}"
    )
    codes = {d.code for d in selected}
    for e in entries:
        if e["destination"] not in codes:
            continue
        b = e["best"]
        if b is None:
            deps.out(f"- {e['origin']}->{e['destination']} {e['city_ko']}: 가격 없음" + (" (조회 실패)" if e["stale"] else ""))
            continue
        ins = b["insight"] or {}
        deps.out(
            f"- {e['origin']}->{e['destination']} {e['city_ko']}: 최저 {won(b['price_krw'])} "
            f"{b['depart_date']}~{b['return_date']} {b['nights']}박 {'/'.join(b['airlines'])} {'직항' if b['stops'] == 0 else '경유 ' + str(b['stops']) + '회'}"
            f" | 조합 {len(e['combos'])}개 | level={ins.get('level')} 평소 범위 {ins.get('typical_low_krw')}~{ins.get('typical_high_krw')}"
            f" 이력 {ins.get('history_count', 0)}점 | 해당 기준 {b['judgement']['matched']}"
            f" | 특가 {'있음 ' + won(e['deal']['price_krw']) if e['deal'] else '없음'}"
            + (" (이전 수집 값)" if e["stale"] else "")
        )
    for err in run["errors"]:
        deps.out(f"  오류[{err['kind']}] {err['destination'] or ''} {err['depart_date'] or ''}: {err['message']}")
    if state.period_over:
        deps.out("출발 가능 기간이 끝나 조회하지 않았습니다. .github/workflows/collect.yml 의 schedule 을 비활성화하십시오.")
    deps.out(f"저장 위치: {write_dir}" if write_dir else "저장하지 않음(--dry-run, --out 미지정)")


class _PeriodOver(Exception):
    """출발 가능 기간 종료: 조회·기준가 갱신·저장을 생략한다."""


def default_site_url(env: Mapping[str, str]) -> str:
    """GitHub Actions 의 GITHUB_REPOSITORY(계정/저장소)로 Pages 기본 주소를 만든다. 없으면 빈 문자열."""
    owner, _, repo = (env.get("GITHUB_REPOSITORY") or "").partition("/")
    if not owner or not repo:
        return ""
    host = f"{owner.lower()}.github.io"
    return f"https://{host}/" if repo.lower() == host else f"https://{host}/{repo}/"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="collector.main", description="연말 특가 항공권 수집")
    p.add_argument("--dry-run", action="store_true", help="텔레그램 발송과 data/ 저장을 하지 않는다(--out 을 주면 그 폴더에만 저장)")
    p.add_argument("--limit", type=int, default=None, help="목록 앞에서부터 N개 목적지만 조회")
    p.add_argument("--destinations", default=None, help="조회할 목적지 코드(쉼표 구분)")
    p.add_argument("--max-queries", type=int, default=None, help="조회 건수 상한(기준가 조회 포함). 초과분은 생략")
    p.add_argument("--max-requests", type=int, default=None, help="HTTP 요청 수 상한(재시도 포함)")
    p.add_argument("--out", default=None, help="결과를 저장할 폴더")
    p.add_argument("--data", default=str(ROOT / "data"), help="이전 상태를 읽는 폴더(기본 data/)")
    p.add_argument("--config", default=str(ROOT / "config"), help="설정 폴더")
    return p.parse_args(argv)


def run(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    args = parse_args(argv)
    deps = deps or Deps()
    cfg = load_config(Path(args.config))
    if not cfg.site_url:
        cfg.site_url = default_site_url(deps.env)
    if args.dry_run:
        store = DataStore(Path(args.data), Path(args.out) if args.out else None)
    else:
        target = Path(args.out) if args.out else Path(args.data)
        store = DataStore(target, target)

    started = deps.now()
    started_iso, run_id, today = iso_kst(started), make_run_id(started), started.astimezone(KST).date()

    selected = list(cfg.destinations)
    if args.destinations:
        want = [c.strip().upper() for c in args.destinations.split(",") if c.strip()]
        selected = [d for d in selected if d.code in want]
    if args.limit is not None:
        selected = selected[: max(args.limit, 0)]
    dests = {d.code: d for d in cfg.destinations}

    status = store.load_status(started_iso)
    if status["serpapi"]["month"] != started_iso[:7]:
        status["serpapi"] = {"month": started_iso[:7], "calls": 0}
    notifier = TelegramNotifier(
        deps.env.get("TELEGRAM_BOT_TOKEN"), deps.env.get("TELEGRAM_CHAT_ID"), deps.http_post, dry_run=args.dry_run
    )
    finder = HotelFinder(cfg, None if args.dry_run else deps.env.get("SERPAPI_KEY"), status["serpapi"], deps.http_get)
    client = fl.FlightClient(cfg, deps.fetch, deps.sleep, deps.clock, deps.rng, max_requests=args.max_requests)
    state = RunState(
        cfg=cfg, client=client, now=deps.now, max_queries=args.max_queries,
        clock=deps.clock, deadline=deps.clock() + cfg.max_run_minutes * 60,
    )

    entries: list[dict] = []
    deals_found = alerts_sent = 0
    fatal: str | None = None
    try:
        alerts = store.load_alerts()
        baseline = store.load_baseline()
        prev_latest = store.load_latest()
        histories = {d.code: store.load_history(d.code) for d in cfg.destinations}

        collect(state, selected, alerts, today)
        if state.period_over:
            raise _PeriodOver()
        note_no_result_anomaly(state)
        baseline_changed = refresh_baseline(state, selected, baseline)

        entries, outcomes, changed = build_entries(state, cfg, selected, prev_latest, baseline, histories, run_id, today)
        now_iso = iso_kst(deps.now())
        to_send = update_alerts(alerts, outcomes, dests, run_id, now_iso, cfg.realert_drop_pct)
        reconcile(entries, alerts, cfg, now_iso)
        deals_found = sum(1 for o in outcomes.values() if o.refreshed and o.deal is not None)
        alerts_sent = send_alerts(state, to_send, dests, finder, notifier, cfg, deps, args.dry_run)
        alerts[:] = trim_alerts(alerts, cfg.keep_alerts)

        now_iso = iso_kst(deps.now())
        store.save_baseline(baseline, now_iso, None if baseline_changed else store.baseline_updated_at)
        same_dir = store.write_dir == store.read_dir
        for d in cfg.destinations:
            if histories.get(d.code) and (d.code in changed or not same_dir):
                store.save_history(d, histories[d.code], cfg.keep_history)
        store.save_alerts(alerts, now_iso)
        store.save_latest_and_index(cfg, entries, {c for c, p in histories.items() if p}, run_id, now_iso)
    except _PeriodOver:  # 조회 대상이 없으면 data/ 의 가격·알림 파일을 변경하지 않는다
        pass
    except Exception as e:  # 처리 중 예외: 실행을 failed 로 기록하고 status.json 은 저장한다
        fatal = f"처리 중 예외로 종료: {type(e).__name__}: {str(e)[:200]}"
        state.add_error("other", fatal)

    finished = deps.now()
    result = "failed" if fatal else classify(state)
    selected_codes = {d.code for d in selected}
    run_rec = {
        "run_id": run_id,
        "started_at": started_iso,
        "finished_at": iso_kst(finished),
        "duration_seconds": max(int((finished - started).total_seconds()), 0),
        "result": result,
        "queries": {
            "planned": state.planned,
            "attempted": state.attempted,
            "succeeded": state.succeeded,
            "no_result": state.no_result,
            "failed": state.failed,
            "bot_checks": client.bot_checks,
            "retries": client.retries,
            "skipped": max(state.planned - state.attempted, 0),
        },
        "baseline_queries": state.baseline_queries,
        "destinations_total": len(selected),
        "destinations_succeeded": sum(
            1 for c in selected_codes if state.dest_attempted[c] > 0 and state.dest_failed[c] < state.dest_attempted[c]
        ),
        "failed_destinations": [
            d.code for d in selected if state.dest_attempted[d.code] > 0 and state.dest_failed[d.code] >= state.dest_attempted[d.code]
        ],
        "expanded_destinations": list(state.expanded),
        "deals_found": deals_found,
        "alerts_sent": alerts_sent,
        "hotel_api_calls": finder.calls_this_run,
        "telegram_enabled": notifier.enabled,
        "serpapi_enabled": finder.enabled,
        "aborted_reason": fatal or (PERIOD_OVER_REASON if state.period_over else state.aborted_reason),
        "errors": [],
    }
    already_recorded = state.period_over and (status.get("last_run") or {}).get("aborted_reason") == PERIOD_OVER_REASON
    if already_recorded:  # 기간 종료는 1회만 기록한다(이후 실행은 파일을 변경하지 않아 커밋이 발생하지 않는다)
        store.write_dir = None
    else:
        update_status(status, state, run_rec, notifier, cfg, iso_kst(finished))
        store.save_status(status)
    print_summary(deps, run_rec, entries, selected, state, store.write_dir)
    return 1 if result == "failed" else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
