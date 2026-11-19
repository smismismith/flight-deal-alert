# 연말 특가 항공권·호텔 알림 서비스 명세 (SPEC)

- 기준 문서: 승인된 계획(`enchanted-wishing-axolotl.md`). 범위는 계획을 따르고, 이 문서는 구현·검증에 필요한 규칙과 수치를 확정한다.
- 설정 값의 원본은 `config/trip.yaml`, `config/destinations.yaml`이다. 이 문서의 수치는 설정 기본값이며, 코드에 수치를 직접 쓰지 않고 설정에서 읽는다.
- 데이터 형식의 원본은 `schemas/*.schema.json`(JSON Schema draft 2020-12)이다. 모든 객체는 `additionalProperties: false`이므로 필드를 추가하려면 스키마를 먼저 수정한다.

## 1. 목적과 범위

| 항목 | 내용 |
|---|---|
| 사용자 | 1명(개인용) |
| 여행 조건 | 성인 1인, 왕복, 출발 2026-12-17 ~ 2026-12-30, 귀국 2027-01-03 이전(당일 포함), 3~7박 |
| 출발지 | ICN, GMP. 국내 목적지는 GMP→CJU 1개만 조회 |
| 목적지 | `config/destinations.yaml`의 60개(해외 59 + 제주). 목적지 코드는 목록 안에서 중복되지 않으며 목적지마다 출발 공항은 1개 |
| 수집 주기 | 하루 3회(KST 08시·14시·21시, cron UTC `0 23,5,12 * * *`) |
| 알림 | 텔레그램 봇 `sendMessage` |
| 사이트 | GitHub Pages 정적 사이트(Vite + React + TS). 서버·DB 없음 |
| 제외 | 예약·결제 기능, 로그인, 목록에 없는 목적지 검색, 편도·다구간 |

## 2. 기능 요구사항

### 2.1 항공권 수집 (FR-1)

1. 날짜 조합: 출발일 d(12/17~12/30)와 박수 n(3~7) 중 `d + n ≤ 2027-01-03`인 조합 **64개**. 출발일이 실행일(KST) 이전이거나 같은 조합은 제외한다.
2. 조회 순서(1회 실행):
   1. **대표 조합 조회**: 모든 목적지 × 대표 조합 6개(`sampling.representative_combos`) = 360건.
   2. **확대 조회**: 대표 조합 최저가가 낮은 순서로 상위 10개 목적지(`expand_top_n`)와, `alerts.json`에 `active` 알림이 있는 목적지를 나머지 58개 조합까지 조회한다. 대표 조합 가격이 하나도 없는 목적지는 확대 대상에서 제외한다.
   3. **기준가 갱신**: 3.2절 규칙에 따라 최대 100건.
3. 조회 방법: `fast_flights.create_query(...)` + `fetch_flights_html(query)`. 응답 HTML의 `<script class="ds:1">`을 자체 파서로 해석한다(`fast_flights.parser`는 사용하지 않는다). 모든 배열 인덱스는 없을 수 있으므로 없으면 해당 값만 null로 처리한다.
4. 항공편 필터: 경유 1회 이하(`max_stops`), 가는 편 총 소요 시간 1,500분 이하(`max_duration_minutes`, 소요 시간을 알 수 없으면 통과). 필터를 통과하고 가격이 있는 항공편(best + other 목록) 중 최저가를 그 조합의 가격으로 사용한다.
5. 소요 시간 `duration_minutes`: 항공편 배열의 `flight[9]`(픽스처에서 직항 1건으로만 확인된 값)를 사용하고, 없으면 구간별 `leg[11]` 합계를 사용한다.
6. 조회 결과 분류:

   | 분류 | 조건 | 처리 |
   |---|---|---|
   | 성공 | `ds:1` 해석 성공, 가격 있는 항공편 1건 이상 | 가격 기록 |
   | 결과 없음(`no_result`) | 해석 성공, 필터 통과 항공편 0건 | 조회 실패로 계산하지 않음. 기록 없음. 비율이 높으면 실행 결과에 반영(5장) |
   | 봇 확인(`bot_check`) | `ds:1` 없음 + 본문에 "Verifying your request" | 20초, 60초 대기 후 재시도(최대 2회). 이후에도 같으면 실패 |
   | 네트워크(`network`) | 시간 초과(30초)·연결 오류·HTTP 오류 | 봇 확인과 같은 재시도 |
   | 해석 오류(`parse`) | `ds:1`은 있으나 JSON 해석 실패 | 재시도 없이 실패 |

7. 요청 간격: 직전 요청 시작 후 6초 이상 + 0~2초 무작위 지연. 재시도 요청에도 적용한다.
8. 재시도 후 실패가 연속 8건이면 해당 실행의 남은 조회를 생략하고(`skipped`) 실행을 종료 처리한다(`aborted_reason` 기록).

### 2.2 저렴함 판정 (FR-2) — 3장 참조

### 2.3 호텔 (FR-3)

1. 텔레그램 알림을 새로 발송하는 건(신규·재알림)에 한해 조회한다. 유지 중인 알림은 다시 조회하지 않는다.
2. 숙박 기간: 체크인 = 가는 편 도착일(`arrive_date`, 없으면 `depart_date`), 체크아웃 = `return_date`.
3. `SERPAPI_KEY`가 있으면 SerpApi `google_hotels`를 호출한다. 파라미터: `q`=`hotel_query`, `check_in_date`, `check_out_date`, `adults=1`, `currency=KRW`, `gl=kr`, `hl=ko`, `sort_by=3`, `special_offers=true`. 결과가 0건이면 `special_offers`를 제외하고 1회 더 호출한다. `properties[]`에서 1박 요금 오름차순 상위 5개를 저장한다(`name`, `rate_per_night.extracted_lowest`, `total_rate.extracted_lowest`, `overall_rating`, `link`, 특가 문구 `deal` 또는 `deal_description`).
4. 호출 한도: 실행당 4회, 월 230회(`status.json`의 `serpapi.month`/`calls`로 집계). 한도 초과·키 없음·호출 오류이면 `source: "links"`로 저장한다(오류는 `errors`에 `kind: hotel`로 기록).
5. 검색 링크는 항상 저장한다.
   - Google Hotels: `https://www.google.com/travel/search?q={hotel_query}&checkin={YYYY-MM-DD}&checkout={YYYY-MM-DD}&hl=ko&gl=kr&curr=KRW`
   - 아고다: `https://www.agoda.com/ko-kr/search?textToSearch={hotel_query}&checkIn={YYYY-MM-DD}&los={박수}&rooms=1&adults=1&currency=KRW`
   - 두 링크의 날짜 파라미터 동작은 미검증이다. QA가 브라우저에서 직접 확인한다(AC-17).

### 2.4 알림 (FR-4) — 4장 참조

### 2.5 웹사이트 (FR-5) — 7장 참조

### 2.6 실행 방법 (FR-6)

- `uv run python -m collector.main` : 수집 → 판정 → 호텔 → 알림 → `data/` 저장.
- `--dry-run` : 텔레그램 발송과 `data/` 저장을 하지 않고 결과 요약을 표준 출력에 표시한다.
- `--destinations KIX,CJU` : 지정한 목적지만 조회. 지정하지 않은 목적지의 `latest.json` 항목은 변경하지 않는다. `--max-queries N` : 조회 건수 상한(초과분은 `skipped`).
- 실행 시간 상한: 시작 후 `pacing.max_run_minutes`(150분)가 지나면 남은 조회와 기준가 조회를 `skipped`로 처리하고 저장 절차를 진행한다. `aborted_reason`에 사유를 기록한다. `collect.yml`의 수집 단계 제한 시간(175분)보다 짧게 둔다.
- 대표 조합이 모두 실행일 이전이면(12/29 실행) 남은 전체 조합을 대표 조합으로 사용한다. 남은 조합이 0개이면(12/30 이후 실행) 조회·기준가 갱신·`data/` 가격 파일 저장을 하지 않고 `result: ok`, `aborted_reason: "출발 가능 기간이 끝나 조회 대상이 없음"`으로 `status.json`에 1회만 기록한다(종료 코드 0, 수집 중단 안내 없음).
- 종료 코드: 실행 결과가 `ok`·`partial`이면 0, `failed`이면 1. `failed`이어도 `status.json`은 저장한다.
- 비밀 값은 환경 변수로만 읽는다: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SERPAPI_KEY`(선택). 코드·설정·커밋에 포함하지 않는다. 토큰이 없으면 발송을 생략하고 `notification.sent=false`, `error`에 사유를 기록한다.

## 3. 판정 규칙

### 3.1 기준

판정 대상은 이번 실행에서 가격을 얻은 모든 조합이다. 가격 `P`는 2.1절 4항의 조합별 최저가(원, 정수)이다.

| 기호 | 이름(`criterion`) | 해당 조건 | 평가 조건(미충족 시 평가하지 않음) |
|---|---|---|---|
| a | `google_low` | `P < typical_low` | Google 가격 정보에 `typical_low`, `typical_high`가 있음 |
| b | `offseason` | `P ≤ 기준가` (같은 출발지·목적지·박수) | `baseline.json`에 해당 항목이 있음 |
| c | `own_history` | `P ≤ 중앙값 × 0.85` | 해당 목적지의 과거 이력이 9건 이상 |
| d | `google_60d` | `P ≤ P10` | Google 가격 이력에서 마지막 점을 제외한 점이 30개 이상 |

- **특가(`is_deal`)**: 해당한 기준이 **2개 이상**(`judge.min_criteria`). 평가하지 않은 기준은 해당하지 않은 것으로 계산한다.
- 기준 a: Google 원본 코드(`payload[5][0]`)는 의미가 확인되지 않아 `google_code`로 저장만 하고 판정에 사용하지 않는다. `level`은 `P < typical_low` → `low`, `P > typical_high` → `high`, 그 외 `typical`.
- 기준 c: 중앙값은 `history/{DEST}.json`의 `points[].rep_price_krw`(대표 조합 6개의 최저가) 중 **이번 실행을 제외한** 값의 중앙값이다. null인 점은 제외한다. 확대 조회 여부에 따라 최저가 범위가 달라지는 문제를 방지하기 위해 대표 조합 값만 사용한다.
- 기준 d: Google 가격 이력(`payload[5][10][0]`, 일별 약 61개)의 시각(ms)을 KST 날짜로 변환한다. 마지막 점은 조회 당일의 현재가와 같으므로(픽스처 2건에서 확인) 계산에서 제외한다. `P10`은 남은 값을 오름차순 정렬한 뒤 `ceil(0.10 × n) − 1`번째(0부터) 값이다. 60일 최저가 이하인 경우는 이 조건에 포함된다. 기준 d는 계획의 선택 항목(SerpApi `price_insights` 재확인)을 대체한다. 같은 이력을 조회 페이지에서 직접 얻기 때문이다.
- 기준 a와 d는 비교 대상이 다르다(a: 해당 노선의 평소 가격 범위, d: 같은 날짜 조합의 최근 약 60일 가격). 따라서 a + d 두 개만으로도 특가로 판정한다.
- 비교 계산은 정수로 한다(부동소수점 오차 방지): 기준 c는 `P × 100 ≤ 중앙값 × 85`, 재알림은 `P × 100 ≤ L × 95`.
- 비율 표기: `pct = round((P − 비교값) / 비교값 × 100, 1)`. 음수이면 비교값보다 저렴하다.
- 목적지의 `best` = 조합 중 최저가 기록, `deal` = `is_deal`인 기록 중 최저가(없으면 null).

### 3.2 비성수기 기준가

- 출발 2027-03-09(화), 귀국 = 출발 + 박수(3~7). 목적지당 5건, 전체 300건.
- 필터와 가격 산정은 2.1절 4항과 같다.
- 항목이 없거나 `collected_at`이 7일을 초과하면 갱신 대상이다. 오래된 순서로 실행당 최대 100건을 조회한다. 조회에 실패하면 기존 값을 유지한다.

### 3.3 판정 예시(샘플 데이터)

| 목적지 | 가격 | a | b | c | d | 결과 |
|---|---|---|---|---|---|---|
| DAD 12/21 4박 | 338,000 | 해당(typical_low 365,000) | 미해당(기준가 299,700) | 해당(중앙값 대비 −20.1%) | 해당 | 특가(3개) |
| FUK 12/18 3박 | 219,000 | 해당(typical_low 230,000) | 해당(기준가 224,000) | 미해당(−14.2%) | 미해당 | 특가(2개) |

## 4. 알림 규칙

### 4.1 발송 조건

실행마다 목적지별로 `deal` 기록 1건만 대상이다.

| 상황 | 처리 |
|---|---|
| 해당 목적지에 발송 완료(`notification.sent=true`) 알림이 없음 | **신규 발송**(`kind: new`) |
| 직전 발송 가격 `L`이 있고 `P ≤ L × 0.95` | **재발송**(`kind: realert`). 기존 `active` 알림은 `replaced`로 변경 |
| `P > L × 0.95` 이고 특가 유지 | 발송하지 않음. 기존 알림의 `current_fare`, `current_checked_at`만 갱신. 기존 알림이 `ended`였다면 `active`로 되돌린다(발송 없음) |
| 이번 실행에서 가격을 얻었고, 특가였던 조합의 응답(성공 또는 결과 없음)을 받았으며 `deal`이 없음 | 해당 목적지의 `active` 알림을 `ended`로 변경(`ended_at` 기록, `current_fare=null`) |
| 특가였던 조합을 이번 실행에서 조회하지 못함(조회 실패, 상한·중단·시간 상한으로 생략) | 이전 `deal` 값과 알림 상태를 유지한다(`current_checked_at`도 변경하지 않음). 미발송 알림만 다시 발송한다 |
| 이번 실행에서 해당 목적지의 가격을 1건도 얻지 못함(`stale`) 또는 조회 대상이 아님 | 알림 상태를 변경하지 않음 |

- 직전 발송 가격 `L` = 해당 목적지에서 `notification.sent=true`인 가장 최근 알림의 `alerted_price_krw`. 상태(`active`/`replaced`/`ended`)와 관계없이 적용한다.
- 발송 실패(`sent=false`)인 `active` 알림은 다음 실행에서 같은 레코드의 `fare`를 갱신하고 발송을 다시 시도한다(`attempts` 증가). 실패는 `errors`에 `kind: telegram`으로 기록하고 실행 결과(`result`)에는 반영하지 않는다.
- 불변 조건: 목적지당 `active` 알림은 최대 1건이고, `latest.json`의 `deal != null` ⇔ 해당 목적지에 `active` 알림이 있음.

### 4.2 메시지 형식

`parse_mode=HTML`, `disable_web_page_preview=true`. 값은 HTML 이스케이프한다. 알림 1건당 메시지 1개.

```
[특가] 다낭(베트남) 338,000원
12/21(월) ~ 12/25(금) · 4박 · 인천(ICN) 출발
비엣젯항공 · 직항 · 4시간 55분
판정 근거(3개)
- Google 평소 가격 하한(365,000원)보다 7.4% 저렴
- 수집 이력 중앙값(423,000원)보다 20.1% 저렴
- 최근 60일 가격 하위 10% 이하(60일 최저가 대비 -10.0%)
비성수기 기준가(299,700원) 대비 +12.8%
항공권 검색: <링크>
호텔(12/21~12/25, 1박 요금)
1. 사노우바 다낭 호텔 38,900원 · 평점 4.3 · 평소보다 21% 저렴
2. ...
호텔 검색: Google Hotels <링크> · 아고다 <링크>
사이트: <notify.site_url>
```

- 재발송이면 첫 줄을 `[특가·추가 인하] … 338,000원 (직전 알림 359,000원)`으로 표시한다.
- 판정 근거에는 해당한 기준만 표시한다. 기준 b에 해당하지 않아도 기준가가 있으면 대비 비율을 한 줄로 표시한다.
- 호텔 목록은 `source: serpapi`일 때 상위 3개만 표시하고, `links`이면 "호텔 검색" 줄만 표시한다. "사이트" 줄은 `{site_url}#dest={목적지 코드}` 형식이다(사이트에서 해당 목적지 상세가 선택된다). `notify.site_url`이 비어 있으면 환경 변수 `GITHUB_REPOSITORY`(GitHub Actions 기본 제공)로 `https://{계정}.github.io/{저장소}/`를 사용하고, 둘 다 없으면 줄을 생략한다.

## 5. 실패 처리

| 실행 결과(`result`) | 조건 |
|---|---|
| `ok` | 실패 조회 0건이고 `no_result` 비율이 50%(`failure.max_no_result_ratio`) 이하. 또는 출발 가능 기간 종료로 조회 대상 없음(2.6절) |
| `partial` | 실패 조회 1건 이상 또는 `no_result` 비율 50% 초과이고, 응답 비율(`(succeeded + no_result) / attempted`)이 50% 이상 |
| `failed` | 응답 비율 50% 미만, `attempted = 0`, `succeeded = 0`(가격을 1건도 얻지 못함), 또는 처리 중 예외로 종료 |

- `no_result`가 비정상적으로 많은 경우(`succeeded = 0` 또는 비율 50% 초과)는 `errors`에 `kind: other`로 기록한다. Google 응답 형식 변경이나 조회 제한으로 항공편 목록이 빈 응답이 올 때 기존 데이터를 지우지 않기 위한 규칙이다.
- `failed` 실행에서도 성공한 조회 결과는 저장한다.
- 목적지 단위 저장 규칙:
  - 이번 실행의 조회 대상이 아닌 목적지: 이전 항목을 변경하지 않는다.
  - 조회 대상이지만 가격을 1건도 얻지 못한 목적지(조회 실패, 결과 없음, 생략): `latest.json`의 이전 값을 유지하고 `stale: true`로 표시하며 이력 점을 추가하지 않는다. 이전 값이 없으면 `best: null`이고, 조회 실패가 있었을 때만 `stale: true`이다.
  - 가격을 얻은 목적지: 응답을 받지 못한 조합(조회 대상 중 실패한 조합. 실행이 상한·중단으로 끝났으면 조회하지 못한 나머지 조합 포함)은 이전 실행의 `combos` 값과 `best`·`deal` 기록을 유지한다. `best`는 전체 기록이 있는 요금(이번 실행 결과와 유지한 `best`·`deal`) 중 최저가이며, 그보다 낮은 이전 `combos` 값은 제외한다. 이력 점은 이번 실행에서 얻은 가격만으로 만든다.
- `consecutive_failures`: `failed`이면 +1, `ok`·`partial`이면 0.
- **수집 중단 안내**: `consecutive_failures`가 3이 된 실행에서 텔레그램으로 1회 발송하고 `stop_notice_sent=true`, `state="stopped"`로 저장한다. 이후 실패가 계속되어도 다시 발송하지 않는다.
  - 문구: `[수집 중단] 항공권 수집이 3회 연속 실패했습니다. 마지막 성공: {last_success_at}. 주요 원인: {가장 많은 오류 종류}. 다음 실행부터 정상 수집되면 재개 안내를 발송합니다.`
- **수집 재개 안내**: `stop_notice_sent=true` 상태에서 `ok`·`partial` 실행이 발생하면 `[수집 재개] 항공권 수집이 다시 정상 처리되었습니다.`를 1회 발송하고 `stop_notice_sent=false`로 저장한다.
- `status.json`의 `errors`는 실행당 최대 50건, `runs`는 최신순 30건을 보관한다.

## 6. 데이터 계약

### 6.1 파일

| 파일 | 스키마 | 주요 필드 |
|---|---|---|
| `data/index.json` | `index.schema.json` | `generated_at`, `run_id`, `is_sample`, `destinations[]`(`destination`, `origin`, `city_ko`, `country_ko`, `region`, `is_domestic`, `best_price_krw`, `is_deal`, `history_file`) |
| `data/latest.json` | `latest.schema.json` | `trip`, `destinations[]`(`expanded`, `stale`, `last_success_at`, `best`, `deal`, `combos[]`) |
| `data/history/{DEST}.json` | `history.schema.json` | `points[]`(`collected_at`, `run_id`, `price_krw`, `rep_price_krw`, 날짜·박수, `combos_checked`), 시각 오름차순, 최대 400건 |
| `data/baseline.json` | `baseline.schema.json` | `entries[]`(`origin`, `destination`, `nights`, `price_krw`, 날짜, `collected_at`) |
| `data/alerts.json` | `alerts.schema.json` | `alerts[]`(`id`, `status`, `kind`, `alerted_price_krw`, `previous_alerted_price_krw`, `fare`, `current_fare`, `notification`, `hotels`), 최신순, 최대 200건 |
| `data/status.json` | `status.schema.json` | `state`, `consecutive_failures`, `stop_notice_sent`, `last_success_at`, `serpapi`, `last_run`, `runs[]` |

### 6.2 공통 규칙

- 시각: ISO 8601, KST 고정(`2026-11-19T08:02:11+09:00`). 날짜: `YYYY-MM-DD`. `run_id`: 실행 시작 시각 `YYYYMMDDTHHMMSS`(KST).
- 가격: 원 단위 정수, 성인 1인 왕복 총액.
- `region`: `국내 | 일본 | 중화권 | 동남아 | 대양주 | 유럽 | 미주 | 기타`(한국어 문자열 그대로 사용).
- **가격 기록 `fare`**(`best`, `deal`, 알림의 `fare`/`current_fare`): 출발지·목적지·도시·국가·지역, 출발·귀국일, 박수, `is_representative`, 가격, 항공사 코드·이름, 경유 횟수, 소요 시간, 출발·도착 시각, 검색 URL(`query.url()`), `insight`(Google 가격 정보: `typical_low_krw`, `typical_high_krw`, `level`, `history_min_krw`, `history_p10_krw`, `history[]` 등. 없으면 null), `judgement`(`evaluated`, `matched`, `matched_count`, `is_deal`, 기준가·중앙값과 대비 비율), `collected_at`.
- **조합 기록 `combo`**(`combos[]`, 히트맵용): 파일 크기를 줄이기 위해 `insight.history`를 제외한 축약 형식이다(`price_krw`, `level`, `matched`, `is_deal`, `search_url` 등).
- `index.json`과 `latest.json`의 목적지 순서는 `config/destinations.yaml` 순서와 같다. `best_price_krw`, `is_deal`은 `latest.json`과 일치해야 한다.
- 파일 저장은 임시 파일에 쓴 뒤 이름을 바꾸는 방식으로 한다(중간 상태의 파일이 커밋되지 않도록).
- 검증: `uv run python schemas/validate.py [폴더]`(기본 `web/public/sample-data`). 스키마 검증과 위 교차 규칙을 함께 확인하며 오류가 있으면 종료 코드 1.

### 6.3 사이트가 데이터를 읽는 방법

- 배포: `deploy.yml`이 `web`을 빌드한 뒤 저장소의 `data/`를 빌드 결과의 `./data/`로 복사한다(`cp -r data web/dist/data`). Vite `base`는 `./`로 설정한다.
- `collect.yml`이 `GITHUB_TOKEN`으로 푸시한 커밋은 다른 워크플로를 실행시키지 않는다. 따라서 `deploy.yml`은 `workflow_run`(collect 완료), `push`(main), `workflow_dispatch`로 실행되게 설정한다.
- 프런트엔드 읽기 순서:
  1. `${BASE_URL}data/index.json`을 `cache: "no-store"`로 요청한다.
  2. 성공하면 같은 폴더에서 `latest.json`, `alerts.json`, `status.json`, `baseline.json`을 읽는다. `history/{DEST}.json`은 목적지 상세를 열 때 읽는다.
  3. 실패(404·네트워크·JSON 오류)했을 때, 개발 모드(`import.meta.env.DEV`)이거나 주소에 `?sample=1`이 있으면 `${BASE_URL}sample-data/`를 같은 방식으로 읽는다. `?sample=1`이 있으면 1번을 생략하고 샘플을 읽는다.
  4. 운영 환경에서 실패하면 샘플로 대체하지 않고 오류 화면을 표시한다.
- `index.json`의 `is_sample`이 true이면 화면 상단에 "샘플 데이터" 표시를 한다.
- 샘플 데이터(`web/public/sample-data/`): 목적지 15개(제주 포함), `active` 알림 2건(DAD: SerpApi 호텔 5개, FUK: 링크만), `replaced` 1건, `ended` 1건, 목적지별 이력 42~43점, 마지막 실행 `partial`(CDG 6건 봇 확인 실패 → `stale`, CTS 2건 시간 초과), 과거 `failed` 실행 1건, Google 가격 정보가 없는 목적지 1개(SYD).

## 7. 화면 요구사항(프런트엔드)

모바일(폭 360~430px) 우선. 모든 문구는 한국어. 가격은 `338,000원` 형식, 시각은 KST `11/19 09:24` 형식.

| 번호 | 화면 요소 | 데이터 | 내용 |
|---|---|---|---|
| V1 | 수집 상태 | `status.json` | 마지막 수집 시각, 상태(정상/일부 실패/실패/수집 중단), 실패 목적지 수. 누르면 최근 실행 목록과 오류 표시 |
| V2 | 오늘의 특가 | `alerts.json`의 `active` | 목적지, 가격(`current_fare`), 날짜·박수, 항공사·경유, 판정 근거(해당 기준별 문구와 비율), 항공권 검색 링크, 호텔 |
| V3 | 호텔 카드 | 알림의 `hotels` | `serpapi`: 이름·1박 요금·총액·평점·특가 문구·링크. 항상 Google Hotels·아고다 검색 링크 표시 |
| V4 | 목적지별 최저가 표 | `latest.json` | 목적지·지역·가격·날짜·박수·`level`·특가 여부. 가격순 정렬(기본), 지역 필터. `stale`이면 "이전 수집 값" 표시 |
| V5 | 출발일×박수 히트맵 | 선택한 목적지의 `combos[]` | 출발일 14칸 × 박수 5칸. 가격이 낮을수록 진한 색, 조회하지 않은 칸과 조건 밖 칸은 구분해 표시. 칸을 누르면 가격·항공사와 검색 링크 표시 |
| V6 | 가격 추이 차트 | `history/{DEST}.json`, `best.insight.history` | 수집 이력(`price_krw`) 선, Google 최근 60일 가격 선, 기준가·`typical_low`/`typical_high` 보조선 |
| V7 | 지난 알림 | `alerts.json`의 `replaced`·`ended` | 발송 시각, 가격, 상태 |

판정 근거 문구(메시지·화면 공통):

| 기준 | 문구 |
|---|---|
| `google_low` | Google 평소 가격 하한({typical_low}원)보다 {n}% 저렴 |
| `offseason` | 비성수기 기준가({baseline}원) 이하({n}%) |
| `own_history` | 수집 이력 중앙값({median}원)보다 {n}% 저렴 |
| `google_60d` | 최근 60일 가격 하위 10% 이하 |

## 8. 수용 기준

### 8.1 백엔드

| 번호 | 기준 | 확인 방법 |
|---|---|---|
| AC-01 | 날짜 조합 생성 결과가 64개이고 모두 `d+n ≤ 2027-01-03`, 3~7박이다. 대표 조합 6개는 64개에 포함된다. 실행일 이전 출발 조합은 제외된다. 대표 조합이 남지 않으면 남은 전체 조합을 조회하고, 조합이 0개이면 조회 없이 `ok`로 종료한다 | 단위 테스트(실행일 고정) |
| AC-02 | 픽스처 `page_ICNKIX.html`, `page_GMPCJU.html` 해석 결과가 항공편 1건 이상이고 최저가가 각각 356,100원, 107,400원이다. 가격 정보는 `typical_low/high`가 290,000/445,000, 65,000/160,000이고 이력 점은 61개다 | 단위 테스트 |
| AC-03 | 임의 위치의 값을 null로 바꾸거나 배열을 잘라낸 payload에서도 예외 없이 해석하고, 가격이 없는 항공편은 제외한다 | 단위 테스트 |
| AC-04 | `page_verify.html`을 `bot_check`로 분류한다. 20초·60초 대기 후 최대 2회 재시도하고, 재시도에서 성공하면 성공으로 기록하며 `bot_checks`·`retries`가 증가한다 | HTTP·sleep 모의 객체 |
| AC-05 | 연속 요청 시작 시각 간격이 6초 이상이다 | sleep 모의 객체로 호출 값 확인 |
| AC-06 | 경유 2회 이상 또는 소요 시간 1,500분 초과 항공편은 최저가 계산에서 제외한다 | 단위 테스트 |
| AC-07 | 기준 a~d 경계값: a는 `P = typical_low`이면 미해당·1원 낮으면 해당, b는 `P = 기준가`이면 해당·1원 높으면 미해당, c는 `P = 중앙값×0.85`이면 해당·이력 8건이면 평가하지 않음, d는 `P = P10`이면 해당·마지막 점 제외 후 29개이면 평가하지 않음 | 단위 테스트 |
| AC-08 | 해당 기준 2개 이상일 때만 `is_deal=true`. `matched ⊆ evaluated`, `matched_count = len(matched)`. Google 가격 정보가 null이면 a·d는 평가하지 않는다 | 단위 테스트 |
| AC-09 | 기준 c의 중앙값은 이번 실행을 제외한 `rep_price_krw`로 계산한다. 기준 d는 이력의 마지막 점을 제외하고 계산한다 | 단위 테스트 |
| AC-10 | 대표 조합 최저가 하위 10개 목적지와 `active` 알림이 있는 목적지만 확대 조회한다 | HTTP 모의 객체로 조회 목록 확인 |
| AC-11 | 재알림: 직전 발송가 359,000원일 때 341,050원(정확히 5% 낮음)은 발송, 341,100원은 발송하지 않는다. 발송 시 기존 알림은 `replaced`가 된다 | 단위 테스트 |
| AC-12 | 특가가 해제되면 `ended`, 조회 실패(`stale`) 목적지와 특가 조합을 조회하지 못한 목적지는 상태 유지, 5% 미만 하락은 `current_fare`만 갱신한다. 목적지당 `active`는 1건 이하다 | 단위 테스트 |
| AC-13 | 텔레그램 메시지에 목적지·날짜·박수·가격·항공사·경유·해당 기준 문구·항공권 검색 링크·호텔 검색 링크가 포함되고 HTML 이스케이프가 적용된다. 발송은 모의 HTTP로만 확인하며 요청 주소·본문에 토큰 외 비밀 값이 없다 | HTTP 모의 객체 |
| AC-14 | 토큰이 없거나 발송에 실패하면 `sent=false`와 사유를 기록하고 다음 실행에서 같은 레코드로 다시 시도한다. 실행 결과는 바뀌지 않는다 | 단위 테스트 |
| AC-15 | `SERPAPI_KEY`가 없으면 외부 호출 없이 `source: links`와 두 검색 링크를 저장한다. 키가 있으면 2.3절 파라미터로 호출하고 상위 5개를 저장한다. 0건이면 필터 없이 1회 더 호출한다. 오류·한도 초과이면 `links`로 저장한다 | HTTP 모의 객체 |
| AC-16 | 기준가: 항목이 없거나 7일을 초과한 것만, 실행당 100건 이하로 조회한다. 실패 시 기존 값을 유지한다. 결과 없음은 `checked_at`(기존 값이 없으면 `price_krw: null` 항목)으로 기록해 7일 동안 다시 조회하지 않는다 | 단위 테스트 |
| AC-17 | 호텔 검색 링크 2종을 브라우저에서 열면 지정한 지역·날짜로 검색된다 | 수동 확인(미검증 항목) |
| AC-18 | 실행 결과 분류는 5장 표와 같다(가격 0건이면 `failed`, 결과 없음 50% 초과이면 `partial`). 연속 실패 8건 또는 실행 시간 150분 초과이면 남은 조회를 `skipped`로 기록하고 저장 후 종료한다 | 단위 테스트 |
| AC-19 | `failed` 3회 연속인 실행에서 "수집 중단" 안내를 1회만 발송하고 `state=stopped`가 된다. 4회째에는 발송하지 않는다. 이후 성공하면 "수집 재개" 안내를 1회 발송한다 | HTTP 모의 객체 |
| AC-20 | 수집 결과로 생성한 `data/`가 `uv run python schemas/validate.py data`를 통과한다(스키마 + 교차 규칙) | 모의 수집 실행 후 검증 |
| AC-21 | 가격을 1건도 얻지 못한 조회 대상 목적지는 `latest.json`의 이전 값과 `stale: true`를 유지하고 이력 점이 추가되지 않는다. 이력은 목적지당 400건, 알림 200건, 실행 30건을 넘지 않는다 | 단위 테스트 |
| AC-22 | `--dry-run`은 텔레그램 요청과 `data/` 쓰기를 하지 않는다. 종료 코드는 `ok`·`partial` 0, `failed` 1 | 단위 테스트 |
| AC-23 | 저장소 전체에 토큰·키 값과 `.env` 파일이 없고, 비밀 값은 환경 변수에서만 읽는다 | 코드 검색, `git ls-files` |
| AC-24 | `uv run python -m collector.main --dry-run --destinations KIX,CJU --max-queries 4`가 실제 조회로 가격을 출력한다(요청 간격 6초 이상) | 실제 조회(QA 1회) |

### 8.2 프런트엔드

| 번호 | 기준 | 확인 방법 |
|---|---|---|
| AC-31 | `web`에서 `npm run build`가 오류 없이 끝나고 타입 검사를 통과한다 | 명령 실행 |
| AC-32 | 개발 모드에서 `data/`가 없으면 `sample-data/`를 읽고 "샘플 데이터" 표시가 나타난다. `?sample=1`도 같은 결과다 | 브라우저 확인 |
| AC-33 | 빌드 결과에 `data/`를 복사하면 `data/`를 읽고 샘플 표시는 나타나지 않는다. 운영 빌드에서 `data/index.json`이 없으면 샘플로 대체하지 않고 오류 문구를 표시한다 | 빌드 결과 미리보기 |
| AC-34 | V1: 마지막 수집 시각(11/19 09:24), 상태 "일부 실패", 실패 목적지 1개(CDG)를 표시한다. `state=stopped` 데이터에서는 "수집 중단"을 표시한다 | 샘플·변형 데이터 |
| AC-35 | V2: 샘플에서 특가 2건(다낭 338,000원, 후쿠오카 219,000원)을 표시하고, 각 건에 해당 기준 문구(다낭 3개, 후쿠오카 2개)와 비율, 항공권 검색 링크가 있다. `active` 알림이 0건이면 "현재 특가가 없습니다" 문구를 표시한다 | 샘플·변형 데이터 |
| AC-36 | V3: 다낭은 호텔 5개(이름·1박 요금·평점·특가 문구)와 검색 링크 2종, 후쿠오카는 검색 링크 2종만 표시한다 | 샘플 데이터 |
| AC-37 | V4: 15개 목적지를 가격 오름차순으로 표시하고(첫 행 제주 130,800원), 지역 필터가 동작한다. CDG에 "이전 수집 값" 표시가 있다. `best=null`인 목적지는 "가격 없음"으로 표시한다 | 샘플·변형 데이터 |
| AC-38 | V5: 확대 조회 목적지(예: KIX)는 64칸, 그 외(예: BKK)는 6칸에 가격을 표시한다. 조건 밖 칸(예: 12/30 출발 5박)과 조회하지 않은 칸을 서로 다르게 표시한다. 칸을 누르면 검색 링크가 열린다 | 샘플 데이터 |
| AC-39 | V6: 목적지를 선택하면 수집 이력 선과 Google 60일 가격 선을 표시한다. Google 가격 정보가 없는 SYD는 수집 이력만 표시하고 오류가 발생하지 않는다 | 샘플 데이터 |
| AC-40 | V7: 지난 알림 2건(DAD `replaced`, TPE `ended`)을 표시한다 | 샘플 데이터 |
| AC-41 | 폭 375px에서 가로 스크롤이 발생하지 않고(표·히트맵은 영역 내부 스크롤 허용), 폭 1280px에서도 정상 배치된다 | 스크린샷 |
| AC-42 | 모든 외부 링크는 새 탭으로 열리고 `rel="noopener noreferrer"`가 있다. 데이터의 문자열은 HTML로 해석하지 않고 텍스트로 표시한다 | 코드 검토 |
| AC-43 | 화면 문구가 모두 한국어이고 가격·시각 형식이 7장 규칙과 같다 | 화면 검토 |
| AC-44 | 브라우저 콘솔에 오류가 없다(샘플 데이터, 운영 빌드) | 브라우저 확인 |

### 8.3 배포

| 번호 | 기준 | 확인 방법 |
|---|---|---|
| AC-51 | `collect.yml`: cron `0 23,5,12 * * *` + `workflow_dispatch`, 비밀 값은 Secrets에서 환경 변수로 전달, 수집 결과가 `failed`여도 `data/` 변경분을 커밋한다 | 파일 검토 |
| AC-52 | `deploy.yml`: 빌드 후 `data/`를 `web/dist/data/`로 복사하고 collect 완료·push·수동 실행으로 동작한다 | 파일 검토 |

## 9. 제한 사항

- Google Flights 조회는 비공식 방식이므로 응답 구조 변경이나 차단으로 중단될 수 있다. 중단되면 5장의 안내로 알린다. GitHub Actions 서버 IP에서의 차단 여부는 미검증이다.
- 조회량: 실행당 약 940건(360 + 580) + 기준가 최대 100건, 6~8초 간격으로 약 1시간 40분~2시간 20분이 걸린다. `active` 알림이 있는 목적지가 상위 10개 밖이면 목적지당 58건이 늘어난다.
- 확대 대상은 절대 가격 기준이므로 단거리 노선이 주로 선정된다. 장거리 목적지는 대표 조합 6개로만 판정한다.
- 기준 c는 대표 조합 기준 중앙값과 비교하므로, 확대 조회로 찾은 조합은 대표 조합보다 낮은 가격일 가능성이 높다. 이 차이는 2개 이상 기준 조건으로 보완한다.
- 기준 b는 연말 성수기 특성상 해당 빈도가 낮을 수 있다.
