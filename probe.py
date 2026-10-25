import asyncio
import json
import os
import re
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

QUERY = os.getenv("SEARCH_QUERY", "iphone 16")
LIMIT = int(os.getenv("RESULT_LIMIT", "10"))
URL = "https://dns-shop.by/ru/search/?q=" + quote_plus(QUERY)

EXTRACT_JS = r"""() => {
  const links = [...document.querySelectorAll('a[href*="/product/"]')];
  const seen = new Set();
  const results = [];
  const pricePattern = /(?:\d[\d\s\u00a0\u202f]{0,12}[,.]\d{2}|\d[\d\s\u00a0\u202f]{1,12})\s*(?:р\.|руб\.?|BYN|Br|₽)/i;
  for (const link of links) {
    const url = new URL(link.getAttribute('href'), location.href).href.split('#')[0];
    if (seen.has(url)) continue;
    seen.add(url);
    const img = link.querySelector('img');
    let name = (link.innerText || link.getAttribute('title') || img?.alt || '').trim().replace(/\s+/g, ' ');
    let card = link;
    for (let i = 0; i < 5 && card.parentElement; i++) {
      card = card.parentElement;
      const text = (card.innerText || '').trim();
      if (text.length > 35 && text.length < 1500 && (pricePattern.test(text) || card.querySelector('[class*="price"]'))) break;
    }
    const text = (card.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 650);
    if (!name || name.length < 8) {
      const candidate = card.querySelector('[class*="title"], [class*="name"], h2, h3');
      name = (candidate?.innerText || img?.alt || '').trim().replace(/\s+/g, ' ');
    }
    const priceEl = card.querySelector('[class*="price"]');
    const priceText = (priceEl?.innerText || '').replace(/\s+/g, ' ').trim();
    const match = (priceText || text).match(pricePattern);
    results.push({name: name.slice(0, 200), url, price: match?.[0] || null, price_text: priceText.slice(0, 150), snippet: text.slice(0, 250)});
  }
  return results;
}"""


def matches_query(name: str, query: str) -> bool:
    tokens = re.findall(r"[\w]+", query.casefold())
    normalized = name.casefold()
    return bool(name) and all(token in normalized for token in tokens)


async def main():
    print(f"DNS product diagnostic | query={QUERY!r} | no database access", flush=True)
    print(f"Search URL: {URL}", flush=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(locale="ru-RU", viewport={"width": 1365, "height": 900})
        try:
            response = await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            print(f"HTTP status: {response.status if response else 'no response'}", flush=True)
            try:
                await page.locator('a[href*="/product/"]').first.wait_for(timeout=20000)
            except Exception:
                print("No product links appeared within 20 seconds", flush=True)
            await page.wait_for_timeout(2500)
            print(f"Page title: {await page.title()}", flush=True)
            print(f"Final URL: {page.url}", flush=True)
            products = await page.evaluate(EXTRACT_JS)
            print(f"Unique product URLs: {len(products)}", flush=True)
            matched = [p for p in products if matches_query(p['name'], QUERY)]
            print(f"Name matches: {len(matched)}", flush=True)
            selected = matched[:LIMIT] if matched else products[:LIMIT]
            if not matched:
                print("WARNING: No product names matched all search words; showing diagnostic candidates", flush=True)
            for i, item in enumerate(selected, 1):
                print(f"\nPRODUCT {i}", flush=True)
                print(f"  Name: {item['name'] or '(not extracted)'}", flush=True)
                print(f"  Price candidate: {item['price'] or '(not found)'}", flush=True)
                print(f"  URL: {item['url']}", flush=True)
                print(f"  Card text: {item['snippet']}", flush=True)
            print("\nRESULT: " + ("MATCHED_PRODUCTS_FOUND" if matched else "NEEDS_SELECTOR_REVIEW"), flush=True)
            print("NOTE: Price candidates are unverified until compared with the product page.", flush=True)
        except Exception as exc:
            print(f"TEST ERROR: {type(exc).__name__}: {str(exc)[:600]}", flush=True)
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
