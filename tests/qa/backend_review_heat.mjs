// 백엔드 검토용: 목적지 상세의 히트맵 문구와 선택 칸 정보를 출력한다.
// 사용: node tests/qa/backend_review_heat.mjs <기준 URL>
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(fileURLToPath(new URL("../../web/package.json", import.meta.url)));
const { chromium } = require("playwright");
const base = process.argv[2];
const cases = [["s5", "LHR"], ["s5", "CJU"], ["s6", "KIX"], ["s2", "CJU"], ["s2", "LHR"], ["s3", "KIX"], ["s3", "NRT"], ["s3", "HND"]];
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "ko-KR" })).newPage();
for (const [s, code] of cases) {
  await page.goto("about:blank");
  await page.goto(`${base}/${s}/index.html#dest=${code}`, { waitUntil: "load" });
  await page.waitForSelector(".heat-block");
  const g = async (sel) => (await page.locator(sel).first().innerText().catch(() => "(없음)")).replace(/\s+/g, " ");
  console.log(`${s} ${code} | aside: ${await g(".heat-block .sub-aside")} | stale: ${await g(".heat-stale")} | summary: ${await g(".detail-summary")} | 가격 칸 ${await page.locator("button.heat-cell").count()}개 | combo: ${(await g(".combo-detail")).slice(0, 160)}`);
}
await browser.close();
