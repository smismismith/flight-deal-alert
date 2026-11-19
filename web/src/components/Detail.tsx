import { useEffect, useMemo, useState, type RefObject } from "react";
import type { Combo, HistoryPoint, LatestDestination, Trip } from "../types";
import { loadHistory } from "../lib/data";
import { CRITERIA, CRITERION_NAME, buildHeatGrid, comboKey, sortDestinations, type HeatCell } from "../lib/derive";
import {
  formatDate,
  formatDateSpoken,
  formatDateTime,
  formatDestination,
  formatManwon,
  formatPrice,
  formatStops,
  formatTrip,
  isWeekend,
  levelLabel,
} from "../lib/format";
import { DealChip, ExternalLink, LevelLabel, Route, StaleChip } from "./common";
import { PriceTrendChart } from "./PriceTrendChart";

interface DetailProps {
  dest: LatestDestination;
  destinations: LatestDestination[];
  trip: Trip;
  generatedAt: string;
  dataDir: string;
  historyFile: string | null;
  /** 마지막 실행의 failed_destinations 에 포함된 목적지이면 true */
  failedInLastRun: boolean;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onSelect: (code: string, scroll: boolean) => void;
  onBackToList: () => void;
}

type HistoryState = { ok: true; points: HistoryPoint[] } | { ok: false } | null;

export function DestinationDetail({
  dest,
  destinations,
  trip,
  generatedAt,
  dataDir,
  historyFile,
  failedInLastRun,
  headingRef,
  onSelect,
  onBackToList,
}: DetailProps) {
  const [history, setHistory] = useState<HistoryState>(null);
  const [attempt, setAttempt] = useState(0);
  const options = useMemo(() => sortDestinations(destinations, "price_asc"), [destinations]);

  useEffect(() => {
    let cancelled = false;
    setHistory(null);
    loadHistory(dataDir, historyFile).then((result) => {
      if (cancelled) return;
      setHistory(result.ok ? { ok: true, points: result.data?.points ?? [] } : { ok: false });
    });
    return () => {
      cancelled = true;
    };
  }, [dataDir, historyFile, dest.destination, attempt]);

  const best = dest.best;

  return (
    <section className="section section-detail" aria-labelledby="detail-title">
      <div className="section-head">
        <h2 id="detail-title" className="section-title" tabIndex={-1} ref={headingRef}>
          {dest.city_ko} 상세
        </h2>
        <span className="section-aside">
          <Route origin={dest.origin} destination={dest.destination} />
        </span>
        <button type="button" className="btn-text back-to-list" onClick={onBackToList}>
          목록으로
        </button>
      </div>
      <div className="detail-card">
        <label className="dest-select">
          <span className="sr-only">목적지 선택</span>
          <select value={dest.destination} onChange={(e) => onSelect(e.target.value, false)}>
            {options.map((d) => (
              <option key={d.destination} value={d.destination}>
                {formatDestination(d.city_ko, d.country_ko, d.is_domestic)} ·{" "}
                {d.best ? formatPrice(d.best.price_krw) : "가격 없음"}
              </option>
            ))}
          </select>
        </label>
        {best && (
          <p className="detail-summary">
            {dest.deal && <DealChip />}
            <span>
              최저가 <strong>{formatPrice(best.price_krw)}</strong> ·{" "}
              {formatTrip(best.depart_date, best.return_date, best.nights)}
              {best.insight?.level ? ` · ${levelLabel(best.insight.level)}` : ""}
            </span>
          </p>
        )}
        {/* 목적지가 바뀌면 선택한 칸을 초기화한다 */}
        <PriceHeatmap key={dest.destination} dest={dest} trip={trip} failedInLastRun={failedInLastRun} />
        <PriceTrendChart
          key={`chart-${dest.destination}`}
          cityKo={dest.city_ko}
          best={best}
          generatedAt={generatedAt}
          history={history}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      </div>
    </section>
  );
}

function cellLabel(cell: Extract<HeatCell, { kind: "price" }>): string {
  return [
    `${formatDateSpoken(cell.departDate)} 출발`,
    `${cell.nights}박`,
    formatPrice(cell.combo.price_krw),
    cell.combo.level ? levelLabel(cell.combo.level) : null,
    cell.combo.is_deal ? "특가" : null,
    cell.isBest ? "최저가" : null,
  ]
    .filter(Boolean)
    .join(", ");
}

export function PriceHeatmap({
  dest,
  trip,
  failedInLastRun = false,
}: {
  dest: LatestDestination;
  trip: Trip;
  failedInLastRun?: boolean;
}) {
  const grid = useMemo(() => buildHeatGrid(trip, dest.combos, dest.best), [trip, dest]);
  const [selectedKey, setSelectedKey] = useState<string | null>(
    dest.best ? comboKey(dest.best.depart_date, dest.best.nights) : null,
  );
  const selected: Combo | null = useMemo(() => {
    for (const row of grid.rows) {
      for (const cell of row.cells) {
        if (cell.kind === "price" && comboKey(cell.departDate, cell.nights) === selectedKey) return cell.combo;
      }
    }
    return null;
  }, [grid, selectedKey]);

  return (
    <div className="heat-block">
      <div className="sub-head">
        <h3>출발일 × 박수 가격</h3>
        <span className="sub-aside">
          조건 안 일정 {grid.inRangeCount}개 중 {grid.pricedCount}개 가격 표시
        </span>
      </div>
      {dest.stale && dest.best !== null && (
        <p className="heat-stale">
          <StaleChip />
          <span>
            {dest.last_success_at ? `${formatDateTime(dest.last_success_at)} 수집 값입니다. ` : ""}
            {failedInLastRun
              ? "최근 수집에서 이 목적지의 조회가 실패했습니다."
              : "최근 수집에서 이 목적지의 가격을 갱신하지 못했습니다."}
          </span>
        </p>
      )}
      <div className="heat-scroll">
        <table className="heat-table">
          <caption className="sr-only">{dest.city_ko} 출발일과 박수별 가격. 칸의 숫자 단위는 만원입니다.</caption>
          <thead>
            <tr>
              <th scope="col" className="heat-corner">
                <span className="sr-only">출발일</span>
              </th>
              {grid.nightsList.map((n) => (
                <th key={n} scope="col">
                  {n}박
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr key={row.departDate}>
                <th scope="row" className={isWeekend(row.departDate) ? "is-weekend" : undefined}>
                  {formatDate(row.departDate)}
                </th>
                {row.cells.map((cell) => {
                  if (cell.kind === "price") {
                    const key = comboKey(cell.departDate, cell.nights);
                    const pressed = key === selectedKey;
                    const className = [
                      "heat-cell",
                      `heat-${cell.level}`,
                      cell.combo.is_deal ? "is-deal" : "",
                      cell.isBest ? "is-best" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");
                    return (
                      <td key={cell.nights}>
                        <button
                          type="button"
                          className={className}
                          aria-pressed={pressed}
                          aria-label={cellLabel(cell)}
                          onClick={() => setSelectedKey(key)}
                        >
                          <span className="heat-value">{formatManwon(cell.combo.price_krw)}</span>
                          {cell.combo.is_deal && <span className="heat-dot" aria-hidden="true" />}
                        </button>
                      </td>
                    );
                  }
                  if (cell.kind === "out") {
                    return (
                      <td key={cell.nights}>
                        <span className="heat-cell heat-out">
                          <span className="sr-only">조건 밖</span>
                        </span>
                      </td>
                    );
                  }
                  return (
                    <td key={cell.nights}>
                      <span className="heat-cell heat-unsearched">
                        <span aria-hidden="true">·</span>
                        <span className="sr-only">조회하지 않음</span>
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {grid.pricedCount === 0 ? (
        <p className="muted">
          {failedInLastRun ? "최근 수집에서 이 목적지의 조회가 실패했습니다. " : ""}이 목적지는 수집된 가격이 없습니다.
        </p>
      ) : (
        <div className="heat-legend">
          <p className="legend-scale">
            <span>낮은 가격</span>
            <span className="legend-swatches" aria-hidden="true">
              {[5, 4, 3, 2, 1].map((level) => (
                <span key={level} className={`legend-swatch heat-${level}`} />
              ))}
            </span>
            <span>높은 가격</span>
            {grid.minPrice !== null && grid.maxPrice !== null && (
              <span className="legend-range">
                {formatPrice(grid.minPrice)} ~ {formatPrice(grid.maxPrice)}
              </span>
            )}
          </p>
          <p>칸의 숫자 단위: 만원. 색은 이 목적지 안의 가격 순위 기준이며 가격 차이의 크기와는 관계없습니다.</p>
          <ul className="legend-keys">
            <li>
              <span className="legend-key heat-unsearched" aria-hidden="true">
                ·
              </span>
              조회하지 않음
            </li>
            <li>
              <span className="legend-key heat-out" aria-hidden="true" />
              조건 밖
            </li>
            <li>
              <span className="legend-key legend-key-deal" aria-hidden="true">
                <span className="heat-dot" />
              </span>
              특가
            </li>
            <li>
              <span className="legend-key legend-key-best" aria-hidden="true">
                12
              </span>
              밑줄: 최저가
            </li>
          </ul>
        </div>
      )}

      {grid.pricedCount > 0 && (
        <div className="combo-detail" aria-live="polite">
          {selected ? (
            <ComboDetail combo={selected} />
          ) : (
            <p className="muted">칸을 선택하면 일정과 가격을 표시합니다.</p>
          )}
        </div>
      )}
    </div>
  );
}

function ComboDetail({ combo }: { combo: Combo }) {
  const matchedNames = CRITERIA.filter((c) => combo.matched.includes(c)).map((c) => CRITERION_NAME[c]);
  return (
    <>
      <div className="combo-top">
        <span className="combo-trip">{formatTrip(combo.depart_date, combo.return_date, combo.nights)}</span>
        <span className="combo-price">{formatPrice(combo.price_krw)}</span>
      </div>
      <p className="combo-flight">
        {[combo.airlines.length > 0 ? combo.airlines.join(", ") : null, formatStops(combo.stops)]
          .filter(Boolean)
          .join(" · ")}
        {combo.level && (
          <>
            {" · "}
            <LevelLabel level={combo.level} />
          </>
        )}
      </p>
      {matchedNames.length > 0 && (
        <p className="combo-matched">
          {combo.is_deal && <DealChip />}
          <span>해당 기준: {matchedNames.join(", ")}</span>
        </p>
      )}
      <div className="combo-actions">
        <ExternalLink href={combo.search_url} className="btn btn-primary">
          이 일정으로 항공권 검색
        </ExternalLink>
        <span className="combo-time">{formatDateTime(combo.collected_at)} 수집</span>
      </div>
    </>
  );
}
