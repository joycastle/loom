import puppeteer from "puppeteer";

const served = process.env.E2E_URL;
const base = served.replace(/\/\?.*/, "");
const token = new URL(served).searchParams.get("token");
const b = await puppeteer.launch({ headless: "new" });
const p = await b.newPage();
const errs = [];
p.on("pageerror", (e) => errs.push(e.message));
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

await p.goto(served, { waitUntil: "networkidle0" });
await wait(600);
console.log("gate before login:", JSON.stringify(await p.evaluate(() => document.querySelector(".loom-gate")?.textContent || "(none)")));

const start = await p.evaluate(async (base, token) => {
  const r = await fetch(base + "/api/enterprise/v1/auth/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Loom-Token": token },
    body: JSON.stringify({ locale: "zh-CN", device_name: "e2e" }),
  });
  return r.json();
}, base, token);
console.log("auth/start ok:", start.ok, "| login_url:", (start.login_url || "").slice(0, 70));

if (start.login_url) {
  await p.goto(start.login_url, { waitUntil: "networkidle0" });
  const approved = await p.evaluate(() => {
    const f = document.querySelector("form[action*='approve']");
    if (f) { f.submit(); return "form"; }
    const btn = Array.from(document.querySelectorAll("button")).find((x) => /授权|approve/i.test(x.textContent || ""));
    if (btn) { btn.click(); return "button"; }
    return "none";
  });
  console.log("approve:", approved);
  await wait(600);
  // exchange the approval like the app's login() poll loop does
  await p.goto(served, { waitUntil: "networkidle0" });
  for (let i = 0; i < 20; i += 1) {
    const polled = await p.evaluate(async (base, token) => {
      const r = await fetch(base + "/api/enterprise/v1/auth/poll", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Loom-Token": token },
        body: "{}",
      });
      return r.json();
    }, base, token);
    if (polled.status === "connected") { console.log("poll → connected"); break; }
    if (polled.status !== "pending") { console.log("poll →", polled.status, polled.message || ""); break; }
    await wait(700);
  }
}

await p.goto(served, { waitUntil: "networkidle0" });
await wait(1500);
console.log("after login:", JSON.stringify(await p.evaluate(() => ({
  sub: document.querySelector(".loom-brand-sub")?.textContent || "",
  gate: document.querySelector(".loom-gate")?.textContent || "(none)",
}))));

// real send through the live gateway (deepseek)
await p.evaluate(() => {
  const t = document.querySelector(".loom-composer textarea");
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  setter.call(t, "你好，用一句话介绍你能帮我做什么。");
  t.dispatchEvent(new Event("input", { bubbles: true }));
});
await wait(200);
await p.evaluate(() => document.querySelector(".loom-send")?.click());
console.log("sent; waiting for live reply…");
for (let i = 0; i < 30; i += 1) {
  await wait(1000);
  const last = await p.evaluate(() => {
    const bubbles = document.querySelectorAll(".loom-message.assistant .loom-text");
    const card = document.querySelector(".loom-card");
    return { text: bubbles.length ? bubbles[bubbles.length - 1].textContent : "", card: !!card };
  });
  if (last.text && last.text !== "正在思考…" && last.text !== "正在整理信息…") {
    console.log("live reply:", JSON.stringify(last.text.slice(0, 100)), "| card:", last.card);
    break;
  }
}
console.log("errors:", errs.join(" | ") || "(none)");
await b.close();
