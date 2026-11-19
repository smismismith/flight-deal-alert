import { describe, expect, it } from "vitest";
import { isSampleRequested, loadDataset, loadHistory, type FetchLike } from "./data";

type Routes = Record<string, unknown | (() => Response | Promise<Response>)>;

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function mockFetch(routes: Routes): { fetchImpl: FetchLike; calls: { url: string; init?: RequestInit }[] } {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchImpl: FetchLike = async (url, init) => {
    calls.push({ url, init });
    const route = routes[url];
    if (route === undefined) return new Response("Not Found", { status: 404 });
    if (typeof route === "function") return (route as () => Response | Promise<Response>)();
    return jsonResponse(route);
  };
  return { fetchImpl, calls };
}

function folder(dir: string, isSample: boolean): Routes {
  return {
    [`${dir}index.json`]: { schema_version: 1, is_sample: isSample, destinations: [] },
    [`${dir}latest.json`]: { schema_version: 1, trip: {}, destinations: [] },
    [`${dir}alerts.json`]: { schema_version: 1, alerts: [] },
    [`${dir}status.json`]: { schema_version: 1, state: "ok", runs: [] },
    [`${dir}baseline.json`]: { schema_version: 1, entries: [] },
  };
}

describe("loadDataset", () => {
  it("data/ 가 있으면 data/ 를 읽고 no-store 로 요청한다", async () => {
    const { fetchImpl, calls } = mockFetch({ ...folder("./data/", false), ...folder("./sample-data/", true) });
    const outcome = await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl });
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.dataset.source).toBe("data");
    expect(outcome.dataset.dir).toBe("./data/");
    expect(outcome.dataset.index.is_sample).toBe(false);
    expect(outcome.dataset.latest.ok && outcome.dataset.alerts.ok && outcome.dataset.status.ok).toBe(true);
    expect(calls[0]?.url).toBe("./data/index.json");
    expect(calls.every((c) => c.init?.cache === "no-store")).toBe(true);
    expect(calls.some((c) => c.url.includes("sample-data"))).toBe(false);
    expect(calls.some((c) => c.url.includes("history"))).toBe(false);
  });

  it("개발 모드에서 data/ 가 없으면 sample-data/ 를 읽는다", async () => {
    const { fetchImpl } = mockFetch(folder("./sample-data/", true));
    const outcome = await loadDataset({ baseUrl: "./", dev: true, search: "", fetchImpl });
    expect(outcome.ok && outcome.dataset.source).toBe("sample");
    expect(outcome.ok && outcome.dataset.index.is_sample).toBe(true);
  });

  it("개발 서버가 index.html 을 대신 응답해도(JSON 오류) 샘플로 대체한다", async () => {
    const { fetchImpl } = mockFetch({
      ...folder("./sample-data/", true),
      "./data/index.json": () => new Response("<!doctype html>", { status: 200 }),
    });
    const outcome = await loadDataset({ baseUrl: "./", dev: true, search: "", fetchImpl });
    expect(outcome.ok && outcome.dataset.source).toBe("sample");
  });

  it("운영 환경에서 data/ 가 없으면 샘플로 대체하지 않고 오류를 반환한다", async () => {
    const { fetchImpl, calls } = mockFetch(folder("./sample-data/", true));
    const outcome = await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl });
    expect(outcome).toMatchObject({ ok: false, error: { file: "index.json", reason: "404" } });
    // index.json 실패 후 status.json 만 추가로 읽는다(샘플 폴더는 요청하지 않는다)
    expect(calls.map((c) => c.url)).toEqual(["./data/index.json", "./data/status.json"]);
  });

  it("index.json 을 읽지 못해도 status.json 은 읽어 오류 결과에 포함한다", async () => {
    const status = { schema_version: 1, state: "failed", runs: [], last_run: null };
    const { fetchImpl } = mockFetch({ "./data/status.json": status });
    const outcome = await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl });
    expect(outcome).toEqual({
      ok: false,
      error: { file: "index.json", reason: "404" },
      status: { ok: true, data: status },
    });
  });

  it("?sample=1 이면 data/ 요청을 생략하고 샘플을 읽는다", async () => {
    const { fetchImpl, calls } = mockFetch({ ...folder("./data/", false), ...folder("./sample-data/", true) });
    const outcome = await loadDataset({ baseUrl: "./", dev: false, search: "?sample=1", fetchImpl });
    expect(outcome.ok && outcome.dataset.source).toBe("sample");
    expect(calls.some((c) => c.url.startsWith("./data/"))).toBe(false);
  });

  it("네트워크 오류와 JSON 오류를 구분해 기록한다", async () => {
    const network = mockFetch({
      "./data/index.json": () => {
        throw new TypeError("failed");
      },
    });
    expect(await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl: network.fetchImpl })).toMatchObject({
      ok: false,
      error: { file: "index.json", reason: "네트워크 오류" },
    });
    const broken = mockFetch({ "./data/index.json": () => new Response("{", { status: 200 }) });
    expect(await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl: broken.fetchImpl })).toMatchObject({
      ok: false,
      error: { file: "index.json", reason: "JSON 오류" },
    });
    const shape = mockFetch({ "./data/index.json": { schema_version: 1 } });
    expect(await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl: shape.fetchImpl })).toMatchObject({
      ok: false,
      error: { file: "index.json", reason: "형식 오류" },
    });
  });

  it("index.json 외의 파일이 실패하면 해당 파일만 오류로 반환한다", async () => {
    const routes = folder("./data/", false);
    delete routes["./data/alerts.json"];
    const { fetchImpl } = mockFetch(routes);
    const outcome = await loadDataset({ baseUrl: "./", dev: false, search: "", fetchImpl });
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.dataset.alerts).toEqual({ ok: false, error: { file: "alerts.json", reason: "404" } });
    expect(outcome.dataset.latest.ok).toBe(true);
    expect(outcome.dataset.status.ok).toBe(true);
  });

  it("하위 경로 base 에서도 상대 주소로 요청한다", async () => {
    const { fetchImpl, calls } = mockFetch(folder("/flight_search/data/", false));
    const outcome = await loadDataset({ baseUrl: "/flight_search", dev: false, search: "", fetchImpl });
    expect(outcome.ok).toBe(true);
    expect(calls[0]?.url).toBe("/flight_search/data/index.json");
  });
});

describe("loadHistory", () => {
  it("history_file 경로로 요청한다", async () => {
    const { fetchImpl, calls } = mockFetch({ "./data/history/DAD.json": { points: [] } });
    const result = await loadHistory("./data/", "history/DAD.json", fetchImpl);
    expect(result.ok).toBe(true);
    expect(calls[0]?.url).toBe("./data/history/DAD.json");
  });
  it("history_file 이 null 이면 요청하지 않는다", async () => {
    const { fetchImpl, calls } = mockFetch({});
    expect(await loadHistory("./data/", null, fetchImpl)).toEqual({ ok: true, data: null });
    expect(calls).toHaveLength(0);
  });
  it("형식이 다른 경로는 요청하지 않는다", async () => {
    const { fetchImpl, calls } = mockFetch({});
    const result = await loadHistory("./data/", "../secret.json", fetchImpl);
    expect(result.ok).toBe(false);
    expect(calls).toHaveLength(0);
  });
  it("실패하면 오류를 반환한다", async () => {
    const { fetchImpl } = mockFetch({});
    expect(await loadHistory("./data/", "history/SYD.json", fetchImpl)).toEqual({
      ok: false,
      error: { file: "history/SYD.json", reason: "404" },
    });
  });
});

describe("isSampleRequested", () => {
  it("sample=1 만 인정한다", () => {
    expect(isSampleRequested("?sample=1")).toBe(true);
    expect(isSampleRequested("?a=b&sample=1")).toBe(true);
    expect(isSampleRequested("?sample=0")).toBe(false);
    expect(isSampleRequested("")).toBe(false);
  });
});
