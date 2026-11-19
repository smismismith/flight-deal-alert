import type { Alert, Fare, Hotels, LatestDestination } from "../types";
import {
  CRITERION_NAME,
  baselineNote,
  criterionStateLabel,
  criterionStates,
  displayFare,
  judgementSentences,
  sortDestinations,
} from "../lib/derive";
import {
  formatDateTime,
  formatDestination,
  formatDuration,
  formatPrice,
  formatRating,
  formatStops,
  formatTrip,
} from "../lib/format";
import { IconCheck, IconMinus, IconWarnTriangle } from "./Icons";
import { DealChip, ExternalLink, Route, StaleChip } from "./common";

export function flightLine(fare: Fare): string {
  return [
    fare.airlines.length > 0 ? fare.airlines.join(", ") : null,
    typeof fare.stops === "number" ? formatStops(fare.stops) : null,
    fare.duration_minutes != null ? formatDuration(fare.duration_minutes) : null,
    fare.depart_time ? `${fare.depart_time} 출발` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function CriteriaChips({ fare }: { fare: Fare }) {
  return (
    <ul className="criteria-chips">
      {criterionStates(fare.judgement).map(({ criterion, state }) => (
        <li key={criterion} className={`criterion criterion-${state}`}>
          {state === "matched" && <IconCheck size={12} />}
          {state === "unmatched" && <IconMinus size={12} />}
          <span aria-hidden="true">
            {CRITERION_NAME[criterion]}
            {state === "not_evaluated" && " (자료 없음)"}
          </span>
          <span className="sr-only">{criterionStateLabel(criterion, state)}</span>
        </li>
      ))}
    </ul>
  );
}

export function HotelList({ hotels }: { hotels: Hotels }) {
  const hasItems = hotels.source === "serpapi" && hotels.items.length > 0;
  return (
    <div className="hotels">
      <div className="hotels-head">
        <h4>
          호텔 <span className="hotels-dates">{formatTrip(hotels.check_in, hotels.check_out, hotels.nights)}</span>
        </h4>
        {hasItems && <span className="hotels-unit">1박 요금</span>}
      </div>
      {hasItems ? (
        <ul className="hotel-list">
          {hotels.items.map((item, i) => (
            <li key={`${item.name}-${i}`} className="hotel">
              <div className="hotel-main">
                {item.link ? (
                  <ExternalLink href={item.link} className="hotel-name link">
                    {item.name}
                  </ExternalLink>
                ) : (
                  <span className="hotel-name">{item.name}</span>
                )}
                <span className="hotel-rate">
                  {item.rate_per_night_krw != null ? formatPrice(item.rate_per_night_krw) : "-"}
                </span>
              </div>
              <div className="hotel-sub">
                <span>
                  {item.rating != null && <span className="hotel-rating">{formatRating(item.rating)}</span>}
                  {item.rating != null && item.deal && " · "}
                  {item.deal && <span className="hotel-deal">{item.deal}</span>}
                </span>
                {item.total_rate_krw != null && (
                  <span className="hotel-total">
                    {hotels.nights}박 {formatPrice(item.total_rate_krw)}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="hotels-empty">호텔 요금은 조회하지 않았습니다. 아래 링크에서 같은 날짜로 검색할 수 있습니다.</p>
      )}
      <div className="hotel-links">
        <ExternalLink href={hotels.links.google_hotels} className="btn btn-secondary">
          Google Hotels에서 검색
        </ExternalLink>
        <ExternalLink href={hotels.links.agoda} className="btn btn-secondary">
          아고다에서 검색
        </ExternalLink>
      </div>
    </div>
  );
}

export function DealCard({
  alert,
  latestDest,
  onSelect,
}: {
  alert: Alert;
  latestDest: LatestDestination | null;
  onSelect: (code: string, scroll: boolean) => void;
}) {
  const fare = displayFare(alert);
  const sentences = judgementSentences(fare);
  const note = baselineNote(fare);
  const isDomestic = latestDest?.is_domestic ?? alert.region === "국내";
  const stale = latestDest?.stale === true;

  return (
    <article className="deal-card">
      <div className="deal-grid">
        <div className="deal-flight">
          <div className="deal-top">
            <DealChip label={alert.kind === "realert" ? "특가 · 추가 인하" : "특가"} />
            <h3>{formatDestination(alert.city_ko, alert.country_ko, isDomestic)}</h3>
            <Route origin={fare.origin} destination={fare.destination} />
          </div>
          <div className="deal-price-row">
            <span className="deal-price">{formatPrice(fare.price_krw)}</span>
            {alert.previous_alerted_price_krw != null && (
              <span className="deal-prev">직전 알림 {formatPrice(alert.previous_alerted_price_krw)}</span>
            )}
          </div>
          {stale && (
            <p className="deal-stale">
              <StaleChip />
              <span>{formatDateTime(latestDest?.last_success_at)} 기준</span>
            </p>
          )}
          <p className="deal-trip">{formatTrip(fare.depart_date, fare.return_date, fare.nights)}</p>
          <p className="deal-flightline">{flightLine(fare)}</p>

          <div className="deal-judgement">
            <h4>
              판정 근거 <span className="deal-judgement-count">4개 기준 중 {fare.judgement.matched_count}개 해당</span>
            </h4>
            <CriteriaChips fare={fare} />
            {sentences.length > 0 && (
              <ul className="deal-sentences">
                {sentences.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
            {note && <p className="deal-baseline">{note}</p>}
          </div>

          <div className="deal-actions">
            <ExternalLink href={fare.search_url} className="btn btn-primary">
              항공권 검색
            </ExternalLink>
            <button type="button" className="btn btn-secondary" onClick={() => onSelect(alert.destination, true)}>
              날짜별 가격 보기
            </button>
          </div>
          {alert.notification.sent ? (
            <p className="deal-times">
              {formatDateTime(fare.collected_at)} 수집 · {formatDateTime(alert.notification.sent_at)} 알림 발송
            </p>
          ) : (
            <p className="deal-times deal-unsent">
              <IconWarnTriangle size={12} />
              텔레그램 알림을 발송하지 못했습니다. 다음 수집에서 다시 발송합니다.
            </p>
          )}
        </div>
        {alert.hotels && <HotelList hotels={alert.hotels} />}
      </div>
    </article>
  );
}

export function DealsEmpty({
  alerts,
  destinations,
  onSelect,
}: {
  alerts: Alert[];
  destinations: LatestDestination[] | null;
  onSelect: (code: string, scroll: boolean) => void;
}) {
  const lastAlert = alerts[0] ?? null;
  const cheapest = destinations
    ? sortDestinations(destinations, "price_asc")
        .filter((d) => d.best !== null)
        .slice(0, 3)
    : [];
  return (
    <div className="deals-empty">
      <p className="deals-empty-title">현재 특가가 없습니다</p>
      <p className="deals-empty-sub">
        {lastAlert
          ? `마지막 특가: ${lastAlert.city_ko} ${formatPrice(lastAlert.alerted_price_krw)} (${
              lastAlert.notification.sent_at
                ? `${formatDateTime(lastAlert.notification.sent_at)} 발송`
                : `${formatDateTime(lastAlert.created_at)} 발송 실패`
            })`
          : "수집을 시작한 뒤 아직 특가가 없습니다. 특가가 발생하면 텔레그램으로 알림을 발송합니다."}
      </p>
      {cheapest.length > 0 && (
        <>
          <h3>현재 가격이 가장 낮은 목적지</h3>
          <ul className="cheapest-list">
            {cheapest.map((d) => (
              <li key={d.destination}>
                <button type="button" onClick={() => onSelect(d.destination, true)}>
                  <span className="cheapest-city">{d.city_ko}</span>
                  <span className="cheapest-trip">
                    {d.best && formatTrip(d.best.depart_date, d.best.return_date, d.best.nights)}
                  </span>
                  <span className="cheapest-price">{d.best && formatPrice(d.best.price_krw)}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
