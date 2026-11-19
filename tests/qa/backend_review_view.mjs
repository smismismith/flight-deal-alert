// 백엔드 검토용: backend_review_gen.py 가 만든 데이터를 빌드 결과에 넣어 화면 문구와 오류를 확인한다.
// 사용: node tests/qa/backend_review_view.mjs <기준 URL> <스크린샷 폴더>
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const require = createRequire(fileURLToPath(new URL("../../web/package.json", import.meta.url)));
const { chromium } = require("playwright");
const [base, shotDir] = process.argv.slice(2);
mkdirSync(shotDir, { recursive: true });

const plan = {
  s1: ["JFK", "CJU"],
  s2: ["CJU", "LHR"],
  s3: ["KIX", "NRT", "FUK", "CTS", "HND"],
  s4: ["DAD"],
  s5: ["CJU", "LHR"],
  s6: ["KIX"],
  s7: [],
};
const browser = await chromium.launch();
const text = async (page, sel) => (await page.locator(sel).first().innerText().catch(() => "(없음)")).replace(/\s+/g, " ").slice(0, 900);

for (const [s, dests] of Object.entries(plan)) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "ko-KR", timezoneId: "America/Los_Angeles" });
  const page = await ctx.newPage();
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push("console: " + m.text()));
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  await page.goto(`${base}/${s}/index.html`, { waitUntil: "networkidle" });
  console.log(`\n===== ${s} =====`);
  console.log("header:", await text(page, "header.app-header"));
  console.log("notices:", await text(page, ".notices"));
  console.log("load-error:", await text(page, ".load-error"));
  console.log("deals:", await text(page, ".section-deals"));
  console.log("table(앞부분):", (await text(page, ".section-table")).slice(0, 500));
  const btn = page.locator("button.status-button");
  if (await btn.count()) {
    await btn.click();
    console.log("status-panel:", (await text(page, ".status-panel")).slice(0, 1200));
  }
  await page.screenshot({ path: `${shotDir}/${s}-390.png`, fullPage: true });
  for (const code of dests) {
    await page.goto(`${base}/${s}/index.html#dest=${code}`, { waitUntil: "networkidle" });
    await page.reload({ waitUntil: "networkidle" });
    console.log(`row ${code}:`, await text(page, `#dest-row-${code}`));
    const detail = await text(page, ".section-detail");
    console.log(`detail ${code}:`, detail.replace(/(\d+\/\d+\([^)]+\)\s*)+/g, " ").slice(0, 700));
    console.log(`chart ${code}:`, await text(page, ".chart-block"));
    await page.locator(".section-detail").screenshot({ path: `${shotDir}/${s}-${code}-detail.png` }).catch(() => {});
  }
  const sw = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  console.log("scroll:", sw.join("/"), "problems:", JSON.stringify(problems));
  await ctx.close();
}
await browser.close();
