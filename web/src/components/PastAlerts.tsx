import { useState } from "react";
import type { Alert } from "../types";
import { formatDateTime, formatDestination, formatPrice, formatTrip } from "../lib/format";

const LIMIT = 5;

export function PastAlerts({ alerts }: { alerts: Alert[] }) {
  const [all, setAll] = useState(false);
  if (alerts.length === 0) return <p className="muted">지난 알림이 없습니다.</p>;
  const shown = all ? alerts : alerts.slice(0, LIMIT);
  return (
    <>
      <ul className="past-list">
        {shown.map((a) => (
          <li key={a.id} className="past-item">
            <div className="past-main">
              <span className="past-city">{formatDestination(a.city_ko, a.country_ko, a.region === "국내")}</span>
              <span className="past-price">{formatPrice(a.alerted_price_krw)}</span>
              <span className="chip chip-outline">{a.status === "replaced" ? "추가 인하로 대체" : "특가 종료"}</span>
            </div>
            <p className="past-sub">
              {formatTrip(a.fare.depart_date, a.fare.return_date, a.fare.nights)} ·{" "}
              {a.notification.sent_at
                ? `${formatDateTime(a.notification.sent_at)} 발송`
                : `${formatDateTime(a.created_at)} 발송 실패`}
              {a.ended_at && <> · {formatDateTime(a.ended_at)} 종료</>}
            </p>
          </li>
        ))}
      </ul>
      {alerts.length > LIMIT && !all && (
        <button type="button" className="btn-text" onClick={() => setAll(true)}>
          지난 알림 더 보기
        </button>
      )}
    </>
  );
}
