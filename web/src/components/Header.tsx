import { useId, useState } from "react";
import type { FileResult } from "../lib/data";
import { ERROR_KIND_LABEL, STATE_LABEL, groupErrors, type Notice } from "../lib/derive";
import { formatClock, formatDate, formatDateShort, formatDateTime, formatNumber, formatRunDuration } from "../lib/format";
import type { Run, StatusFile, Trip } from "../types";
import { IconChevronDown, IconWarnTriangle, IconXCircle } from "./Icons";
import { StateIcon, stateTone } from "./common";

const ERROR_LIMIT = 10;
const RUN_LIMIT = 10;

export function tripSummary(trip: Trip): string {
  const nights = trip.nights_min === trip.nights_max ? `${trip.nights_min}박` : `${trip.nights_min}~${trip.nights_max}박`;
  return `${formatDateShort(trip.depart_from)} ~ ${formatDateShort(trip.depart_to)} 출발 · ${nights} · 성인 ${trip.adults}명`;
}

interface HeaderProps {
  trip: Trip | null;
  isSample: boolean;
  /** null: 읽는 중, undefined: 전체 읽기 실패(상태 줄을 표시하지 않음) */
  status: FileResult<StatusFile> | null | undefined;
  cityOf: (code: string) => string | null;
  onSelect: (code: string) => void;
}

export function AppHeader({ trip, isSample, status, cityOf, onSelect }: HeaderProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const data = status?.ok ? status.data : null;

  return (
    <header className="app-header">
      <div className="header-row">
        <div className="header-title">
          <div className="header-title-line">
            <h1>연말 특가 항공권</h1>
            {isSample && <span className="chip chip-sample">샘플 데이터</span>}
          </div>
          {trip && <p className="header-sub">{tripSummary(trip)}</p>}
        </div>
        {status === null && <p className="status-line status-line-plain">데이터를 읽는 중입니다.</p>}
        {status != null && !status.ok && (
          <p className="status-line status-line-plain tone-crit">
            <IconXCircle />
            수집 상태를 읽지 못했습니다.
          </p>
        )}
        {data && (
          <button
            type="button"
            className={`status-line status-button${data.state === "stopped" ? " status-stopped" : ""}`}
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((v) => !v)}
          >
            <span className={`status-state tone-${stateTone(data.state)}`}>
              <StateIcon state={data.state} />
              {STATE_LABEL[data.state]}
            </span>
            <span className="status-rest">
              {" · "}
              {data.last_run ? `마지막 수집 ${formatDateTime(data.last_run.finished_at)}` : "수집 기록 없음"}
              {data.last_run && data.last_run.failed_destinations.length > 0 && (
                <> · 실패 목적지 {data.last_run.failed_destinations.length}곳</>
              )}
            </span>
            <span className="sr-only">{open ? " 상세 숨기기" : " 상세 보기"}</span>
            <IconChevronDown className={open ? "chevron chevron-open" : "chevron"} />
          </button>
        )}
      </div>
      {data && (
        <div id={panelId} hidden={!open}>
          {open && <StatusPanel status={data} cityOf={cityOf} onSelect={onSelect} />}
        </div>
      )}
    </header>
  );
}

function StatusPanel({
  status,
  cityOf,
  onSelect,
}: {
  status: StatusFile;
  cityOf: (code: string) => string | null;
  onSelect: (code: string) => void;
}) {
  const run: Run | null = status.last_run ?? null;
  const [allErrors, setAllErrors] = useState(false);
  const [allRuns, setAllRuns] = useState(false);
  const errors = run?.errors ?? [];
  const shownErrors = allErrors ? errors : errors.slice(0, ERROR_LIMIT);
  const shownRuns = allRuns ? status.runs : status.runs.slice(0, RUN_LIMIT);
  const destName = (code: string) => {
    const city = cityOf(code);
    return city ? `${city}(${code})` : code;
  };

  return (
    <div className="status-panel">
      <h2 className="sr-only">수집 상태 상세</h2>
      {run ? (
        <dl className="status-dl">
          <div>
            <dt>수집 시간</dt>
            <dd>
              {formatDateTime(run.started_at)} ~ {formatClock(run.finished_at)} ({formatRunDuration(run.duration_seconds)})
            </dd>
          </div>
          <div>
            <dt>조회</dt>
            <dd>
              {formatNumber(run.queries.attempted)}건 중 성공 {formatNumber(run.queries.succeeded)}건
              {run.queries.no_result > 0 && <> · 결과 없음 {formatNumber(run.queries.no_result)}건</>} · 실패{" "}
              {formatNumber(run.queries.failed)}건
            </dd>
          </div>
          <div>
            <dt>봇 확인 응답</dt>
            <dd>
              {formatNumber(run.queries.bot_checks)}건(재시도 {formatNumber(run.queries.retries)}건)
            </dd>
          </div>
          {run.queries.skipped > 0 && (
            <div>
              <dt>생략</dt>
              <dd>{formatNumber(run.queries.skipped)}건</dd>
            </div>
          )}
          <div>
            <dt>목적지</dt>
            <dd>
              {run.destinations_total}곳 중 {run.destinations_succeeded}곳 성공
            </dd>
          </div>
          <div>
            <dt>특가 · 알림</dt>
            <dd>
              특가 {run.deals_found}건 · 알림 발송 {run.alerts_sent}건
            </dd>
          </div>
          <div>
            <dt>마지막 성공</dt>
            <dd>{status.last_success_at ? formatDateTime(status.last_success_at) : "없음"}</dd>
          </div>
          {status.consecutive_failures > 0 && (
            <div>
              <dt>연속 실패</dt>
              <dd>{status.consecutive_failures}회</dd>
            </div>
          )}
        </dl>
      ) : (
        <p className="muted">수집 기록 없음</p>
      )}

      {run && run.failed_destinations.length > 0 && (
        <div className="status-block">
          <h3>실패 목적지</h3>
          <div className="chip-row">
            {run.failed_destinations.map((code) => (
              <button key={code} type="button" className="chip-button" onClick={() => onSelect(code)}>
                {destName(code)}
              </button>
            ))}
          </div>
        </div>
      )}

      {run?.aborted_reason && (
        <p className="status-aborted">
          <IconWarnTriangle />
          {run.aborted_reason}
        </p>
      )}

      {errors.length > 0 && (
        <div className="status-block">
          <h3>
            오류{" "}
            <span className="status-error-counts">
              {groupErrors(errors)
                .map((g) => `${g.label} ${g.count}건`)
                .join(" · ")}
            </span>
          </h3>
          <ul className="error-list">
            {shownErrors.map((e, i) => (
              <li key={i}>
                <span className="error-kind">{ERROR_KIND_LABEL[e.kind] ?? "기타"}</span>
                {[
                  e.destination ? destName(e.destination) : null,
                  e.depart_date && e.return_date ? `${formatDate(e.depart_date)} ~ ${formatDate(e.return_date)}` : null,
                  e.message,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </li>
            ))}
          </ul>
          {errors.length > ERROR_LIMIT && !allErrors && (
            <button type="button" className="btn-text" onClick={() => setAllErrors(true)}>
              오류 {errors.length}건 모두 보기
            </button>
          )}
        </div>
      )}

      {status.runs.length > 0 && (
        <div className="status-block">
          <h3>최근 실행</h3>
          <div className="table-scroll" role="region" aria-label="최근 실행 표" tabIndex={0}>
            <table className="runs-table">
              <thead>
                <tr>
                  <th scope="col">시작 시각</th>
                  <th scope="col">결과</th>
                  <th scope="col" className="num">
                    조회<span className="sr-only">(응답/시도)</span>
                  </th>
                  <th scope="col" className="num">
                    특가
                  </th>
                  <th scope="col" className="num">
                    알림
                  </th>
                </tr>
              </thead>
              <tbody>
                {shownRuns.map((r) => (
                  <tr key={r.run_id}>
                    <td>{formatDateTime(r.started_at)}</td>
                    <td>
                      <span className={`run-result tone-${stateTone(r.result)}`}>
                        <StateIcon state={r.result} size={12} />
                        {STATE_LABEL[r.result]}
                      </span>
                    </td>
                    <td className="num">
                      {formatNumber(r.queries.succeeded + r.queries.no_result)}/{formatNumber(r.queries.attempted)}
                    </td>
                    <td className="num">{r.deals_found}</td>
                    <td className="num">{r.alerts_sent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {status.runs.length > RUN_LIMIT && !allRuns && (
            <button type="button" className="btn-text" onClick={() => setAllRuns(true)}>
              이전 실행 더 보기
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function NoticeBanner({ notices }: { notices: Notice[] }) {
  if (notices.length === 0) return null;
  return (
    <div className="notices">
      {notices.map((n) => (
        <p key={n.id} className={`notice notice-${n.tone}`} role={n.role}>
          {n.tone === "crit" ? <IconXCircle /> : <IconWarnTriangle />}
          <span>{n.text}</span>
        </p>
      ))}
    </div>
  );
}
