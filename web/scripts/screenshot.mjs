// 빌드 결과(dist)를 미리보기 서버로 열고 샘플 데이터 화면을 캡처한다.
// 사용: npm run build && npm run screenshots
// 외부 접속 없음(로컬 미리보기 서버만 사용).
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { preview } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const outDir = fileURLToPath(new URL("../screenshots/", import.meta.url));
mkdirSync(outDir, { recursive: true });

const server = await preview({ root, preview: { port: 4179, strictPort: false, host: "127.0.0.1" } });
const base = server.resolvedUrls.local[0];
const browser = await chromium.launch();
const problems = [];

async function open(context, path, routes) {
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`[console] ${path}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`[pageerror] ${path}: ${e.message}`));
  if (routes) await routes(page);
  await page.goto(base + path, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

async function checkNoHorizontalScroll(page, label) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (scrollWidth !== clientWidth) problems.push(`[가로 스크롤] ${label}: ${scrollWidth} != ${clientWidth}`);
  console.log(`${label}: scrollWidth=${scrollWidth} clientWidth=${clientWidth}`);
}

const shots = [
  { name: "mobile-390", width: 390, height: 844, scheme: "light" },
  { name: "desktop-1280", width: 1280, height: 900, scheme: "light" },
  { name: "mobile-390-dark", width: 390, height: 844, scheme: "dark" },
  { name: "desktop-1280-dark", width: 1280, height: 900, scheme: "dark" },
  { name: "mobile-360", width: 360, height: 740, scheme: "light" },
  { name: "tablet-768", width: 768, height: 1024, scheme: "light" },
];

for (const shot of shots) {
  const context = await browser.newContext({
    viewport: { width: shot.width, height: shot.height },
    colorScheme: shot.scheme,
    deviceScaleFactor: 2,
    locale: "ko-KR",
    timezoneId: "America/Los_Angeles", // 기기 시간대와 관계없이 KST 로 표시되는지 확인
  });
  const page = await open(context, "?sample=1");
  await checkNoHorizontalScroll(page, shot.name);
  await page.screenshot({ path: `${outDir}${shot.name}.png`, fullPage: true });
  if (shot.name === "mobile-390") {
    await page.screenshot({ path: `${outDir}mobile-390-first-view.png` });
    await page.locator(".status-button").click();
    await page.screenshot({ path: `${outDir}mobile-390-status-open.png` });
    await page.locator(".status-button").click();
    await page.locator(".section-detail").screenshot({ path: `${outDir}mobile-390-detail.png` });
  }
  if (shot.name === "desktop-1280") {
    await page.locator(".chart-svg").hover({ position: { x: 300, y: 120 } });
    await page.locator(".section-detail").screenshot({ path: `${outDir}desktop-1280-detail-hover.png` });
  }
  await context.close();
}

// 목적지별 상세(히트맵 6칸, Google 정보 없음, 이전 수집 값)
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  for (const code of ["BKK", "SYD", "CDG", "CJU", "KIX"]) {
    const page = await open(context, `?sample=1#dest=${code}`);
    await page.locator(".section-detail").screenshot({ path: `${outDir}detail-${code}-390.png` });
    await checkNoHorizontalScroll(page, `detail-${code}`);
    await page.close();
  }
  await context.close();
}

// 운영 빌드에서 data/ 가 없으면 오류 화면(샘플로 대체하지 않음)
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const before = problems.length;
  const page = await open(context, "");
  const text = await page.locator("main").innerText();
  if (!text.includes("데이터를 읽지 못했습니다")) problems.push("[오류 화면] 운영 빌드에서 오류 문구가 없음");
  if (await page.locator(".chip-sample").count()) problems.push("[오류 화면] 샘플로 대체됨");
  await page.screenshot({ path: `${outDir}error-no-data-390.png`, fullPage: true });
  problems.splice(before); // 404 응답으로 인한 콘솔 메시지는 이 화면의 정상 동작이다
  await context.close();
}

// 변형 데이터: 수집 중단 + 특가 없음 + alerts 실패
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const patch = (name, fn) => async (page) => {
    await page.route(`**/sample-data/${name}`, async (route) => {
      const response = await route.fetch();
      const body = fn(await response.json());
      await route.fulfill({ response, json: body });
    });
  };
  let page = await open(context, "?sample=1", async (p) => {
    await patch("status.json", (s) => ({ ...s, state: "stopped", consecutive_failures: 3 }))(p);
    await patch("alerts.json", (a) => ({
      ...a,
      alerts: a.alerts.map((x) =>
        x.status === "active" ? { ...x, status: "ended", ended_at: x.current_checked_at, current_fare: null } : x,
      ),
    }))(p);
  });
  await checkNoHorizontalScroll(page, "variant-stopped-empty");
  await page.screenshot({ path: `${outDir}variant-stopped-no-deals-390.png` });
  await page.close();

  const before = problems.length;
  page = await open(context, "?sample=1", async (p) => {
    await p.route("**/sample-data/alerts.json", (route) => route.fulfill({ status: 404, body: "" }));
    await p.route("**/sample-data/history/*.json", (route) => route.fulfill({ status: 404, body: "" }));
  });
  await page.screenshot({ path: `${outDir}variant-alerts-history-failed-390.png`, fullPage: true });
  problems.splice(before);
  await context.close();
}

await browser.close();
await new Promise((resolve) => server.httpServer.close(resolve));

if (problems.length > 0) {
  console.error("문제:\n" + problems.join("\n"));
  process.exit(1);
}
console.log("문제 없음. 저장 위치:", outDir);
