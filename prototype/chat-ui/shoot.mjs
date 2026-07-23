import puppeteer from "puppeteer";

const URL = process.env.SHOT_URL || "http://localhost:5174/";
const scheme = process.env.SHOT_SCHEME || "light";
const out = process.env.SHOT_OUT || "/tmp/loom-shot";
const browser = await puppeteer.launch({ headless: "new" });
const page = await browser.newPage();
await page.setViewport({ width: 1120, height: 820, deviceScaleFactor: 2 });
await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

await page.goto(URL, { waitUntil: "networkidle0", timeout: 20000 });
await wait(400);
await page.screenshot({ path: `${out}-empty-${scheme}.png` });

await page.evaluate(() => {
  const b = Array.from(document.querySelectorAll(".loom-suggestions button")).find(x => /收编/.test(x.textContent||""));
  b?.click();
});
await wait(1400);
await page.screenshot({ path: `${out}-proposal-${scheme}.png` });
console.log("shots:", `${out}-empty-${scheme}.png`, `${out}-proposal-${scheme}.png`);
await browser.close();
