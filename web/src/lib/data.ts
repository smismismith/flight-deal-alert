// 데이터 읽기(SPEC 6.3절).
// 1) {base}data/index.json  2) 실패 시 개발 모드 또는 ?sample=1 일 때만 {base}sample-data/
// 3) 운영 환경에서 실패하면 샘플로 대체하지 않고 오류를 반환한다.
import type { AlertsFile, BaselineFile, HistoryFile, IndexFile, LatestFile, StatusFile } from "../types";

export interface LoadError {
  /** 화면에 표시할 파일 이름. 예: "index.json" */
  file: string;
  /** "404", "네트워크 오류", "JSON 오류", "형식 오류" */
  reason: string;
}

export type FileResult<T> = { ok: true; data: T } | { ok: false; error: LoadError };

export type DataSource = "data" | "sample";

export interface Dataset {
  source: DataSource;
  /** 파일을 읽은 폴더 주소(끝에 / 포함). history 파일을 읽을 때 사용한다 */
  dir: string;
  index: IndexFile;
  latest: FileResult<LatestFile>;
  alerts: FileResult<AlertsFile>;
  status: FileResult<StatusFile>;
  baseline: FileResult<BaselineFile>;
}

/** index.json 을 읽지 못해도 status.json 은 별도로 읽어 수집 상태를 표시할 수 있게 한다 */
export type LoadOutcome =
  | { ok: true; dataset: Dataset }
  | { ok: false; error: LoadError; status?: FileResult<StatusFile> };

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface LoadOptions {
  /** import.meta.env.BASE_URL */
  baseUrl: string;
  /** import.meta.env.DEV */
  dev: boolean;
  /** window.location.search */
  search: string;
  fetchImpl?: FetchLike;
}

type Guard = (value: unknown) => boolean;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const hasArray =
  (key: string): Guard =>
  (value) =>
    isRecord(value) && Array.isArray(value[key]);

const guards = {
  index: hasArray("destinations"),
  latest: (v: unknown) => hasArray("destinations")(v) && isRecord((v as Record<string, unknown>).trip),
  alerts: hasArray("alerts"),
  status: (v: unknown) => hasArray("runs")(v) && typeof (v as Record<string, unknown>).state === "string",
  baseline: hasArray("entries"),
  history: hasArray("points"),
} satisfies Record<string, Guard>;

export async function fetchJson<T>(
  url: string,
  file: string,
  guard: Guard,
  fetchImpl: FetchLike,
): Promise<FileResult<T>> {
  let response: Response;
  try {
    response = await fetchImpl(url, { cache: "no-store" });
  } catch {
    return { ok: false, error: { file, reason: "네트워크 오류" } };
  }
  if (!response.ok) {
    return { ok: false, error: { file, reason: String(response.status) } };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { ok: false, error: { file, reason: "JSON 오류" } };
  }
  if (!guard(body)) {
    return { ok: false, error: { file, reason: "형식 오류" } };
  }
  return { ok: true, data: body as T };
}

export function isSampleRequested(search: string): boolean {
  return new URLSearchParams(search).get("sample") === "1";
}

function joinDir(baseUrl: string, folder: string): string {
  const base = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  return `${base}${folder}/`;
}

async function loadFromDir(
  dir: string,
  source: DataSource,
  fetchImpl: FetchLike,
): Promise<LoadOutcome> {
  const index = await fetchJson<IndexFile>(`${dir}index.json`, "index.json", guards.index, fetchImpl);
  if (!index.ok) {
    const status = await fetchJson<StatusFile>(`${dir}status.json`, "status.json", guards.status, fetchImpl);
    return { ok: false, error: index.error, status };
  }
  const [latest, alerts, status, baseline] = await Promise.all([
    fetchJson<LatestFile>(`${dir}latest.json`, "latest.json", guards.latest, fetchImpl),
    fetchJson<AlertsFile>(`${dir}alerts.json`, "alerts.json", guards.alerts, fetchImpl),
    fetchJson<StatusFile>(`${dir}status.json`, "status.json", guards.status, fetchImpl),
    fetchJson<BaselineFile>(`${dir}baseline.json`, "baseline.json", guards.baseline, fetchImpl),
  ]);
  return { ok: true, dataset: { source, dir, index: index.data, latest, alerts, status, baseline } };
}

export async function loadDataset(options: LoadOptions): Promise<LoadOutcome> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const sampleDir = joinDir(options.baseUrl, "sample-data");
  if (isSampleRequested(options.search)) {
    return loadFromDir(sampleDir, "sample", fetchImpl);
  }
  const real = await loadFromDir(joinDir(options.baseUrl, "data"), "data", fetchImpl);
  if (real.ok || !options.dev) return real;
  return loadFromDir(sampleDir, "sample", fetchImpl);
}

/** history_file 이 null 이면 요청하지 않고 data: null 을 반환한다. */
export async function loadHistory(
  dir: string,
  historyFile: string | null,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): Promise<FileResult<HistoryFile | null>> {
  if (historyFile === null) return { ok: true, data: null };
  if (!/^history\/[A-Z]{3}\.json$/.test(historyFile)) {
    return { ok: false, error: { file: historyFile, reason: "형식 오류" } };
  }
  return fetchJson<HistoryFile>(`${dir}${historyFile}`, historyFile, guards.history, fetchImpl);
}
