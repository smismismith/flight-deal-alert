import type { ReactNode } from "react";
import type { Level, StatusState } from "../types";
import { levelLabel } from "../lib/format";
import {
  IconArrowDown,
  IconArrowUp,
  IconCheckCircle,
  IconClock,
  IconExternal,
  IconMinus,
  IconStop,
  IconWarnTriangle,
  IconXCircle,
} from "./Icons";

/** 외부 링크: 새 창 + rel="noopener noreferrer". https 주소만 링크로 만든다. */
export function ExternalLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  if (!/^https:\/\//i.test(href)) {
    return <span className={className}>{children}</span>;
  }
  return (
    <a className={className} href={href} target="_blank" rel="noopener noreferrer">
      {children}
      <IconExternal size={12} className="icon-external" />
      <span className="sr-only"> (새 창)</span>
    </a>
  );
}

export function Route({ origin, destination }: { origin: string; destination: string }) {
  return (
    <span className="route">
      {origin} <span aria-hidden="true">→</span>
      <span className="sr-only">에서</span> {destination}
    </span>
  );
}

export function SectionHeading({
  id,
  title,
  aside,
  children,
}: {
  id: string;
  title: string;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="section-head">
      <h2 id={id} className="section-title">
        {title}
      </h2>
      {aside != null && <span className="section-aside">{aside}</span>}
      {children}
    </div>
  );
}

export function SectionError({ name, onRetry }: { name: string; onRetry: () => void }) {
  return (
    <div className="section-error" role="alert">
      <p>{name} 데이터를 읽지 못했습니다.</p>
      <button type="button" className="btn btn-secondary" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  );
}

export function DealChip({ label = "특가", outline = false }: { label?: string; outline?: boolean }) {
  return <span className={outline ? "chip chip-deal-outline" : "chip chip-deal"}>{label}</span>;
}

export function StaleChip() {
  return (
    <span className="chip chip-warn">
      <IconClock size={12} />
      이전 수집 값
    </span>
  );
}

export function LevelLabel({ level, hasInsight = true }: { level: Level | null | undefined; hasInsight?: boolean }) {
  const effective = hasInsight ? (level ?? null) : null;
  if (effective === null) return <span className="level level-none">{levelLabel(null)}</span>;
  return (
    <span className={`level level-${effective}`}>
      {effective === "low" && <IconArrowDown size={12} />}
      {effective === "typical" && <IconMinus size={12} />}
      {effective === "high" && <IconArrowUp size={12} />}
      {levelLabel(effective)}
    </span>
  );
}

export function StateIcon({ state, size = 16 }: { state: StatusState; size?: number }) {
  if (state === "ok") return <IconCheckCircle size={size} />;
  if (state === "partial") return <IconWarnTriangle size={size} />;
  if (state === "failed") return <IconXCircle size={size} />;
  return <IconStop size={size} />;
}

export function stateTone(state: StatusState): "ok" | "warn" | "crit" {
  if (state === "ok") return "ok";
  if (state === "partial") return "warn";
  return "crit";
}
