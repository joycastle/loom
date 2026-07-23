import puppeteer from "puppeteer";

const URL = process.env.DIAG_URL || "http://localhost:5174/";
const browser = await puppeteer.launch({ headless: "new" });
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push("CONSOLE: " + m.text()); });
page.on("pageerror", (e) => errors.push("PAGEERROR: " + (e.stack || e.message).split("\n").slice(0,3).join(" | ")));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

await page.goto(URL, { waitUntil: "networkidle0", timeout: 20000 });

// 1) trigger the proposal flow
await page.evaluate(() => {
  const btn = Array.from(document.querySelectorAll(".loom-suggestions button")).find(b => /收编/.test(b.textContent||""));
  btn?.click();
});
await wait(1500);
const afterSend = await page.evaluate(() => ({
  hasCard: !!document.querySelector(".loom-card"),
  cardText: (document.querySelector(".loom-card")?.textContent || "").replace(/\s+/g," ").slice(0,120),
  rootEmpty: (document.getElementById("root")?.innerHTML || "").length < 20,
}));
console.log("after send:", JSON.stringify(afterSend));

// 2) click 确认执行
await page.evaluate(() => {
  const btn = Array.from(document.querySelectorAll(".loom-card button")).find(b => /确认执行/.test(b.textContent||""));
  btn?.click();
});
await wait(1200);
const afterConfirm = await page.evaluate(() => ({
  cardStatus: document.querySelector(".loom-card")?.getAttribute("data-status"),
  cardText: (document.querySelector(".loom-card")?.textContent || "").replace(/\s+/g," ").slice(0,160),
  rootEmpty: (document.getElementById("root")?.innerHTML || "").length < 20,
}));
console.log("after confirm:", JSON.stringify(afterConfirm));
console.log("--- errors ---");
console.log(errors.join("\n") || "(none)");
await browser.close();
