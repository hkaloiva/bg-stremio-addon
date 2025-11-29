import express from "express";
import puppeteer from "puppeteer-extra";
import StealthPlugin from "puppeteer-extra-plugin-stealth";

puppeteer.use(StealthPlugin());

const app = express();
const PORT = process.env.PORT || 8080;

app.get("/fetch", async (req, res) => {
  const target = req.query.url;
  if (!target) return res.status(400).send("Missing ?url=");

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox"]
    });

    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    );
    await page.setViewport({ width: 1366, height: 768 });

    const response = await page.goto(target, {
      waitUntil: "networkidle2",
      timeout: 30000
    });

    const contentType = response.headers()["content-type"] || "text/html";
    const body = await page.content();

    res.set("Content-Type", contentType);
    res.send(body);
    await page.close();
  } catch (err) {
    console.error("❌ Fetch error:", err.message);
    res.status(500).send("fetch error");
  } finally {
    if (browser) await browser.close();
  }
});

app.listen(PORT, () =>
  console.log(`✅ Puppeteer proxy running on port ${PORT}`)
);
