// 표기 형식(DESIGN 4장). 모든 함수는 기기 시간대와 관계없이 같은 결과를 반환한다.
import type { Level } from "../types";

const numberFormat = new Intl.NumberFormat("ko-KR");
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

export function formatNumber(n: number): string {
  return numberFormat.format(n);
}

/** 338000 -> "338,000원" */
export function formatPrice(n: number): string {
  return `${numberFormat.format(n)}원`;
}

/** 히트맵 칸: 만원 단위 소수 1자리(천원 미만 반올림). 338000 -> "33.8" */
export function formatManwon(n: number): string {
  return (Math.round(n / 1000) / 10).toFixed(1);
}

export interface YmdParts {
  y: number;
  m: number;
  d: number;
}

/** "YYYY-MM-DD" 를 숫자로 분리한다. new Date("YYYY-MM-DD") 를 사용하지 않는다. */
export function parseYmd(ymd: string): YmdParts | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!match) return null;
  return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
}

function ymdToUtcMs(ymd: string): number | null {
  const p = parseYmd(ymd);
  return p ? Date.UTC(p.y, p.m - 1, p.d) : null;
}

/** 0(일) ~ 6(토). 형식이 틀리면 null */
export function weekdayIndex(ymd: string): number | null {
  const ms = ymdToUtcMs(ymd);
  return ms === null ? null : new Date(ms).getUTCDay();
}

export function isWeekend(ymd: string): boolean {
  const w = weekdayIndex(ymd);
  return w === 0 || w === 6;
}

/** "2026-12-21" -> "12/21(월)" */
export function formatDate(ymd: string): string {
  const p = parseYmd(ymd);
  const w = weekdayIndex(ymd);
  if (!p || w === null) return ymd;
  return `${p.m}/${p.d}(${WEEKDAYS[w]})`;
}

/** "2026-12-21" -> "12/21" */
export function formatDateShort(ymd: string): string {
  const p = parseYmd(ymd);
  return p ? `${p.m}/${p.d}` : ymd;
}

/** 접근성 이름용: "12월 21일 월요일" */
export function formatDateSpoken(ymd: string): string {
  const p = parseYmd(ymd);
  const w = weekdayIndex(ymd);
  if (!p || w === null) return ymd;
  return `${p.m}월 ${p.d}일 ${WEEKDAYS[w]}요일`;
}

/** "12/21(월) ~ 12/25(금) · 4박" */
export function formatTrip(departDate: string, returnDate: string, nights: number): string {
  return `${formatDate(departDate)} ~ ${formatDate(returnDate)} · ${nights}박`;
}

/** "12/21 출발 · 4박" */
export function formatTripShort(departDate: string, nights: number): string {
  return `${formatDateShort(departDate)} 출발 · ${nights}박`;
}

export function addDays(ymd: string, days: number): string {
  const ms = ymdToUtcMs(ymd);
  if (ms === null) return ymd;
  return new Date(ms + days * 86400000).toISOString().slice(0, 10);
}

/** b - a (일) */
export function diffDays(a: string, b: string): number {
  const am = ymdToUtcMs(a);
  const bm = ymdToUtcMs(b);
  if (am === null || bm === null) return NaN;
  return Math.round((bm - am) / 86400000);
}

/** ISO 시각 -> epoch ms. 해석할 수 없으면 NaN */
export function isoToMs(iso: string): number {
  return Date.parse(iso);
}

/** "YYYY-MM-DD"(KST 날짜) -> KST 자정의 epoch ms */
export function ymdToKstMs(ymd: string): number {
  const ms = ymdToUtcMs(ymd);
  return ms === null ? NaN : ms - KST_OFFSET_MS;
}

function kstParts(ms: number): { m: number; d: number; hh: number; mm: number } {
  const date = new Date(ms + KST_OFFSET_MS);
  return {
    m: date.getUTCMonth() + 1,
    d: date.getUTCDate(),
    hh: date.getUTCHours(),
    mm: date.getUTCMinutes(),
  };
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** ISO 시각 -> "11/19 09:24"(KST). 형식이 틀리면 "-" */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const ms = isoToMs(iso);
  if (Number.isNaN(ms)) return "-";
  const p = kstParts(ms);
  return `${p.m}/${p.d} ${pad2(p.hh)}:${pad2(p.mm)}`;
}

/** ISO 시각 -> "09:24"(KST) */
export function formatClock(iso: string): string {
  const ms = isoToMs(iso);
  if (Number.isNaN(ms)) return "-";
  const p = kstParts(ms);
  return `${pad2(p.hh)}:${pad2(p.mm)}`;
}

/** epoch ms -> "11/5"(KST). 차트 가로축 */
export function formatAxisDate(ms: number): string {
  const p = kstParts(ms);
  return `${p.m}/${p.d}`;
}

/** 295 -> "4시간 55분", 45 -> "45분", 120 -> "2시간" */
export function formatDuration(minutes: number): string {
  const total = Math.max(0, Math.floor(minutes));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m}분`;
  if (m === 0) return `${h}시간`;
  return `${h}시간 ${m}분`;
}

/** 수집 소요 시간: 4957초 -> "1시간 22분"(초는 버림) */
export function formatRunDuration(seconds: number): string {
  return formatDuration(Math.floor(Math.max(0, seconds) / 60));
}

/** 0 -> "직항", 1 -> "경유 1회" */
export function formatStops(stops: number): string {
  return stops <= 0 ? "직항" : `경유 ${stops}회`;
}

/** -20.1 -> "20.1"(절댓값, 소수 1자리) */
export function formatPctAbs(pct: number): string {
  return Math.abs(pct).toFixed(1);
}

/** 12.8 -> "+12.8%", -10 -> "-10.0%", 0 -> "0.0%" */
export function formatPctSigned(pct: number): string {
  const text = Math.abs(pct).toFixed(1);
  if (Number(text) === 0) return "0.0%";
  return `${pct > 0 ? "+" : "-"}${text}%`;
}

export function formatRating(rating: number): string {
  return `평점 ${rating.toFixed(1)}`;
}

/** "다낭 (베트남)", 국내는 "제주" */
export function formatDestination(cityKo: string, countryKo: string, isDomestic: boolean): string {
  return isDomestic ? cityKo : `${cityKo} (${countryKo})`;
}

export function levelLabel(level: Level | null | undefined): string {
  switch (level) {
    case "low":
      return "평소보다 낮음";
    case "typical":
      return "평소 수준";
    case "high":
      return "평소보다 높음";
    default:
      return "수준 정보 없음";
  }
}
