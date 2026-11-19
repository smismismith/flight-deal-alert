// QA 브라우저 확인. 사용: NODE_PATH=web/node_modules node tests/qa/browser_check.cjs <기준 URL> <이름> [동작]
// 콘솔 오류, 가로 스크롤, 본문 텍스트를 출력하고 web/screenshots/review/ 에 화면을 저장한다. 외부 접속 없음.
const { chromium } = require("playwright");
const path = require("node:path");
const [base, name, action] = process.argv.slice(2);
const outDir = path.join(__dirname, "../../web/screenshots/review/");
(async () => {
  const browser = await chromium.launch();
  const problems = [];
  const external = [];
  for (const width of [375, 1280]) {
    const ctx = await browser.newContext({ viewport: { width, height: 850 }, locale: "ko-KR", timezoneId: "America/Los_Angeles" });
    const page = await ctx.newPage();
    page.on("console", (m) => { if (m.type() === "error") problems.push(`[console ${width}] ${m.text()}`); });
    page.on("pageerror", (e) => problems.push(`[pageerror ${width}] ${e.message}`));
    page.on("request", (r) => { if (!r.url().startsWith(base.split("?")[0].replace(/\/[^/]*$/, "/")) && !r.url().startsWith("data:")) external.push(r.url()); });
    await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (r) => r.abort());
    await page.goto(base, { waitUntil: "networkidle" });
    if (action) {
      for (const step of action.split(";;")) {
        const [kind, arg] = step.split("=>");
        if (kind === "click") await page.locator(arg).first().click();
        if (kind === "clicktext") await page.getByText(arg, { exact: false }).first().click();
        if (kind === "hash") await page.evaluate((h) => { location.hash = h; }, arg);
        await page.waitForTimeout(400);
      }
      await page.waitForLoadState("networkidle");
    }
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    if (m.sw !== m.cw) problems.push(`[가로 스크롤 ${width}] ${m.sw} != ${m.cw}`);
    await page.screenshot({ path: `${outDir}${name}-${width}.png`, fullPage: true });
    if (width === 375) {
      console.log("=== TEXT ===\n" + (await page.evaluate(() => document.body.innerText)));
      const links = await page.evaluate(() => [...document.querySelectorAll("a[href^=http]")].map((a) => [a.textContent.trim().slice(0, 30), a.target, a.rel, a.href.slice(0, 110)]));
      console.log("=== LINKS ===\n" + links.map((l) => l.join(" | ")).join("\n"));
    }
    await ctx.close();
  }
  console.log("=== EXTERNAL REQUESTS === " + JSON.stringify([...new Set(external)]));
  console.log("=== PROBLEMS === " + JSON.stringify(problems, null, 1));
  await browser.close();
})();
