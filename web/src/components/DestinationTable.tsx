import { useMemo, useState } from "react";
import type { LatestDestination } from "../types";
import {
  filterDestinations,
  regionCounts,
  sortDestinations,
  type RegionFilterValue,
  type SortKey,
} from "../lib/derive";
import { formatDateTime, formatPrice, formatTrip, formatTripShort } from "../lib/format";
import { IconArrowDown, IconArrowUp, IconSortBoth } from "./Icons";
import { DealChip, LevelLabel, SectionHeading, StaleChip } from "./common";

interface Props {
  destinations: LatestDestination[];
  selected: string | null;
  onSelect: (code: string, scroll: boolean) => void;
}

export function rowId(code: string): string {
  return `dest-row-${code}`;
}

export function DestinationTable({ destinations, selected, onSelect }: Props) {
  const [region, setRegion] = useState<RegionFilterValue>("전체");
  const [sortKey, setSortKey] = useState<SortKey>("price_asc");
  const [dealsOnly, setDealsOnly] = useState(false);

  const counts = useMemo(() => regionCounts(destinations), [destinations]);
  const rows = useMemo(
    () => sortDestinations(filterDestinations(destinations, region, dealsOnly), sortKey),
    [destinations, region, dealsOnly, sortKey],
  );
  const liveText = `${region}${dealsOnly ? " 특가" : ""} ${rows.length}곳 표시`;

  const priceSort = sortKey === "price_asc" ? "ascending" : sortKey === "price_desc" ? "descending" : "none";
  const nameSort = sortKey === "name" ? "ascending" : "none";

  return (
    <section className="section section-table" aria-labelledby="table-title">
      <SectionHeading id="table-title" title="목적지별 최저가" aside={`${rows.length}곳`} />

      <div className="region-filter" role="group" aria-label="지역 필터">
        <button
          type="button"
          className="filter-chip"
          aria-pressed={region === "전체"}
          onClick={() => setRegion("전체")}
        >
          전체 {destinations.length}
        </button>
        {counts.map((c) => (
          <button
            key={c.region}
            type="button"
            className="filter-chip"
            aria-pressed={region === c.region}
            onClick={() => setRegion(c.region)}
          >
            {c.region} {c.count}
          </button>
        ))}
      </div>

      <div className="table-controls">
        <label className="sort-select">
          <span>정렬</span>
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="price_asc">가격 낮은 순</option>
            <option value="price_desc">가격 높은 순</option>
            <option value="name">목적지 이름순</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={dealsOnly} onChange={(e) => setDealsOnly(e.target.checked)} />
          <span>특가만 보기</span>
        </label>
      </div>
      <p className="sr-only" aria-live="polite">
        {liveText}
      </p>

      {rows.length === 0 ? (
        <div className="table-empty">
          <p>조건에 해당하는 목적지가 없습니다.</p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setRegion("전체");
              setDealsOnly(false);
            }}
          >
            필터 초기화
          </button>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="dest-table">
            <thead>
              <tr>
                <th scope="col" aria-sort={nameSort}>
                  <span className="th-plain">목적지</span>
                  <button type="button" className="th-sort" onClick={() => setSortKey("name")}>
                    목적지
                    {sortKey === "name" ? <IconArrowUp size={12} /> : <IconSortBoth size={12} />}
                  </button>
                </th>
                <th scope="col" className="col-wide">
                  지역
                </th>
                <th scope="col" className="col-wide">
                  일정
                </th>
                <th scope="col" className="col-wide">
                  가격 수준
                </th>
                <th scope="col" className="num" aria-sort={priceSort}>
                  <span className="th-plain">최저가</span>
                  <button
                    type="button"
                    className="th-sort"
                    onClick={() => setSortKey(sortKey === "price_asc" ? "price_desc" : "price_asc")}
                  >
                    최저가
                    {sortKey === "price_asc" ? (
                      <IconArrowUp size={12} />
                    ) : sortKey === "price_desc" ? (
                      <IconArrowDown size={12} />
                    ) : (
                      <IconSortBoth size={12} />
                    )}
                  </button>
                </th>
                <th scope="col" className="col-wide">
                  특가
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const isSelected = d.destination === selected;
                const best = d.best;
                const className = [
                  "dest-row",
                  isSelected ? "is-selected" : "",
                  d.deal ? "is-deal" : "",
                  d.stale ? "is-stale" : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <tr
                    key={d.destination}
                    id={rowId(d.destination)}
                    className={className}
                    aria-current={isSelected ? "true" : undefined}
                    onClick={() => onSelect(d.destination, true)}
                  >
                    <td className="cell-dest">
                      <div className="cell-line">
                        <button
                          type="button"
                          className="dest-button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelect(d.destination, true);
                          }}
                        >
                          {d.city_ko}
                        </button>
                        {d.stale && best && <StaleChip />}
                      </div>
                      <div className="cell-sub">
                        <span>
                          {d.is_domestic ? "국내" : d.country_ko} · <span className="code">{d.destination}</span>
                          {d.stale && d.last_success_at && <> · {formatDateTime(d.last_success_at)} 수집</>}
                        </span>
                        <span className="only-s" aria-hidden="true">
                          {best ? <LevelLabel level={best.insight?.level} hasInsight={best.insight !== null} /> : null}
                        </span>
                      </div>
                    </td>
                    <td className="col-wide cell-region">{d.region}</td>
                    <td className="col-wide">{best ? formatTrip(best.depart_date, best.return_date, best.nights) : "-"}</td>
                    <td className="col-wide">
                      {best ? <LevelLabel level={best.insight?.level} hasInsight={best.insight !== null} /> : "-"}
                    </td>
                    <td className="num cell-price">
                      <div className="cell-line cell-line-end">
                        {d.deal && (
                          <span className="only-s" aria-hidden="true">
                            <DealChip outline />
                          </span>
                        )}
                        {best ? (
                          <span className="price">{formatPrice(best.price_krw)}</span>
                        ) : (
                          <span className="price-none">{d.stale ? "조회 실패" : "가격 없음"}</span>
                        )}
                      </div>
                      <div className="cell-sub cell-sub-end only-s" aria-hidden="true">
                        {best ? formatTripShort(best.depart_date, best.nights) : "-"}
                      </div>
                    </td>
                    <td className="col-wide">{d.deal ? <DealChip outline /> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
