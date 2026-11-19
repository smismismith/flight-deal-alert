// schemas/*.schema.json 과 같은 구조의 타입 정의.
// 모든 객체는 스키마에서 additionalProperties: false 이고 아래 필드는 모두 required 이다.

export type IsoKst = string; // YYYY-MM-DDTHH:MM:SS+09:00
export type Ymd = string; // YYYY-MM-DD
export type RunId = string; // YYYYMMDDTHHMMSS
export type Iata = string; // ^[A-Z]{3}$
export type Hhmm = string; // HH:MM

export type Region = "국내" | "일본" | "중화권" | "동남아" | "대양주" | "유럽" | "미주" | "기타";
export type Level = "low" | "typical" | "high";
export type Criterion = "google_low" | "offseason" | "own_history" | "google_60d";

// ---------- index.json ----------
export interface IndexDestination {
  destination: Iata;
  origin: Iata;
  city_ko: string;
  country_ko: string;
  region: Region;
  is_domestic: boolean;
  best_price_krw: number | null;
  is_deal: boolean;
  history_file: string | null;
}

export interface IndexFile {
  schema_version: 1;
  generated_at: IsoKst;
  run_id: RunId;
  is_sample: boolean;
  destinations: IndexDestination[];
}

// ---------- 공통: fare / insight / judgement ----------
export interface InsightHistoryPoint {
  date: Ymd;
  price_krw: number;
}

export interface Insight {
  google_code: number | null;
  current_price_krw: number | null;
  usual_price_krw: number | null;
  typical_low_krw: number | null;
  typical_high_krw: number | null;
  level: Level | null;
  history_min_krw: number | null;
  history_p10_krw: number | null;
  history_count: number;
  history: InsightHistoryPoint[];
}

export interface Judgement {
  evaluated: Criterion[];
  matched: Criterion[];
  matched_count: number;
  is_deal: boolean;
  baseline_price_krw: number | null;
  pct_vs_baseline: number | null;
  own_median_krw: number | null;
  own_samples: number;
  pct_vs_own_median: number | null;
  pct_vs_typical_low: number | null;
  pct_vs_60d_min: number | null;
}

export interface Fare {
  origin: Iata;
  destination: Iata;
  city_ko: string;
  country_ko: string;
  region: Region;
  depart_date: Ymd;
  return_date: Ymd;
  nights: number;
  is_representative: boolean;
  price_krw: number;
  airline_code: string | null;
  airlines: string[];
  stops: number;
  duration_minutes: number | null;
  depart_time: Hhmm | null;
  arrive_time: Hhmm | null;
  arrive_date: Ymd | null;
  search_url: string;
  insight: Insight | null;
  judgement: Judgement;
  collected_at: IsoKst;
}

// ---------- latest.json ----------
export interface Combo {
  depart_date: Ymd;
  return_date: Ymd;
  nights: number;
  is_representative: boolean;
  price_krw: number;
  airlines: string[];
  stops: number;
  level: Level | null;
  matched: Criterion[];
  is_deal: boolean;
  search_url: string;
  collected_at: IsoKst;
}

export interface Trip {
  adults: number;
  depart_from: Ymd;
  depart_to: Ymd;
  return_by: Ymd;
  nights_min: number;
  nights_max: number;
}

export interface LatestDestination {
  origin: Iata;
  destination: Iata;
  city_ko: string;
  country_ko: string;
  region: Region;
  is_domestic: boolean;
  expanded: boolean;
  stale: boolean;
  last_success_at: IsoKst | null;
  best: Fare | null;
  deal: Fare | null;
  combos: Combo[];
}

export interface LatestFile {
  schema_version: 1;
  generated_at: IsoKst;
  run_id: RunId;
  trip: Trip;
  destinations: LatestDestination[];
}

// ---------- history/{DEST}.json ----------
export interface HistoryPoint {
  collected_at: IsoKst;
  run_id: RunId;
  price_krw: number;
  rep_price_krw: number | null;
  depart_date: Ymd;
  return_date: Ymd;
  nights: number;
  airlines: string[];
  stops: number;
  combos_checked: number;
}

export interface HistoryFile {
  schema_version: 1;
  origin: Iata;
  destination: Iata;
  city_ko: string;
  country_ko: string;
  region: Region;
  points: HistoryPoint[];
}

// ---------- baseline.json ----------
export interface BaselineEntry {
  origin: Iata;
  destination: Iata;
  nights: number;
  depart_date: Ymd;
  return_date: Ymd;
  /** 조회 결과가 없었던 노선·박수는 null */
  price_krw: number | null;
  airlines: string[];
  stops: number | null;
  search_url: string;
  collected_at: IsoKst;
  /** 기존 가격을 유지한 채 결과 없음 응답을 받은 마지막 시각(선택 항목) */
  checked_at?: IsoKst;
}

export interface BaselineFile {
  schema_version: 1;
  updated_at: IsoKst;
  entries: BaselineEntry[];
}

// ---------- alerts.json ----------
export type AlertStatus = "active" | "replaced" | "ended";
export type AlertKind = "new" | "realert";

export interface AlertNotification {
  channel: "telegram";
  sent: boolean;
  sent_at: IsoKst | null;
  attempts: number;
  error: string | null;
}

export interface HotelItem {
  name: string;
  rate_per_night_krw: number | null;
  total_rate_krw: number | null;
  rating: number | null;
  deal: string | null;
  link: string | null;
}

export interface Hotels {
  source: "serpapi" | "links";
  query: string;
  check_in: Ymd;
  check_out: Ymd;
  nights: number;
  fetched_at: IsoKst | null;
  links: { google_hotels: string; agoda: string };
  items: HotelItem[];
}

export interface Alert {
  id: string;
  origin: Iata;
  destination: Iata;
  city_ko: string;
  country_ko: string;
  region: Region;
  status: AlertStatus;
  kind: AlertKind;
  created_at: IsoKst;
  ended_at: IsoKst | null;
  alerted_price_krw: number;
  previous_alerted_price_krw: number | null;
  fare: Fare;
  current_fare: Fare | null;
  current_checked_at: IsoKst;
  notification: AlertNotification;
  hotels: Hotels;
}

export interface AlertsFile {
  schema_version: 1;
  updated_at: IsoKst;
  alerts: Alert[];
}

// ---------- status.json ----------
export type StatusState = "ok" | "partial" | "failed" | "stopped";
export type RunResult = "ok" | "partial" | "failed";
export type ErrorKind = "bot_check" | "network" | "parse" | "hotel" | "telegram" | "other";

export interface RunError {
  destination: Iata | null;
  depart_date: Ymd | null;
  return_date: Ymd | null;
  kind: ErrorKind;
  message: string;
}

export interface RunQueries {
  planned: number;
  attempted: number;
  succeeded: number;
  no_result: number;
  failed: number;
  bot_checks: number;
  retries: number;
  skipped: number;
}

export interface Run {
  run_id: RunId;
  started_at: IsoKst;
  finished_at: IsoKst;
  duration_seconds: number;
  result: RunResult;
  queries: RunQueries;
  baseline_queries: number;
  destinations_total: number;
  destinations_succeeded: number;
  failed_destinations: Iata[];
  expanded_destinations: Iata[];
  deals_found: number;
  alerts_sent: number;
  hotel_api_calls: number;
  telegram_enabled: boolean;
  serpapi_enabled: boolean;
  aborted_reason: string | null;
  errors: RunError[];
}

export interface StatusFile {
  schema_version: 1;
  updated_at: IsoKst;
  state: StatusState;
  consecutive_failures: number;
  stop_notice_sent: boolean;
  last_success_at: IsoKst | null;
  serpapi: { month: string; calls: number };
  last_run: Run;
  runs: Run[];
}
