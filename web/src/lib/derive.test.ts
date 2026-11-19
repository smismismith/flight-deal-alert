import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { AlertsFile, HistoryFile, IndexFile, LatestDestination, LatestFile, StatusFile } from "../types";
import {
  activeAlerts,
  baselineNote,
  axisDateTicks,
  buildChartModel,
  buildHeatGrid,
  buildNotices,
  chartSummary,
  computeYDomain,
  criterionStates,
  displayFare,
  filterDestinations,
  groupErrors,
  heatLevels,
  judgementSentences,
  nearestIndex,
  niceTicks,
  parseDestHash,
  pastAlerts,
  pickInitialDestination,
  regionCounts,
  sortDestinations,
} from "./derive";

function sample<T>(name: string): T {
  const path = fileURLToPath(new URL(`../../public/sample-data/${name}`, import.meta.url));
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

const latest = sample<LatestFile>("latest.json");
const alerts = sample<AlertsFile>("alerts.json");
const status = sample<StatusFile>("status.json");
const index = sample<IndexFile>("index.json");
const dest = (code: string): LatestDestination => {
  const found = latest.destinations.find((d) => d.destination === code);
  if (!found) throw new Error(code);
  return found;
};

describe("알림", () => {
  it("active 알림을 가격 오름차순으로 반환한다", () => {
    const active = activeAlerts(alerts.alerts);
    expect(active.map((a) => [a.city_ko, displayFare(a).price_krw])).toEqual([
      ["후쿠오카", 219000],
      ["다낭", 338000],
    ]);
  });
  it("지난 알림은 replaced·ended 2건이다", () => {
    expect(pastAlerts(alerts.alerts).map((a) => [a.destination, a.status, a.alerted_price_krw])).toEqual([
      ["DAD", "replaced", 359000],
      ["TPE", "ended", 298000],
    ]);
  });
  it("current_fare 가 없으면 fare 를 사용한다", () => {
    const first = alerts.alerts[0]!;
    expect(displayFare({ ...first, current_fare: null })).toBe(first.fare);
  });
});

describe("판정 근거", () => {
  const dad = activeAlerts(alerts.alerts).find((a) => a.destination === "DAD")!;
  const fuk = activeAlerts(alerts.alerts).find((a) => a.destination === "FUK")!;

  it("다낭: 문장 3개와 기준가 대비 줄", () => {
    expect(judgementSentences(displayFare(dad))).toEqual([
      "Google 평소 가격 하한(365,000원)보다 7.4% 저렴",
      "수집 이력 중앙값(423,000원)보다 20.1% 저렴",
      "최근 60일 가격 하위 10% 이하(60일 최저가 대비 -10.0%)",
    ]);
    expect(baselineNote(displayFare(dad))).toBe("비성수기 기준가(299,700원) 대비 +12.8%");
  });
  it("후쿠오카: 문장 2개, 기준가 대비 줄 없음", () => {
    const sentences = judgementSentences(displayFare(fuk));
    expect(sentences).toHaveLength(2);
    expect(sentences[0]).toBe("Google 평소 가격 하한(230,000원)보다 4.8% 저렴");
    expect(sentences[1]).toBe("비성수기 기준가(224,000원) 이하(-2.2%)");
    expect(baselineNote(displayFare(fuk))).toBeNull();
  });
  it("기준 칩 상태 3종", () => {
    const fare = displayFare(dad);
    expect(criterionStates(fare.judgement).map((c) => c.state)).toEqual([
      "matched",
      "unmatched",
      "matched",
      "matched",
    ]);
    const partial = { ...fare.judgement, evaluated: fare.judgement.evaluated.filter((c) => c !== "offseason") };
    expect(criterionStates(partial)[1]).toEqual({ criterion: "offseason", state: "not_evaluated" });
  });
  it("비율 값이 없으면 괄호 부분을 생략한다", () => {
    const fare = displayFare(dad);
    const noPct = { ...fare, judgement: { ...fare.judgement, pct_vs_60d_min: null } };
    expect(judgementSentences(noPct)[2]).toBe("최근 60일 가격 하위 10% 이하");
  });
});

describe("목적지 표", () => {
  it("가격 낮은 순: 제주 → 후쿠오카 … 파리", () => {
    const sorted = sortDestinations(latest.destinations, "price_asc");
    expect(sorted).toHaveLength(15);
    expect([sorted[0]!.city_ko, sorted[0]!.best?.price_krw]).toEqual(["제주", 130800]);
    expect([sorted[1]!.city_ko, sorted[1]!.best?.price_krw]).toEqual(["후쿠오카", 219000]);
    expect([sorted[14]!.city_ko, sorted[14]!.best?.price_krw]).toEqual(["파리", 1779200]);
  });
  it("가격 없는 목적지는 정렬 방향과 관계없이 마지막이다", () => {
    const changed = latest.destinations.map((d) => (d.destination === "CJU" ? { ...d, best: null } : d));
    for (const key of ["price_asc", "price_desc", "name"] as const) {
      const sorted = sortDestinations(changed, key);
      expect(sorted[sorted.length - 1]!.destination).toBe("CJU");
    }
    expect(sortDestinations(changed, "price_desc")[0]!.destination).toBe("CDG");
  });
  it("가격이 같으면 데이터 순서를 유지한다", () => {
    const a = { ...dest("KIX"), best: { ...dest("KIX").best!, price_krw: 100 } };
    const b = { ...dest("NRT"), best: { ...dest("NRT").best!, price_krw: 100 } };
    expect(sortDestinations([a, b], "price_desc").map((d) => d.destination)).toEqual(["KIX", "NRT"]);
  });
  it("지역별 개수와 필터", () => {
    expect(regionCounts(latest.destinations)).toEqual([
      { region: "국내", count: 1 },
      { region: "일본", count: 4 },
      { region: "중화권", count: 2 },
      { region: "동남아", count: 4 },
      { region: "대양주", count: 2 },
      { region: "유럽", count: 1 },
      { region: "미주", count: 1 },
    ]);
    expect(filterDestinations(latest.destinations, "일본", false)).toHaveLength(4);
    expect(filterDestinations(latest.destinations, "전체", true).map((d) => d.destination)).toEqual(["FUK", "DAD"]);
    expect(filterDestinations(latest.destinations, "유럽", true)).toHaveLength(0);
  });
});

describe("목적지 선택", () => {
  it("해시 형식", () => {
    expect(parseDestHash("#dest=KIX")).toBe("KIX");
    expect(parseDestHash("#dest=kix")).toBeNull();
    expect(parseDestHash("")).toBeNull();
  });
  it("해시 → 첫 active 알림 → 최저가 순서", () => {
    expect(pickInitialDestination("#dest=KIX", alerts.alerts, latest.destinations)).toBe("KIX");
    expect(pickInitialDestination("#dest=ZZZ", alerts.alerts, latest.destinations)).toBe("DAD");
    expect(pickInitialDestination("", alerts.alerts, latest.destinations)).toBe("DAD");
    expect(pickInitialDestination("", [], latest.destinations)).toBe("CJU");
    expect(pickInitialDestination("", null, latest.destinations)).toBe("CJU");
    expect(pickInitialDestination("", null, [])).toBeNull();
  });
});

describe("히트맵", () => {
  it("단계 계산: 5개 이상이면 5분위", () => {
    const levels = heatLevels([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]);
    expect(levels.get(100)).toBe(5);
    expect(levels.get(200)).toBe(5);
    expect(levels.get(300)).toBe(4);
    expect(levels.get(1000)).toBe(1);
  });
  it("단계 계산: 5개 미만이면 최저가부터 5, 4, 3, 2", () => {
    expect([...heatLevels([300, 100, 200, 100]).entries()]).toEqual([
      [100, 5],
      [200, 4],
      [300, 3],
    ]);
    expect(heatLevels([777]).get(777)).toBe(5);
    expect(heatLevels([]).size).toBe(0);
  });
  it("오사카는 64칸에 가격이 있고 14행 × 5열이다", () => {
    const grid = buildHeatGrid(latest.trip, dest("KIX").combos, dest("KIX").best);
    expect(grid.rows).toHaveLength(14);
    expect(grid.nightsList).toEqual([3, 4, 5, 6, 7]);
    expect(grid.pricedCount).toBe(64);
    const kinds = grid.rows.flatMap((r) => r.cells.map((c) => c.kind));
    expect(kinds.filter((k) => k === "price")).toHaveLength(64);
    expect(kinds.filter((k) => k === "out")).toHaveLength(6);
    expect(kinds.filter((k) => k === "unsearched")).toHaveLength(0);
    expect(grid.rows.flatMap((r) => r.cells).filter((c) => c.kind === "price" && c.isBest)).toHaveLength(1);
  });
  it("방콕은 6칸만 가격이 있고 나머지는 조회하지 않음·조건 밖이다", () => {
    const grid = buildHeatGrid(latest.trip, dest("BKK").combos, dest("BKK").best);
    const kinds = grid.rows.flatMap((r) => r.cells.map((c) => c.kind));
    expect(kinds.filter((k) => k === "price")).toHaveLength(6);
    expect(kinds.filter((k) => k === "unsearched")).toHaveLength(58);
    expect(kinds.filter((k) => k === "out")).toHaveLength(6);
  });
  it("12/30 출발 5박은 조건 밖, 4박은 조건 안이다", () => {
    const grid = buildHeatGrid(latest.trip, [], null);
    const row = grid.rows.find((r) => r.departDate === "2026-12-30")!;
    expect(row.cells.map((c) => c.kind)).toEqual(["unsearched", "unsearched", "out", "out", "out"]);
    expect(grid.pricedCount).toBe(0);
    expect(grid.minPrice).toBeNull();
  });
  it("다낭 12/21 4박은 특가이면서 최저가 칸이고 단계 5다", () => {
    const grid = buildHeatGrid(latest.trip, dest("DAD").combos, dest("DAD").best);
    const cell = grid.rows.find((r) => r.departDate === "2026-12-21")!.cells.find((c) => c.nights === 4)!;
    expect(cell.kind).toBe("price");
    if (cell.kind !== "price") return;
    expect(cell.combo.price_krw).toBe(338000);
    expect(cell.combo.is_deal).toBe(true);
    expect(cell.isBest).toBe(true);
    expect(cell.level).toBe(5);
    expect(grid.minPrice).toBe(338000);
  });
});

describe("수집 상태", () => {
  it("오류를 종류별로 집계한다", () => {
    expect(groupErrors(status.last_run.errors)).toEqual([
      { kind: "bot_check", label: "봇 확인", count: 6 },
      { kind: "network", label: "네트워크", count: 2 },
    ]);
  });
  const now = Date.parse("2026-11-19T10:00:00+09:00");
  it("샘플 데이터는 샘플 안내만 표시한다", () => {
    expect(buildNotices(status, index, now).map((n) => n.id)).toEqual(["sample"]);
  });
  it("partial 은 안내를 표시하지 않는다", () => {
    expect(buildNotices(status, { ...index, is_sample: false }, now)).toEqual([]);
  });
  it("stopped · failed 안내 문구", () => {
    const stopped = buildNotices(
      { state: "stopped", consecutive_failures: 3, last_success_at: "2026-11-18T22:14:00+09:00" },
      { ...index, is_sample: false },
      now,
    );
    expect(stopped).toHaveLength(1);
    expect(stopped[0]!.role).toBe("alert");
    expect(stopped[0]!.text).toBe(
      "수집이 중단된 상태입니다. 3회 연속 실패했습니다. 마지막 성공: 11/18 22:14. 아래 가격은 그 시점의 값입니다.",
    );
    const failed = buildNotices(
      { state: "failed", consecutive_failures: 1, last_success_at: null },
      { ...index, is_sample: false },
      now,
    );
    // 성공한 수집이 없으면 "아래 가격은 그 시점의 값입니다" 문장을 표시하지 않는다
    expect(failed[0]!.text).toBe("최근 수집이 실패했습니다. 마지막 성공: 없음.");
    const failedAfterSuccess = buildNotices(
      { state: "failed", consecutive_failures: 1, last_success_at: "2026-11-18T22:14:00+09:00" },
      { ...index, is_sample: false },
      now,
    );
    expect(failedAfterSuccess[0]!.text).toBe(
      "최근 수집이 실패했습니다. 마지막 성공: 11/18 22:14. 아래 가격은 그 시점의 값입니다.",
    );
  });
  it("14시간 이상 지나면 경과 시간을 버림한 정수로 표시한다", () => {
    const base = { ...index, is_sample: false };
    const at = (iso: string) => buildNotices(status, base, Date.parse(iso));
    expect(at("2026-11-19T23:24:47+09:00")).toEqual([]);
    expect(at("2026-11-19T23:24:48+09:00")[0]!.text).toBe(
      "마지막 수집 후 14시간이 지났습니다. 표시된 가격은 현재 가격과 다를 수 있습니다.",
    );
    expect(at("2026-11-20T13:00:00+09:00")[0]!.text).toContain("27시간");
  });
  it("status 를 읽지 못해도 샘플·경과 안내는 계산한다", () => {
    expect(buildNotices(null, index, now).map((n) => n.id)).toEqual(["sample"]);
  });
});

describe("차트", () => {
  it("세로축 범위: 기준가가 최솟값의 75% 이상이면 포함한다(다낭)", () => {
    const y = computeYDomain([338000, 446300], 365000, 560000, 299700)!;
    const span = 446300 - 299700;
    expect(y.min).toBeCloseTo(299700 - span * 0.08);
    expect(y.max).toBeCloseTo(446300 + span * 0.08);
  });
  it("세로축 범위: 기준가가 최솟값의 75% 미만이면 제외한다(제주)", () => {
    const y = computeYDomain([117800, 160000], 65000, 160000, 75000)!;
    expect(y.min).toBeCloseTo(117800 - (160000 - 117800) * 0.08);
    expect(y.min).toBeGreaterThan(75000);
  });
  it("세로축 범위: typical_high 는 최댓값의 125% 이하이면 포함한다", () => {
    expect(computeYDomain([100000, 200000], null, 250000, null)!.max).toBeCloseTo(250000 + 150000 * 0.08);
    expect(computeYDomain([100000, 200000], null, 250001, null)!.max).toBeCloseTo(200000 + 100000 * 0.08);
  });
  it("값이 없으면 null, 값이 1개이면 범위를 임의로 넓힌다", () => {
    expect(computeYDomain([], null, null, null)).toBeNull();
    const y = computeYDomain([100000], null, null, null)!;
    expect(y.min).toBeLessThan(100000);
    expect(y.max).toBeGreaterThan(100000);
  });
  it("눈금은 만원 단위 배수다", () => {
    expect(niceTicks(287972, 458028)).toEqual([300000, 350000, 400000, 450000]);
    expect(niceTicks(1430000, 1530000)).toEqual([1440000, 1460000, 1480000, 1500000, 1520000]);
    expect(niceTicks(130000, 135000)).toEqual([130000]);
    expect(niceTicks(100000, 2000000)).toEqual([500000, 1000000, 1500000, 2000000]);
    expect(niceTicks(5, 5)).toEqual([]);
  });
  it("가장 가까운 점을 찾는다", () => {
    const points = [
      { t: 0, v: 1 },
      { t: 10, v: 2 },
      { t: 20, v: 3 },
    ];
    expect(nearestIndex(points, 14)).toBe(1);
    expect(nearestIndex(points, 16)).toBe(2);
    expect(nearestIndex([], 5)).toBe(-1);
  });
  it("다낭: 두 선과 기준가가 범위 안에 있다", () => {
    const history = sample<HistoryFile>("history/DAD.json");
    const best = dest("DAD").best!;
    const model = buildChartModel({
      points: history.points,
      insight: best.insight,
      baseline: best.judgement.baseline_price_krw,
      generatedAt: latest.generated_at,
    })!;
    expect(model.own).toHaveLength(43);
    expect(model.google).toHaveLength(61);
    expect(model.baselineInRange).toBe(true);
    expect(model.band).toEqual({ low: 365000, high: 560000 });
    expect(model.xMax).toBe(Date.parse(latest.generated_at));
    expect(model.xMin).toBe(Date.parse("2026-09-20T00:00:00+09:00"));
    expect(chartSummary("다낭", model)).toContain("수집 이력 43건");
    expect(chartSummary("다낭", model)).toContain("현재 338,000원.");
  });
  it("제주: 기준가가 차트 범위 밖이다", () => {
    const history = sample<HistoryFile>("history/CJU.json");
    const best = dest("CJU").best!;
    const model = buildChartModel({
      points: history.points,
      insight: best.insight,
      baseline: best.judgement.baseline_price_krw,
      generatedAt: latest.generated_at,
    })!;
    expect(model.baseline).toBe(75000);
    expect(model.baselineInRange).toBe(false);
  });
  it("시드니: Google 정보가 없으면 수집 이력만 사용한다", () => {
    const history = sample<HistoryFile>("history/SYD.json");
    const best = dest("SYD").best!;
    expect(best.insight).toBeNull();
    const model = buildChartModel({
      points: history.points,
      insight: best.insight,
      baseline: best.judgement.baseline_price_krw,
      generatedAt: latest.generated_at,
    })!;
    expect(model.google).toHaveLength(0);
    expect(model.band).toBeNull();
    expect(model.own.length).toBeGreaterThan(1);
  });
  it("이력이 모두 없으면 null 이다", () => {
    expect(buildChartModel({ points: [], insight: null, baseline: null, generatedAt: latest.generated_at })).toBeNull();
  });
});

describe("가로축 날짜 눈금", () => {
  const fmt = (ms: number) => {
    const d = new Date(ms + 9 * 3600000);
    return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  };
  const at = (iso: string) => Date.parse(iso);
  it("이력 기간이 짧으면 같은 날짜를 한 번만 표시한다", () => {
    const ticks = axisDateTicks(at("2026-11-18T22:00:00+09:00"), at("2026-11-19T14:00:00+09:00"), 4, 400, fmt);
    expect(ticks.map((t) => t.label)).toEqual(["11/18", "11/19"]);
    expect(ticks[1]!.t).toBe(at("2026-11-19T14:00:00+09:00"));
    const sameDay = axisDateTicks(at("2026-11-19T08:00:00+09:00"), at("2026-11-19T21:00:00+09:00"), 6, 600, fmt);
    expect(sameDay.map((t) => t.label)).toEqual(["11/19"]);
  });
  it("차트 영역이 좁으면 눈금 수를 줄여 글자가 겹치지 않게 한다", () => {
    const min = at("2026-09-20T00:00:00+09:00");
    const max = at("2026-11-19T00:00:00+09:00");
    expect(axisDateTicks(min, max, 4, 142, fmt)).toHaveLength(3); // 폭 360px, 7자리 가격
    expect(axisDateTicks(min, max, 4, 200, fmt)).toHaveLength(4);
    expect(axisDateTicks(min, max, 6, 500, fmt)).toHaveLength(6);
    expect(axisDateTicks(min, max, 4, 40, fmt)).toHaveLength(2);
  });
});

describe("히트맵 조회 범위", () => {
  it("조건 안 칸 수와 가격이 있는 칸 수를 함께 반환한다", () => {
    const trip = { adults: 1, depart_from: "2026-12-17", depart_to: "2026-12-30", return_by: "2027-01-03", nights_min: 3, nights_max: 7 };
    const grid = buildHeatGrid(trip, [], null);
    expect(grid.inRangeCount).toBe(64);
    expect(grid.pricedCount).toBe(0);
  });
});
