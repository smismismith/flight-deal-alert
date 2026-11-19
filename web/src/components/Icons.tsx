// 인라인 SVG 아이콘(16px 기준, stroke=currentColor, 선 두께 1.5px). 모두 장식용이며 문구와 함께 사용한다.
import type { ReactNode } from "react";

interface IconProps {
  size?: number;
  className?: string;
}

function Svg({ size = 16, className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const IconCheckCircle = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6.25" />
    <path d="M5.2 8.2l1.9 1.9 3.7-4" />
  </Svg>
);

export const IconWarnTriangle = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 2.2l6.2 11H1.8z" />
    <path d="M8 6.5v3.2M8 11.6v.1" />
  </Svg>
);

export const IconXCircle = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6.25" />
    <path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4" />
  </Svg>
);

export const IconStop = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="10" height="10" rx="1" fill="currentColor" />
  </Svg>
);

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 6l4.5 4.5L12.5 6" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 8.4l3.2 3.2L13 4.6" />
  </Svg>
);

export const IconMinus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 8h9" />
  </Svg>
);

export const IconArrowDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 2.5v11M3.5 9l4.5 4.5L12.5 9" />
  </Svg>
);

export const IconArrowUp = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 13.5v-11M3.5 7L8 2.5 12.5 7" />
  </Svg>
);

export const IconClock = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6.25" />
    <path d="M8 4.5V8l2.4 1.6" />
  </Svg>
);

export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 2.5h4.5V7M13.2 2.8L7.5 8.5M6 4H3.5a1 1 0 00-1 1v7.5a1 1 0 001 1H11a1 1 0 001-1V10" />
  </Svg>
);

export const IconSortBoth = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 6.5L8 3.5l3 3M5 9.5l3 3 3-3" />
  </Svg>
);
