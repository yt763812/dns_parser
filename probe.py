import asyncio
from urllib.parse import quote_plus
from playwright.async_api import async_playwright

QUERY = "iphone 16"
URL = "https://dns-shop.by/ru/search/?q=" + quote_plus(QUERY)

async def main():
    print("DNS browser diagnostic; no database access", flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(locale="ru-RU", viewport={"width": 1280, "height": 800})
        try:
            response = await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            print("Initial HTTP:", response.status if response else "no response")
            for seconds in (0, 3, 8, 15):
                if seconds:
                    await page.wait_for_timeout((seconds - previous) * 1000)
                previous = seconds
                title = await page.title()
                links = await page.locator('a[href*="/product/"]').count()
                text = (await page.locator("body").inner_text(timeout=5000))[:160].replace("\n", " ")
                print(f"After {seconds}s: title={title!r}, product_links={links}, body_start={text!r}", flush=True)
            print("Final URL:", page.url)
            print("Result:", "PRODUCT_LINKS_FOUND" if await page.locator('a[href*="/product/"]').count() else "NO_PRODUCT_LINKS")
        except Exception as exc:
            print("TEST ERROR:", type(exc).__name__, str(exc)[:400])
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
