import express from "express";
import { chromium } from "playwright";

const app = express();
const PORT = process.env.PORT || 8080;

app.get("/fetch", async (req, res) => {
  const target = req.query.url;
  if (!target) return res.status(400).send("Missing ?url=");

  let browser;
  try {
    browser = await chromium.launch({
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
      headless: true
    });
    const page = await browser.newPage({
      userAgent:
        req.headers["user-agent"] ||
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    });

    await page.setExtraHTTPHeaders({
      "Accept-Language": req.headers["accept-language"] || "en-US,en;q=0.9",
      Referer: req.headers["referer"] || "https://yavka.net/search"
    });

    const cookieHeader = req.headers["cookie"];
    if (cookieHeader) {
      const url = new URL(target);
      const domain = url.hostname.startsWith(".") ? url.hostname : `.${url.hostname}`;
      const cookiesPayload = [];
      cookieHeader.split(/;\s*/).forEach((entry) => {
        const [name, ...rest] = entry.split("=");
        if (!name || !rest.length) return;
        const value = rest.join("=");
        const payload = {
          name,
          value,
          domain,
          path: "/",
          secure: true,
        };
        if (name.toLowerCase().startsWith("cf_")) {
          payload.httpOnly = true;
          payload.secure = true;
        }
        cookiesPayload.push(payload);
      });
      if (cookiesPayload.length) {
        await page.context().addCookies(cookiesPayload);
      }
    }

    let response;
    try {
      response = await page.goto(target, {
        waitUntil: "domcontentloaded",
        timeout: 45000
      });
      if (page.url().includes("__cf_chl")) {
        await page.waitForTimeout(4000);
      }
      await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    } catch (err) {
      console.warn("Playwright goto warning:", err);
    }

    const body = response ? await response.body() : Buffer.from(await page.content(), "utf-8");
    const contentType =
      (response && response.headers()["content-type"]) || "text/html; charset=utf-8";

    res.set("Content-Type", contentType);
    res.send(body);
    await page.close();
  } catch (err) {
    console.error("Playwright fetch error", err);
    res.status(500).send("fetch error");
  } finally {
    if (browser) await browser.close();
  }
});

app.listen(PORT, () =>
  console.log(`✅ Playwright proxy running on port ${PORT}`)
);
