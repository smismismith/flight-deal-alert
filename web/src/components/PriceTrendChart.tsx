import { useEffect, useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Fare, HistoryPoint } from "../types";
import { axisDateTicks, buildChartModel, chartSummary, nearestIndex, type SeriesPoint } from "../lib/derive";
import { formatAxisDate, formatDateTime, formatNumber, formatPrice, formatTrip } from "../lib/format";

const BASE_MARGIN = { top: 20, right: 64, bottom: 26, left: 44 };
/** 12px 숫자 1자의 폭(쉼표 포함 평균) */
const CHAR_W = 7;
const TABLE_LIMIT = 15;
const DAY_MS = 86400000;

interface Props {
  cityKo: string;
  best: Fare | null;
  generatedAt: string;
  /** null: 읽는 중 */
  history: { ok: true; points: HistoryPoint[] } | { ok: false } | null;
  onRetry: () => void;
}

function useElementWidth(element: HTMLElement | null): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element) return;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return width;
}

function useIsWide(): boolean {
  const query = "(min-width: 640px)";
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setWide(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return wide;
}

function valueNear(points: SeriesPoint[], t: number): number | null {
  if (points.length === 0) return null;
  const first = points[0] as SeriesPoint;
  const last = points[points.length - 1] as SeriesPoint;
  if (t < first.t - DAY_MS || t > last.t + DAY_MS) return null;
  return points[nearestIndex(points, t)]?.v ?? null;
}

export function PriceTrendChart({ cityKo, best, generatedAt, history, onRetry }: Props) {
  const [wrap, setWrap] = useState<HTMLDivElement | null>(null);
  const width = useElementWidth(wrap);
  const wide = useIsWide();
  const height = wide ? 260 : 220;
  const [hoverT, setHoverT] = useState<number | null>(null);
  const [tableOpen, setTableOpen] = useState(false);
  const [allRows, setAllRows] = useState(false);
  const tableId = useId();

  const points = useMemo(() => (history?.ok ? history.points : []), [history]);
  const baseline = best?.judgement.baseline_price_krw ?? null;
  const model = useMemo(
    () => buildChartModel({ points, insight: best?.insight ?? null, baseline, generatedAt }),
    [points, best, baseline, generatedAt],
  );

  useEffect(() => {
    if (hoverT === null) return;
    const onDown = (event: globalThis.PointerEvent) => {
      if (wrap && !wrap.contains(event.target as Node)) setHoverT(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [hoverT, wrap]);

  if (history === null) {
    return (
      <div className="chart-block" aria-busy="true">
        <h3>가격 추이</h3>
        <div className="chart-skeleton" style={{ height }} />
        <p className="sr-only">가격 이력을 읽는 중입니다.</p>
      </div>
    );
  }

  const historyFailed = !history.ok;
  // 축 눈금과 선 끝 표기의 글자 수에 맞춰 좌우 여백을 정한다(7자리 가격이 잘리지 않도록)
  const maxTickChars = model ? Math.max(0, ...model.yTicks.map((t) => formatNumber(t).length)) : 0;
  const lastOwnValue = model?.own[model.own.length - 1]?.v;
  const endChars = lastOwnValue !== undefined ? formatNumber(lastOwnValue).length : 0;
  const MARGIN = {
    ...BASE_MARGIN,
    left: Math.max(BASE_MARGIN.left, maxTickChars * CHAR_W + 12),
    right: Math.max(BASE_MARGIN.right, endChars * CHAR_W + 16),
  };
  const plotW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const plotH = height - MARGIN.top - MARGIN.bottom;

  let chart = null;
  if (model && width > 0) {
    const { xMin, xMax, y } = model;
    const sx = (t: number) => MARGIN.left + ((t - xMin) / (xMax - xMin)) * plotW;
    const sy = (v: number) => MARGIN.top + (1 - (v - y.min) / (y.max - y.min)) * plotH;
    const path = (series: SeriesPoint[]) =>
      series.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join("");
    const xTicks = axisDateTicks(xMin, xMax, wide ? 6 : 4, plotW, formatAxisDate);
    const lastOwn = model.own[model.own.length - 1];
    const bandTop = model.band ? Math.max(MARGIN.top, sy(Math.min(model.band.high, y.max))) : 0;
    const bandBottom = model.band ? Math.min(MARGIN.top + plotH, sy(Math.max(model.band.low, y.min))) : 0;

    const tFromEvent = (event: PointerEvent<SVGSVGElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const x = Math.min(Math.max(event.clientX - rect.left, MARGIN.left), MARGIN.left + plotW);
      return xMin + ((x - MARGIN.left) / Math.max(plotW, 1)) * (xMax - xMin);
    };
    const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
      if (event.key === "Escape") {
        setHoverT(null);
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (model.own.length === 0) return;
      event.preventDefault();
      const current = hoverT === null ? -1 : nearestIndex(model.own, hoverT);
      const next =
        current === -1
          ? model.own.length - 1
          : Math.min(model.own.length - 1, Math.max(0, current + (event.key === "ArrowLeft" ? -1 : 1)));
      setHoverT((model.own[next] as SeriesPoint).t);
    };

    const ownValue = hoverT !== null ? valueNear(model.own, hoverT) : null;
    const googleValue = hoverT !== null ? valueNear(model.google, hoverT) : null;
    const hoverX = hoverT !== null ? sx(hoverT) : 0;
    const tooltipText =
      hoverT !== null
        ? [
            formatAxisDate(hoverT),
            ownValue !== null ? `수집 이력 ${formatPrice(ownValue)}` : null,
            googleValue !== null ? `Google ${formatPrice(googleValue)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")
        : "";
    const tooltipOnLeft = hoverX > MARGIN.left + plotW / 2;

    chart = (
      <>
        <svg
          className="chart-svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={chartSummary(cityKo, model)}
          tabIndex={0}
          onPointerMove={(e) => setHoverT(tFromEvent(e))}
          onPointerDown={(e) => setHoverT(tFromEvent(e))}
          onPointerLeave={(e) => {
            if (e.pointerType === "mouse") setHoverT(null);
          }}
          onKeyDown={onKeyDown}
        >
          <text className="chart-axis" x={MARGIN.left - 8} y={10} textAnchor="end">
            원
          </text>
          {model.yTicks.map((tick) => (
            <g key={tick}>
              <line className="chart-grid" x1={MARGIN.left} x2={MARGIN.left + plotW} y1={sy(tick)} y2={sy(tick)} />
              <text className="chart-axis" x={MARGIN.left - 8} y={sy(tick) + 4} textAnchor="end">
                {formatNumber(tick)}
              </text>
            </g>
          ))}
          {xTicks.map((tick, i) => (
            <text
              key={tick.t}
              className="chart-axis"
              x={sx(tick.t)}
              y={height - 6}
              textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}
            >
              {tick.label}
            </text>
          ))}
          <line
            className="chart-baseline-axis"
            x1={MARGIN.left}
            x2={MARGIN.left + plotW}
            y1={MARGIN.top + plotH}
            y2={MARGIN.top + plotH}
          />
          {model.band && bandBottom > bandTop && (
            <rect className="chart-band" x={MARGIN.left} y={bandTop} width={plotW} height={bandBottom - bandTop} />
          )}
          {model.baseline !== null && model.baselineInRange && (
            <line
              className="chart-refline"
              x1={MARGIN.left}
              x2={MARGIN.left + plotW}
              y1={sy(model.baseline)}
              y2={sy(model.baseline)}
            />
          )}
          {model.google.length > 1 && <path className="chart-line chart-line-google" d={path(model.google)} />}
          {model.own.length > 1 && <path className="chart-line chart-line-own" d={path(model.own)} />}
          {lastOwn && (
            <>
              <circle className="chart-dot" cx={sx(lastOwn.t)} cy={sy(lastOwn.v)} r={4} />
              <text className="chart-end-label" x={sx(lastOwn.t) + 9} y={sy(lastOwn.v) + 4}>
                {formatNumber(lastOwn.v)}
              </text>
            </>
          )}
          {hoverT !== null && (
            <line className="chart-cursor" x1={hoverX} x2={hoverX} y1={MARGIN.top} y2={MARGIN.top + plotH} />
          )}
        </svg>
        <div
          className="chart-tooltip"
          aria-live="polite"
          hidden={hoverT === null}
          style={
            tooltipOnLeft
              ? { right: Math.max(0, width - hoverX + 8), top: MARGIN.top }
              : { left: Math.max(0, hoverX + 8), top: MARGIN.top }
          }
        >
          {tooltipText}
        </div>
      </>
    );
  }

  const sortedPoints = [...points].sort((a, b) => (a.collected_at < b.collected_at ? 1 : -1));
  const shownPoints = allRows ? sortedPoints : sortedPoints.slice(0, TABLE_LIMIT);

  return (
    <div className="chart-block">
      <h3>가격 추이</h3>
      {historyFailed && (
        <div className="chart-error" role="alert">
          <span>수집 이력을 읽지 못했습니다.</span>
          <button type="button" className="btn btn-secondary" onClick={onRetry}>
            다시 시도
          </button>
        </div>
      )}
      {model ? (
        <>
          <ul className="chart-legend">
            {model.own.length > 0 && (
              <li>
                <span className="swatch swatch-own" aria-hidden="true" />
                수집 이력(수집 시점의 목적지 최저가)
              </li>
            )}
            {model.google.length > 0 && (
              <li>
                <span className="swatch swatch-google" aria-hidden="true" />
                Google 최근 60일(현재 최저가 일정 기준)
              </li>
            )}
            {model.band && (
              <li>
                <span className="swatch swatch-band" aria-hidden="true" />
                Google 평소 가격 범위 {formatNumber(model.band.low)} ~ {formatPrice(model.band.high)}
              </li>
            )}
            {model.baseline !== null && best && (
              <li>
                <span className="swatch swatch-ref" aria-hidden="true" />
                비성수기 기준가 {formatPrice(model.baseline)}({best.nights}박)
                {!model.baselineInRange && " (차트 범위 밖)"}
              </li>
            )}
          </ul>
          <div className="chart-wrap" ref={setWrap} style={{ height }}>
            {chart}
          </div>
        </>
      ) : (
        !historyFailed && <p className="muted">수집 이력이 아직 없습니다. 다음 수집 후 표시됩니다.</p>
      )}
      {model && model.own.length > 0 && (
        <p className="chart-note">
          수집 이력은 실행마다 조회한 일정 중 최저가입니다. 조회한 일정 수가 실행마다 다르면 실제 가격 변동 없이 값이
          달라질 수 있습니다. 실행별 조회 일정 수는 '표로 보기'에 표시합니다.
        </p>
      )}
      {best !== null && best.insight === null && model && (
        <p className="chart-note">이 목적지는 Google 가격 정보가 없어 수집 이력만 표시합니다.</p>
      )}
      {points.length > 0 && (
        <>
          <button
            type="button"
            className="btn-text"
            aria-expanded={tableOpen}
            aria-controls={tableId}
            onClick={() => setTableOpen((v) => !v)}
          >
            {tableOpen ? "표 숨기기" : "표로 보기"}
          </button>
          <div id={tableId} hidden={!tableOpen}>
            {tableOpen && (
              <>
                <div className="table-scroll">
                  <table className="history-table">
                    <caption className="sr-only">{cityKo} 수집 이력(최신순)</caption>
                    <thead>
                      <tr>
                        <th scope="col">수집 시각</th>
                        <th scope="col" className="num">
                          최저가
                        </th>
                        <th scope="col">일정</th>
                        <th scope="col" className="num">
                          조회 일정 수
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {shownPoints.map((p) => (
                        <tr key={p.run_id}>
                          <td>{formatDateTime(p.collected_at)}</td>
                          <td className="num">{formatPrice(p.price_krw)}</td>
                          <td>{formatTrip(p.depart_date, p.return_date, p.nights)}</td>
                          <td className="num">{typeof p.combos_checked === "number" ? `${p.combos_checked}개` : "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {sortedPoints.length > TABLE_LIMIT && !allRows && (
                  <button type="button" className="btn-text" onClick={() => setAllRows(true)}>
                    더 보기
                  </button>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
