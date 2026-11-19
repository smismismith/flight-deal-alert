// 화면 표시용 계산(DESIGN 2.3, 3.2, 5.x). 화면 요소와 분리해 단위 테스트한다.
import type {
  Alert,
  Combo,
  Criterion,
  ErrorKind,
  Fare,
  HistoryPoint,
  IndexFile,
  Insight,
  Judgement,
  LatestDestination,
  Region,
  RunError,
  StatusFile,
  Trip,
} from "../types";
import {
  addDays,
  formatDateTime,
  formatPctAbs,
  formatPctSigned,
  formatPrice,
  isoToMs,
  ymdToKstMs,
} from "./format";

// ---------- 판정 기준 ----------

export const CRITERIA: readonly Criterion[] = ["google_low", "offseason", "own_history", "google_60d"];

export const CRITERION_NAME: Record<Criterion, string> = {
  google_low: "Google 평소 가격",
  offseason: "비성수기",
  own_history: "수집 이력",
  google_60d: "최근 60일",
};

export type CriterionState = "matched" | "unmatched" | "not_evaluated";

export function criterionStates(judgement: Judgement): { criterion: Criterion; state: CriterionState }[] {
  return CRITERIA.map((criterion) => ({
    criterion,
    state: judgement.matched.includes(criterion)
      ? "matched"
      : judgement.evaluated.includes(criterion)
        ? "unmatched"
        : "not_evaluated",
  }));
}

export function criterionStateLabel(criterion: Criterion, state: CriterionState): string {
  const name = CRITERION_NAME[criterion];
  if (state === "matched") return `${name}: 해당`;
  if (state === "unmatched") return `${name}: 미해당`;
  return `${name}: 자료가 없어 평가하지 않음`;
}

/** 해당한 기준의 판정 문장(a → b → c → d 순서). SPEC 7장 문구 */
export function judgementSentences(fare: Fare): string[] {
  const j = fare.judgement;
  const sentences: string[] = [];
  for (const criterion of CRITERIA) {
    if (!j.matched.includes(criterion)) continue;
    if (criterion === "google_low") {
      const low = fare.insight?.typical_low_krw;
      sentences.push(
        low != null && j.pct_vs_typical_low != null
          ? `Google 평소 가격 하한(${formatPrice(low)})보다 ${formatPctAbs(j.pct_vs_typical_low)}% 저렴`
          : "Google 평소 가격 하한보다 저렴",
      );
    } else if (criterion === "offseason") {
      sentences.push(
        j.baseline_price_krw != null && j.pct_vs_baseline != null
          ? `비성수기 기준가(${formatPrice(j.baseline_price_krw)}) 이하(${formatPctSigned(j.pct_vs_baseline)})`
          : "비성수기 기준가 이하",
      );
    } else if (criterion === "own_history") {
      sentences.push(
        j.own_median_krw != null && j.pct_vs_own_median != null
          ? `수집 이력 중앙값(${formatPrice(j.own_median_krw)})보다 ${formatPctAbs(j.pct_vs_own_median)}% 저렴`
          : "수집 이력 중앙값보다 15% 이상 저렴",
      );
    } else {
      sentences.push(
        j.pct_vs_60d_min != null
          ? `최근 60일 가격 하위 10% 이하(60일 최저가 대비 ${formatPctSigned(j.pct_vs_60d_min)})`
          : "최근 60일 가격 하위 10% 이하",
      );
    }
  }
  return sentences;
}

/** offseason 에 해당하지 않아도 기준가가 있으면 표시하는 줄 */
export function baselineNote(fare: Fare): string | null {
  const j = fare.judgement;
  if (j.matched.includes("offseason")) return null;
  if (j.baseline_price_krw == null || j.pct_vs_baseline == null) return null;
  return `비성수기 기준가(${formatPrice(j.baseline_price_krw)}) 대비 ${formatPctSigned(j.pct_vs_baseline)}`;
}

// ---------- 알림 ----------

export function displayFare(alert: Alert): Fare {
  return alert.current_fare ?? alert.fare;
}

/** active 알림, 표시 가격 오름차순(같으면 데이터 순서 유지) */
export function activeAlerts(alerts: Alert[]): Alert[] {
  return alerts
    .filter((a) => a.status === "active")
    .map((alert, i) => ({ alert, i }))
    .sort((a, b) => displayFare(a.alert).price_krw - displayFare(b.alert).price_krw || a.i - b.i)
    .map((x) => x.alert);
}

/** replaced · ended 알림, 데이터 순서(최신순) */
export function pastAlerts(alerts: Alert[]): Alert[] {
  return alerts.filter((a) => a.status === "replaced" || a.status === "ended");
}

// ---------- 목적지 표 ----------

export const REGION_ORDER: readonly Region[] = ["국내", "일본", "중화권", "동남아", "대양주", "유럽", "미주", "기타"];

export type RegionFilterValue = Region | "전체";
export type SortKey = "price_asc" | "price_desc" | "name";

export function regionCounts(destinations: LatestDestination[]): { region: Region; count: number }[] {
  return REGION_ORDER.map((region) => ({
    region,
    count: destinations.filter((d) => d.region === region).length,
  })).filter((x) => x.count > 0);
}

export function filterDestinations(
  destinations: LatestDestination[],
  region: RegionFilterValue,
  dealsOnly: boolean,
): LatestDestination[] {
  return destinations.filter(
    (d) => (region === "전체" || d.region === region) && (!dealsOnly || d.deal !== null),
  );
}

/** 가격 없는 목적지는 항상 마지막. 값이 같으면 데이터 순서 유지 */
export function sortDestinations(destinations: LatestDestination[], key: SortKey): LatestDestination[] {
  return destinations
    .map((dest, i) => ({ dest, i }))
    .sort((a, b) => {
      const pa = a.dest.best?.price_krw ?? null;
      const pb = b.dest.best?.price_krw ?? null;
      if (pa === null || pb === null) {
        if (pa === null && pb === null) return a.i - b.i;
        return pa === null ? 1 : -1;
      }
      let diff = 0;
      if (key === "price_asc") diff = pa - pb;
      else if (key === "price_desc") diff = pb - pa;
      else diff = a.dest.city_ko.localeCompare(b.dest.city_ko, "ko");
      return diff || a.i - b.i;
    })
    .map((x) => x.dest);
}

// ---------- 목적지 선택 ----------

export function parseDestHash(hash: string): string | null {
  const match = /^#?dest=([A-Z]{3})$/.exec(hash);
  return match?.[1] ?? null;
}

/** 초기 선택: 해시 → 첫 active 알림 → 최저가 목적지 */
export function pickInitialDestination(
  hash: string,
  alerts: Alert[] | null,
  destinations: LatestDestination[],
): string | null {
  const codes = new Set(destinations.map((d) => d.destination));
  const fromHash = parseDestHash(hash);
  if (fromHash && codes.has(fromHash)) return fromHash;
  const firstActive = alerts?.find((a) => a.status === "active" && codes.has(a.destination));
  if (firstActive) return firstActive.destination;
  const cheapest = sortDestinations(destinations, "price_asc")[0];
  if (cheapest?.best) return cheapest.destination;
  return destinations[0]?.destination ?? null;
}

// ---------- 히트맵 ----------

export type HeatLevel = 1 | 2 | 3 | 4 | 5;

/** 가격 -> 단계(5 = 가장 낮은 가격 구간). 목적지별로 계산한다(DESIGN 3.2) */
export function heatLevels(prices: number[]): Map<number, HeatLevel> {
  const unique = [...new Set(prices)].sort((a, b) => a - b);
  const n = unique.length;
  const result = new Map<number, HeatLevel>();
  unique.forEach((price, r) => {
    const level = n >= 5 ? 5 - Math.floor((r * 5) / n) : 5 - r;
    result.set(price, Math.min(5, Math.max(1, level)) as HeatLevel);
  });
  return result;
}

export type HeatCell =
  | { kind: "price"; departDate: string; nights: number; combo: Combo; level: HeatLevel; isBest: boolean }
  | { kind: "unsearched"; departDate: string; nights: number }
  | { kind: "out"; departDate: string; nights: number };

export interface HeatGrid {
  nightsList: number[];
  rows: { departDate: string; cells: HeatCell[] }[];
  /** 조건 안(귀국일이 return_by 이전)인 칸 수 */
  inRangeCount: number;
  pricedCount: number;
  minPrice: number | null;
  maxPrice: number | null;
}

export function comboKey(departDate: string, nights: number): string {
  return `${departDate}|${nights}`;
}

export function buildHeatGrid(trip: Trip, combos: Combo[], best: Fare | null): HeatGrid {
  const nightsList: number[] = [];
  for (let n = trip.nights_min; n <= trip.nights_max; n += 1) nightsList.push(n);
  const dates: string[] = [];
  for (let d = trip.depart_from; d <= trip.depart_to && dates.length < 62; d = addDays(d, 1)) dates.push(d);

  const byKey = new Map<string, Combo>();
  for (const combo of combos) {
    if (typeof combo.price_krw === "number") byKey.set(comboKey(combo.depart_date, combo.nights), combo);
  }
  const inGrid = (c: Combo) => dates.includes(c.depart_date) && nightsList.includes(c.nights);
  const prices = [...byKey.values()].filter(inGrid).map((c) => c.price_krw);
  const levels = heatLevels(prices);
  const bestKey = best ? comboKey(best.depart_date, best.nights) : null;

  const rows = dates.map((departDate) => ({
    departDate,
    cells: nightsList.map((nights): HeatCell => {
      const key = comboKey(departDate, nights);
      const combo = byKey.get(key);
      if (combo) {
        return {
          kind: "price",
          departDate,
          nights,
          combo,
          level: levels.get(combo.price_krw) ?? 1,
          isBest: key === bestKey,
        };
      }
      if (addDays(departDate, nights) > trip.return_by) return { kind: "out", departDate, nights };
      return { kind: "unsearched", departDate, nights };
    }),
  }));

  return {
    nightsList,
    rows,
    inRangeCount: rows.reduce((n, row) => n + row.cells.filter((c) => c.kind !== "out").length, 0),
    pricedCount: prices.length,
    minPrice: prices.length ? Math.min(...prices) : null,
    maxPrice: prices.length ? Math.max(...prices) : null,
  };
}

// ---------- 수집 상태 ----------

export const ERROR_KIND_LABEL: Record<ErrorKind, string> = {
  bot_check: "봇 확인",
  network: "네트워크",
  parse: "해석 오류",
  hotel: "호텔 조회",
  telegram: "텔레그램 발송",
  other: "기타",
};

const ERROR_KIND_ORDER: readonly ErrorKind[] = ["bot_check", "network", "parse", "hotel", "telegram", "other"];

export function groupErrors(errors: RunError[]): { kind: ErrorKind; label: string; count: number }[] {
  return ERROR_KIND_ORDER.map((kind) => ({
    kind,
    label: ERROR_KIND_LABEL[kind],
    count: errors.filter((e) => e.kind === kind).length,
  })).filter((g) => g.count > 0);
}

export const STATE_LABEL = {
  ok: "정상",
  partial: "일부 실패",
  failed: "실패",
  stopped: "수집 중단",
} as const;

export interface Notice {
  id: "stopped" | "failed" | "old" | "sample";
  tone: "crit" | "warn";
  role: "alert" | "status";
  text: string;
}

export const STALE_HOURS = 14;

/** 안내 표시줄(DESIGN 5.10). 해당하는 항목을 순서대로 모두 반환한다 */
export function buildNotices(
  status: Pick<StatusFile, "state" | "consecutive_failures" | "last_success_at"> | null,
  index: Pick<IndexFile, "is_sample" | "generated_at">,
  nowMs: number,
): Notice[] {
  const notices: Notice[] = [];
  const lastSuccess = status?.last_success_at ? formatDateTime(status.last_success_at) : "없음";
  // 성공한 수집이 없으면 표시할 이전 가격도 없으므로 뒤 문장을 생략한다
  const priceNote = status?.last_success_at ? " 아래 가격은 그 시점의 값입니다." : "";
  if (status?.state === "stopped") {
    notices.push({
      id: "stopped",
      tone: "crit",
      role: "alert",
      text: `수집이 중단된 상태입니다. ${status.consecutive_failures}회 연속 실패했습니다. 마지막 성공: ${lastSuccess}.${priceNote}`,
    });
  }
  if (status?.state === "failed") {
    notices.push({
      id: "failed",
      tone: "crit",
      role: "alert",
      text: `최근 수집이 실패했습니다. 마지막 성공: ${lastSuccess}.${priceNote}`,
    });
  }
  if (!index.is_sample) {
    const generated = isoToMs(index.generated_at);
    const hours = Math.floor((nowMs - generated) / 3600000);
    if (!Number.isNaN(generated) && hours >= STALE_HOURS) {
      notices.push({
        id: "old",
        tone: "warn",
        role: "status",
        text: `마지막 수집 후 ${hours}시간이 지났습니다. 표시된 가격은 현재 가격과 다를 수 있습니다.`,
      });
    }
  } else {
    notices.push({
      id: "sample",
      tone: "warn",
      role: "status",
      text: "샘플 데이터를 표시하고 있습니다. 실제 수집 결과가 아닙니다.",
    });
  }
  return notices;
}

// ---------- 가격 추이 차트 ----------

export interface SeriesPoint {
  t: number;
  v: number;
}

export interface YDomain {
  min: number;
  max: number;
}

/**
 * 세로축 범위(DESIGN 5.7).
 * ① 두 선의 최솟값 lo, 최댓값 hi ② typical_low·기준가는 lo×0.75 이상이면 포함,
 * typical_high 는 hi×1.25 이하이면 포함 ③ 위아래에 범위의 8% 추가.
 */
export function computeYDomain(
  values: number[],
  typicalLow: number | null,
  typicalHigh: number | null,
  baseline: number | null,
): YDomain | null {
  if (values.length === 0) return null;
  const lineLo = Math.min(...values);
  const lineHi = Math.max(...values);
  let lo = lineLo;
  let hi = lineHi;
  for (const v of [typicalLow, baseline]) {
    if (v == null) continue;
    if (v < lineLo && v >= lineLo * 0.75) lo = Math.min(lo, v);
    if (v > lineHi && v <= lineHi * 1.25) hi = Math.max(hi, v);
  }
  if (typicalHigh != null && typicalHigh > lineHi && typicalHigh <= lineHi * 1.25) {
    hi = Math.max(hi, typicalHigh);
  }
  const span = hi - lo;
  const pad = span > 0 ? span * 0.08 : Math.max(lo * 0.05, 1000);
  return { min: lo - pad, max: hi + pad };
}

/** 만원 단위 배수로 맞춘 눈금 값. 눈금이 minCount 개 이상인 간격 중 가장 넓은 간격을 사용한다 */
export function niceTicks(min: number, max: number, minCount = 3): number[] {
  if (!(max > min)) return [];
  const ticksFor = (step: number) => {
    const ticks: number[] = [];
    for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(v);
    return ticks;
  };
  let chosen = ticksFor(10000);
  for (let magnitude = 10000; magnitude <= max; magnitude *= 10) {
    for (const m of [1, 2, 5]) {
      const ticks = ticksFor(m * magnitude);
      if (ticks.length >= minCount) chosen = ticks;
    }
  }
  return chosen;
}

export function timeTicks(min: number, max: number, count: number): number[] {
  if (!(max > min) || count < 2) return [min];
  return Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1));
}

export interface AxisTick {
  t: number;
  label: string;
}

/** 가로축 눈금 글자(월/일) 1개의 폭(px, 12px 글자 기준) */
export const AXIS_LABEL_W = 38;

/**
 * 가로축 날짜 눈금.
 * - 눈금 사이 간격이 글자 폭 1.5배 + 8px 보다 좁으면 눈금 수를 줄인다(최소 2개).
 * - 같은 날짜가 여러 번 표시되지 않도록 날짜가 같은 눈금은 1개만 남긴다(마지막 눈금 우선).
 */
export function axisDateTicks(
  min: number,
  max: number,
  maxCount: number,
  plotWidth: number,
  format: (ms: number) => string,
): AxisTick[] {
  const fit = Math.floor(plotWidth / (AXIS_LABEL_W * 1.5 + 8)) + 1;
  const count = Math.max(2, Math.min(maxCount, fit));
  const ticks = timeTicks(min, max, count).map((t) => ({ t, label: format(t) }));
  const lastLabel = ticks[ticks.length - 1]?.label;
  const out: AxisTick[] = [];
  ticks.forEach((tick, i) => {
    const isLast = i === ticks.length - 1;
    if (!isLast && tick.label === lastLabel) return;
    if (out.length > 0 && out[out.length - 1]!.label === tick.label) return;
    out.push(tick);
  });
  return out;
}

/** t 에 가장 가까운 점의 인덱스. 점이 없으면 -1 */
export function nearestIndex(points: SeriesPoint[], t: number): number {
  let bestIndex = -1;
  let bestDistance = Infinity;
  points.forEach((p, i) => {
    const distance = Math.abs(p.t - t);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = i;
    }
  });
  return bestIndex;
}

export interface ChartModel {
  own: SeriesPoint[];
  google: SeriesPoint[];
  xMin: number;
  xMax: number;
  y: YDomain;
  yTicks: number[];
  band: { low: number; high: number } | null;
  baseline: number | null;
  baselineInRange: boolean;
}

export function buildChartModel(input: {
  points: HistoryPoint[];
  insight: Insight | null;
  baseline: number | null;
  generatedAt: string;
}): ChartModel | null {
  const own = input.points
    .filter((p) => typeof p.price_krw === "number")
    .map((p) => ({ t: isoToMs(p.collected_at), v: p.price_krw }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t);
  const google = (input.insight?.history ?? [])
    .map((p) => ({ t: ymdToKstMs(p.date), v: p.price_krw }))
    .filter((p) => !Number.isNaN(p.t) && typeof p.v === "number")
    .sort((a, b) => a.t - b.t);
  const all = [...own, ...google];
  if (all.length === 0) return null;

  const typicalLow = input.insight?.typical_low_krw ?? null;
  const typicalHigh = input.insight?.typical_high_krw ?? null;
  const y = computeYDomain(
    all.map((p) => p.v),
    typicalLow,
    typicalHigh,
    input.baseline,
  );
  if (!y) return null;

  const times = all.map((p) => p.t);
  const generated = isoToMs(input.generatedAt);
  let xMin = Math.min(...times);
  let xMax = Math.max(...times, Number.isNaN(generated) ? -Infinity : generated);
  if (xMax <= xMin) {
    xMin -= 43200000;
    xMax += 43200000;
  }

  return {
    own,
    google,
    xMin,
    xMax,
    y,
    yTicks: niceTicks(y.min, y.max),
    band: typicalLow != null && typicalHigh != null ? { low: typicalLow, high: typicalHigh } : null,
    baseline: input.baseline,
    baselineInRange: input.baseline != null && input.baseline >= y.min && input.baseline <= y.max,
  };
}

export function chartSummary(cityKo: string, model: ChartModel | null): string {
  if (!model) return `${cityKo} 가격 추이. 표시할 이력이 없습니다.`;
  const parts = [`${cityKo} 가격 추이.`];
  if (model.own.length > 0) {
    const values = model.own.map((p) => p.v);
    const last = values[values.length - 1] as number;
    parts.push(
      `수집 이력 ${model.own.length}건, 최저 ${formatPrice(Math.min(...values))}, 최고 ${formatPrice(Math.max(...values))}, 현재 ${formatPrice(last)}.`,
    );
  }
  if (model.google.length > 0) {
    const values = model.google.map((p) => p.v);
    parts.push(
      `Google 최근 60일 ${model.google.length}건, 최저 ${formatPrice(Math.min(...values))}, 최고 ${formatPrice(Math.max(...values))}.`,
    );
  }
  return parts.join(" ");
}
