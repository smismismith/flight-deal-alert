import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadDataset, type LoadOutcome } from "./lib/data";
import {
  STATE_LABEL,
  activeAlerts,
  buildNotices,
  parseDestHash,
  pastAlerts,
  pickInitialDestination,
} from "./lib/derive";
import { formatDateTime } from "./lib/format";
import { DealCard, DealsEmpty } from "./components/Deals";
import { DestinationTable, rowId } from "./components/DestinationTable";
import { DestinationDetail } from "./components/Detail";
import { AppHeader, NoticeBanner } from "./components/Header";
import { PastAlerts } from "./components/PastAlerts";
import { SectionError, SectionHeading } from "./components/common";

const DESKTOP_QUERY = "(min-width: 1024px)";

function scrollBehavior(): ScrollBehavior {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

export function App() {
  const [outcome, setOutcome] = useState<LoadOutcome | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const pendingScroll = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setOutcome(null);
    loadDataset({
      baseUrl: import.meta.env.BASE_URL,
      dev: import.meta.env.DEV,
      search: window.location.search,
    }).then((result) => {
      if (cancelled) return;
      setNowMs(Date.now());
      setOutcome(result);
    });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const dataset = outcome?.ok ? outcome.dataset : null;
  const latest = dataset?.latest.ok ? dataset.latest.data : null;
  const alerts = dataset?.alerts.ok ? dataset.alerts.data.alerts : null;
  const status = dataset?.status.ok ? dataset.status.data : null;
  // index.json 을 읽지 못한 경우에도 status.json 을 읽었으면 수집 상태를 표시한다
  const failStatus = outcome && !outcome.ok && outcome.status?.ok ? outcome.status : undefined;
  const failRun = failStatus?.data.last_run ?? null;

  // 초기 선택: 해시 → 첫 active 알림 → 최저가 목적지
  useEffect(() => {
    if (!latest) return;
    setSelected((current) => {
      if (current && latest.destinations.some((d) => d.destination === current)) return current;
      return pickInitialDestination(window.location.hash, alerts, latest.destinations);
    });
  }, [latest, alerts]);

  useEffect(() => {
    if (!latest) return;
    const onHashChange = () => {
      const code = parseDestHash(window.location.hash);
      if (code && latest.destinations.some((d) => d.destination === code)) setSelected(code);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [latest]);

  const selectDestination = useCallback(
    (code: string, scroll: boolean) => {
      if (!latest?.destinations.some((d) => d.destination === code)) return;
      setSelected(code);
      window.history.replaceState(null, "", `#dest=${code}`);
      if (scroll && !window.matchMedia(DESKTOP_QUERY).matches) pendingScroll.current = true;
    },
    [latest],
  );

  // S·M 구간: 선택 후 상세 제목으로 스크롤하고 포커스를 설정한다
  useEffect(() => {
    if (!pendingScroll.current) return;
    pendingScroll.current = false;
    const heading = headingRef.current;
    if (!heading) return;
    heading.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    heading.focus({ preventScroll: true });
  });

  const backToList = useCallback(() => {
    if (!selected) return;
    const row = document.getElementById(rowId(selected)) ?? document.getElementById("table-title");
    if (!row) return;
    row.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
    row.querySelector<HTMLButtonElement>("button.dest-button")?.focus({ preventScroll: true });
  }, [selected]);

  const cityOf = useCallback(
    (code: string) =>
      (latest?.destinations ?? dataset?.index.destinations ?? []).find((d) => d.destination === code)?.city_ko ?? null,
    [latest, dataset],
  );

  const notices = useMemo(
    () => (dataset ? buildNotices(status, dataset.index, nowMs) : []),
    [dataset, status, nowMs],
  );
  const active = useMemo(() => (alerts ? activeAlerts(alerts) : []), [alerts]);
  const past = useMemo(() => (alerts ? pastAlerts(alerts) : []), [alerts]);
  const selectedDest = latest?.destinations.find((d) => d.destination === selected) ?? null;
  const latestOf = (code: string) => latest?.destinations.find((d) => d.destination === code) ?? null;

  return (
    <div className="page">
      <AppHeader
        trip={latest?.trip ?? null}
        isSample={dataset?.index.is_sample === true}
        status={outcome === null ? null : dataset ? dataset.status : failStatus}
        cityOf={cityOf}
        onSelect={(code) => selectDestination(code, true)}
      />
      <NoticeBanner notices={notices} />

      <main aria-busy={outcome === null}>
        {outcome === null && (
          <div className="layout">
            <section className="section section-deals" aria-labelledby="deals-title">
              <SectionHeading id="deals-title" title="오늘의 특가" />
              <div className="skeleton skeleton-card" />
            </section>
            <section className="section section-table" aria-labelledby="table-title">
              <SectionHeading id="table-title" title="목적지별 최저가" />
              <div className="skeleton-rows">
                {Array.from({ length: 6 }, (_, i) => (
                  <div key={i} className="skeleton skeleton-row" />
                ))}
              </div>
            </section>
          </div>
        )}

        {outcome !== null && !outcome.ok && (
          <div className="load-error" role="alert">
            <h2>데이터를 읽지 못했습니다</h2>
            <p>수집 데이터 파일을 읽을 수 없습니다. 잠시 후 다시 시도하십시오.</p>
            <p className="load-error-cause">
              {outcome.error.file} · {outcome.error.reason}
            </p>
            {failRun && (
              <p className="load-error-status">
                최근 수집({formatDateTime(failRun.finished_at)}) 결과: {STATE_LABEL[failRun.result]}
                {failRun.aborted_reason ? ` · ${failRun.aborted_reason}` : ""}
              </p>
            )}
            <button type="button" className="btn btn-primary" onClick={reload}>
              다시 시도
            </button>
          </div>
        )}

        {dataset && (
          <div className="layout">
            <section className="section section-deals" aria-labelledby="deals-title">
              <SectionHeading
                id="deals-title"
                title="오늘의 특가"
                aside={alerts ? `${active.length}건` : undefined}
              />
              {!alerts ? (
                <SectionError name="오늘의 특가" onRetry={reload} />
              ) : active.length === 0 ? (
                <DealsEmpty alerts={alerts} destinations={latest?.destinations ?? null} onSelect={selectDestination} />
              ) : (
                <div className="deal-list">
                  {active.map((alert) => (
                    <DealCard
                      key={alert.id}
                      alert={alert}
                      latestDest={latestOf(alert.destination)}
                      onSelect={selectDestination}
                    />
                  ))}
                </div>
              )}
            </section>

            {latest ? (
              <DestinationTable destinations={latest.destinations} selected={selected} onSelect={selectDestination} />
            ) : (
              <section className="section section-table" aria-labelledby="table-title">
                <SectionHeading id="table-title" title="목적지별 최저가" />
                <SectionError name="목적지별 최저가" onRetry={reload} />
              </section>
            )}

            {latest && selectedDest ? (
              <DestinationDetail
                dest={selectedDest}
                destinations={latest.destinations}
                trip={latest.trip}
                generatedAt={latest.generated_at}
                dataDir={dataset.dir}
                historyFile={
                  dataset.index.destinations.find((d) => d.destination === selectedDest.destination)?.history_file ??
                  null
                }
                failedInLastRun={status?.last_run?.failed_destinations.includes(selectedDest.destination) ?? false}
                headingRef={headingRef}
                onSelect={selectDestination}
                onBackToList={backToList}
              />
            ) : (
              <section className="section section-detail" aria-labelledby="detail-title">
                <SectionHeading id="detail-title" title="목적지 상세" />
                {latest ? (
                  <p className="muted">표시할 목적지가 없습니다.</p>
                ) : (
                  <SectionError name="목적지 상세" onRetry={reload} />
                )}
              </section>
            )}

            <section className="section section-past" aria-labelledby="past-title">
              <SectionHeading id="past-title" title="지난 알림" aside={alerts ? `${past.length}건` : undefined} />
              {alerts ? <PastAlerts alerts={past} /> : <SectionError name="지난 알림" onRetry={reload} />}
            </section>
          </div>
        )}
      </main>

      <footer className="app-footer">
        <p>
          가격은 성인 1명 왕복 총액이며 수집 시점의 Google Flights 검색 결과입니다. 예약 시점의 가격과 다를 수
          있습니다.
        </p>
        {dataset && <p>데이터 생성: {formatDateTime(dataset.index.generated_at)}</p>}
      </footer>
    </div>
  );
}
