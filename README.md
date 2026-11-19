# 연말 특가 항공권·호텔 알림

2026-12-17 ~ 2027-01-03 기간에 인천·김포에서 출발하는 왕복 항공권 가격을 하루 3회 수집하고, 평소보다 저렴한 가격을 찾으면 텔레그램으로 알림을 보내는 개인용 서비스입니다. 규칙과 데이터 형식은 `docs/SPEC.md`와 `schemas/`를 기준으로 합니다.

## 처음 설정하는 순서

1. 텔레그램 봇을 만들고 토큰과 chat id를 확인합니다(아래 "알림 방식").
2. 이 폴더를 GitHub 저장소에 올립니다(기본 브랜치 `main`).
3. 저장소 Settings → Secrets and variables → Actions에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`(선택: `SERPAPI_KEY`)를 등록합니다.
4. 저장소 Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 지정합니다. 지정하지 않으면 `deploy.yml`의 Pages 단계가 실패합니다.
5. Actions 탭에서 `collect`를 수동 실행(Run workflow)합니다. 수집이 끝나면 `data/`가 커밋되고 `deploy`가 실행되어 사이트가 배포됩니다.
6. 사이트 주소는 `https://{계정}.github.io/{저장소}/`입니다. 텔레그램 메시지의 "사이트" 줄은 이 주소를 자동으로 사용합니다. 사용자 지정 도메인을 사용하면 `config/trip.yaml`의 `notify.site_url`에 그 주소를 입력합니다.
7. 2026-12-30 이후에는 조회할 출발일이 없습니다. 수집기는 조회 없이 종료하지만 예약 실행은 계속되므로, Actions 탭 → `collect` → `···` → Disable workflow로 비활성화합니다.

## 알림 방식

- 알림은 텔레그램 봇으로 발송합니다. 무료이고, 휴대폰 푸시 알림이 바로 표시되며, 서버 없이 HTTP 요청 1건으로 발송할 수 있어 선택했습니다.
- 이메일 발송은 지원하지 않습니다. 이메일은 SMTP 계정 또는 발송 서비스 가입이 필요하고 스팸으로 분류될 수 있습니다. 대안으로 Discord·Slack 웹훅, ntfy 같은 푸시 서비스가 있으며, 추가하려면 `collector/notify.py`의 발송 부분을 변경합니다.
- 봇 생성 절차:
  1. 텔레그램에서 `@BotFather`와 대화를 열고 `/newbot`을 보냅니다. 봇 이름과 사용자 이름(`_bot`으로 끝남)을 입력하면 토큰을 받습니다.
  2. 만든 봇과 대화를 열고 아무 메시지나 1건 보냅니다.
  3. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates`를 열어 `message.chat.id` 값을 확인합니다.
  4. 토큰은 `TELEGRAM_BOT_TOKEN`, chat id는 `TELEGRAM_CHAT_ID`로 등록합니다.
- 메시지 내용: 목적지, 날짜, 가격, 항공사·경유, 판정 근거, 항공권 검색 링크, 호텔(SerpApi 키가 있으면 상위 3개), 호텔 검색 링크, 사이트 링크(`#dest={목적지 코드}` 포함. 해당 목적지 상세가 선택됩니다).
- 날짜별 가격 표, 가격 추이, 호텔 5개는 사이트에서 확인합니다.

## 사이트(프런트엔드)

`web/`은 Vite + React + TypeScript로 만든 정적 사이트입니다. `data/*.json`을 읽어 특가 목록, 목적지별 최저가, 출발일 × 박수 가격, 가격 추이, 호텔, 수집 상태를 표시합니다. Node.js 22가 필요합니다.

```bash
cd web
npm ci
npm run dev        # 개발 서버. data/ 가 없으면 샘플 데이터(web/public/sample-data)를 표시
npm test           # 단위 테스트
npm run build      # 형식 검사 후 web/dist 에 빌드
npm run preview    # 빌드 결과 확인. 주소 뒤에 ?sample=1 을 붙이면 샘플 데이터를 표시
```

- 운영 환경에서는 `{사이트 주소}/data/`의 파일만 읽습니다. `?sample=1`을 붙인 경우에만 샘플 데이터를 표시합니다.
- 배포는 `.github/workflows/deploy.yml`이 처리합니다. `web/` 또는 `data/`가 변경되거나 `collect`가 끝나면 빌드 후 `data/`를 `web/dist/data/`로 복사해 GitHub Pages에 배포합니다.
- 화면 명세는 `docs/DESIGN.md`를 기준으로 합니다.

## 수집기(백엔드)

### 구성

| 경로 | 내용 |
|---|---|
| `collector/flights.py` | Google Flights 조회(요청 간격, 재시도, 봇 확인 페이지 감지)와 응답 해석 |
| `collector/judge.py` | 저렴함 판정(기준 4개 중 2개 이상 해당하면 특가) |
| `collector/baseline.py` | 비성수기(2027-03-09 출발) 기준가 조회, 7일 주기 갱신 |
| `collector/alerts.py` | 알림 상태 관리(신규, 재알림, 유지, 종료) |
| `collector/hotels.py` | 호텔 조회(SerpApi) 또는 검색 링크 생성 |
| `collector/notify.py` | 텔레그램 메시지 작성과 발송 |
| `collector/store.py` | `data/*.json` 읽기·쓰기 |
| `collector/main.py` | 실행 명령 |
| `config/trip.yaml`, `config/destinations.yaml` | 여행 조건, 판정 임계값, 목적지 목록 |
| `.github/workflows/collect.yml` | 예약 실행(KST 08시, 14시, 21시)과 `data/` 커밋 |

### 설치

[uv](https://docs.astral.sh/uv/)와 Python 3.12가 필요합니다.

```bash
uv sync
```

### 비밀 값

비밀 값은 환경 변수로만 읽습니다. 코드, 설정 파일, 커밋에 포함하지 않습니다. `.env` 파일은 `.gitignore`에 포함되어 있습니다.

| 환경 변수 | 필수 | 용도 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 알림을 받으려면 필수 | @BotFather에서 만든 봇의 토큰 |
| `TELEGRAM_CHAT_ID` | 알림을 받으려면 필수 | 알림을 받을 대화의 chat id |
| `SERPAPI_KEY` | 선택 | 호텔 가격 조회. 없으면 Google Hotels·아고다 검색 링크만 제공 |

- 토큰이 없으면 수집과 저장은 그대로 진행하고 발송만 생략합니다. 발송하지 못한 알림은 다음 실행에서 다시 발송합니다.
- GitHub Actions에서는 저장소의 Settings → Secrets and variables → Actions에 같은 이름으로 등록합니다.
- 봇 생성과 chat id 확인 절차는 위 "알림 방식"을 참고합니다.
- 로컬에 토큰을 환경 변수로 설정한 상태에서 `--dry-run` 없이 실행하면 실제 알림이 발송됩니다. 시험 실행에는 `--dry-run`을 사용합니다.

### 실행

```bash
# 전체 수집: 조회 -> 판정 -> 호텔 -> 알림 -> data/ 저장 (약 1시간 40분 ~ 2시간 20분)
uv run python -m collector.main

# 시험 실행: 텔레그램 발송과 data/ 저장을 하지 않고 결과만 출력
uv run python -m collector.main --dry-run --destinations KIX,CJU --max-queries 4

# 시험 실행 결과를 다른 폴더에 저장해 확인
uv run python -m collector.main --dry-run --limit 2 --max-requests 14 --out /tmp/flight-out
uv run python schemas/validate.py /tmp/flight-out
```

| 옵션 | 내용 |
|---|---|
| `--dry-run` | 텔레그램 발송, SerpApi 호출, `data/` 저장을 하지 않습니다. `--out`을 함께 주면 그 폴더에만 저장합니다 |
| `--destinations KIX,CJU` | 지정한 목적지만 조회합니다 |
| `--limit N` | 목적지 목록의 앞에서부터 N개만 조회합니다 |
| `--max-queries N` | 조회 건수 상한입니다(기준가 조회 포함). 초과분은 생략으로 기록합니다 |
| `--max-requests N` | HTTP 요청 수 상한입니다(재시도 포함) |
| `--out DIR` | 결과를 저장할 폴더입니다. `--dry-run`이 아니면 이전 상태도 이 폴더에서 읽습니다 |
| `--data DIR` | 이전 상태를 읽는 폴더입니다(기본 `data/`) |

- 종료 코드: 실행 결과가 `ok`·`partial`이면 0, `failed`이면 1입니다. `failed`이어도 `status.json`은 저장합니다.
- 요청 간격은 6~8초입니다. Google이 봇 확인 페이지를 응답하면 20초, 60초 후 다시 요청합니다. 재시도 후 실패가 연속 8건이면 남은 조회를 생략합니다.
- 실행 시간이 150분(`pacing.max_run_minutes`)을 넘으면 남은 조회를 생략하고 그때까지의 결과를 저장합니다. 조회하지 못한 일정은 이전 수집 값을 유지합니다.
- 가격을 1건도 얻지 못한 실행은 `failed`로 기록하고 이전 가격과 알림 상태를 유지합니다.
- 실행 결과가 3회 연속 `failed`이면 텔레그램으로 "수집 중단" 안내를 1회 발송하고, 이후 정상 수집되면 "수집 재개" 안내를 1회 발송합니다.

### 테스트

```bash
uv run pytest                              # 단위 테스트와 모의 수집 실행(네트워크 사용 없음)
uv run python schemas/validate.py data     # 수집 결과의 스키마·교차 규칙 검증
```

### 제한 사항

- Google Flights 조회는 비공식 방식입니다. 응답 구조가 바뀌거나 접속이 차단되면 수집이 중단될 수 있습니다. GitHub Actions 서버에서의 차단 여부는 확인되지 않았습니다.
- 목적지 목록(`config/destinations.yaml`)에 없는 도시는 조회하지 않습니다.
- 3~7박 일정만 조회합니다(출발 12/17~12/30, 귀국 1/3 이전).
- 매 실행에서 모든 목적지는 대표 일정 6개만 조회하고, 그 가격이 낮은 6개 목적지와 특가 알림이 있는 목적지만 전체 일정(64개)을 조회합니다. 대표 일정 밖에서만 저렴한 목적지는 발견하지 못할 수 있습니다.
- 이메일 알림은 지원하지 않습니다.
- 호텔 검색 링크(Google Hotels, 아고다)에 지역과 날짜가 적용되는지는 확인되지 않았습니다. 첫 알림을 받으면 두 링크를 1회 열어 확인하십시오.

## 수집 주기 (2026-11-19 변경)

- GitHub Actions 에서는 Google 이 요청의 50~70%에 오류 응답을 반환하고, 한 실행 안에서 조회가 길어질수록 비율이 높아지는 것을 확인했습니다. 그래서 하루 3회 전체 수집 대신 **30분마다 순환 수집**으로 변경했습니다.
- 매 실행은 가장 오래 조회하지 않은 목적지 6곳의 대표 일정 6개(약 36건)를 조회합니다. 목적지 60곳 기준으로 각 목적지는 하루 약 4~5회 조회됩니다. 특가 알림이 있는 목적지는 매 실행에 포함합니다.
- 전체 일정(64개) 확대 조회는 대표 일정 가격이 Google 평소 가격 하한보다 낮은 목적지와 특가 알림이 있는 목적지에만 적용합니다.
- 조회 순서는 `data/rotation.json`(목적지별 마지막 조회 시도 시각)으로 관리합니다.
- "수집 중단" 안내는 8회 연속 실패(약 4시간) 시 발송합니다.
- 로컬에서 같은 방식으로 실행: `uv run python -m collector.main --rotate 6 --max-minutes 22 --baseline-max 8`
