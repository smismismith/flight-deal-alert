import { describe, expect, it } from "vitest";
import {
  addDays,
  diffDays,
  formatAxisDate,
  formatDate,
  formatDateSpoken,
  formatDateTime,
  formatDestination,
  formatDuration,
  formatManwon,
  formatPctAbs,
  formatPctSigned,
  formatPrice,
  formatRating,
  formatRunDuration,
  formatStops,
  formatTrip,
  formatTripShort,
  isWeekend,
  levelLabel,
  ymdToKstMs,
} from "./format";

describe("가격 형식", () => {
  it("천 단위 쉼표와 원을 붙인다", () => {
    expect(formatPrice(338000)).toBe("338,000원");
    expect(formatPrice(1779200)).toBe("1,779,200원");
    expect(formatPrice(0)).toBe("0원");
  });
  it("히트맵 칸은 만원 단위 소수 1자리다", () => {
    expect(formatManwon(338000)).toBe("33.8");
    expect(formatManwon(1779200)).toBe("177.9");
    expect(formatManwon(130800)).toBe("13.1");
    expect(formatManwon(100000)).toBe("10.0");
  });
});

describe("날짜 형식", () => {
  it("M/D(요일)", () => {
    expect(formatDate("2026-12-21")).toBe("12/21(월)");
    expect(formatDate("2026-12-17")).toBe("12/17(목)");
    expect(formatDate("2027-01-03")).toBe("1/3(일)");
  });
  it("형식이 틀린 값은 그대로 반환한다", () => {
    expect(formatDate("2026/12/21")).toBe("2026/12/21");
  });
  it("일정 형식", () => {
    expect(formatTrip("2026-12-21", "2026-12-25", 4)).toBe("12/21(월) ~ 12/25(금) · 4박");
    expect(formatTripShort("2026-12-21", 4)).toBe("12/21 출발 · 4박");
  });
  it("접근성 이름용 날짜", () => {
    expect(formatDateSpoken("2026-12-21")).toBe("12월 21일 월요일");
  });
  it("주말 판별", () => {
    expect(isWeekend("2026-12-19")).toBe(true);
    expect(isWeekend("2026-12-20")).toBe(true);
    expect(isWeekend("2026-12-21")).toBe(false);
  });
  it("날짜 계산은 연도를 넘어간다", () => {
    expect(addDays("2026-12-30", 5)).toBe("2027-01-04");
    expect(addDays("2026-12-29", 5)).toBe("2027-01-03");
    expect(diffDays("2026-12-21", "2026-12-25")).toBe(4);
  });
});

describe("시각 형식", () => {
  it("KST 문자열을 M/D HH:mm 으로 표시한다", () => {
    expect(formatDateTime("2026-11-19T09:24:48+09:00")).toBe("11/19 09:24");
    expect(formatDateTime("2026-11-05T00:03:00+09:00")).toBe("11/5 00:03");
  });
  it("다른 시간대 표기도 KST 로 변환한다", () => {
    expect(formatDateTime("2026-11-19T00:24:48Z")).toBe("11/19 09:24");
    expect(formatDateTime("2026-11-18T16:24:48-08:00")).toBe("11/19 09:24");
  });
  it("값이 없거나 틀리면 - 를 반환한다", () => {
    expect(formatDateTime(null)).toBe("-");
    expect(formatDateTime("잘못된 값")).toBe("-");
  });
  it("차트 축 날짜는 KST 날짜다", () => {
    expect(formatAxisDate(ymdToKstMs("2026-11-05"))).toBe("11/5");
    expect(formatAxisDate(Date.parse("2026-11-04T23:59:00+09:00"))).toBe("11/4");
  });
});

describe("그 외 형식", () => {
  it("소요 시간", () => {
    expect(formatDuration(295)).toBe("4시간 55분");
    expect(formatDuration(45)).toBe("45분");
    expect(formatDuration(120)).toBe("2시간");
    expect(formatRunDuration(4957)).toBe("1시간 22분");
  });
  it("경유", () => {
    expect(formatStops(0)).toBe("직항");
    expect(formatStops(1)).toBe("경유 1회");
  });
  it("비율", () => {
    expect(formatPctAbs(-20.1)).toBe("20.1");
    expect(formatPctSigned(12.8)).toBe("+12.8%");
    expect(formatPctSigned(-10)).toBe("-10.0%");
    expect(formatPctSigned(0)).toBe("0.0%");
    expect(formatPctSigned(-0.04)).toBe("0.0%");
  });
  it("평점, 목적지, 가격 수준", () => {
    expect(formatRating(4.3)).toBe("평점 4.3");
    expect(formatRating(4)).toBe("평점 4.0");
    expect(formatDestination("다낭", "베트남", false)).toBe("다낭 (베트남)");
    expect(formatDestination("제주", "대한민국", true)).toBe("제주");
    expect(levelLabel("low")).toBe("평소보다 낮음");
    expect(levelLabel(null)).toBe("수준 정보 없음");
  });
});
