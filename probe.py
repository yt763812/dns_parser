"""DNS Belarus catalogue diagnostic (Railway / Playwright).

Reads five categories, up to two pages each by default. No database writes.
Environment: MAX_PAGES=2, MAX_ITEMS_LOG=15, PAGE_DELAY_MS=1200.
"""
import asyncio
import json
import os
import re
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.async_api import async_playwright

BASE = 'https://dns-shop.by'
MAX_PAGES = max(1, min(int(os.getenv('MAX_PAGES', '2')), 100))
MAX_ITEMS_LOG = max(0, int(os.getenv('MAX_ITEMS_LOG', '15')))
DELAY = max(500, int(os.getenv('PAGE_DELAY_MS', '1200')))
CATEGORIES = {
    'smartphones': ('смартфоны', ['смартфон']),
    'tablets': ('планшеты', ['планшет']),
    'laptops': ('ноутбуки', ['ноутбук']),
    'smartwatches': ('смарт-часы', ['смарт-час', 'умные часы', 'умные-часы']),
    'headphones': ('наушники', ['наушник']),
}
PRICE_RE = re.compile(r'(\d[\d\s\u00a0\u202f]*[.,]\d{2})\s*BYN', re.I)

# Extract from a product anchor and its closest likely listing card.
EXTRACT_JS = r'''() => {
  const anchors = [...document.querySelectorAll('a[href*="/product/"]')];
  const output = [];
  const seen = new Set();
  for (const a of anchors) {
    const href = a.href.split('?')[0].split('#')[0];
    if (!/^https:\/\/dns-shop\.by\/ru\/product\//.test(href) || seen.has(href)) continue;
    let el = a;
    let card = null;
    for (let i = 0; i < 7 && el; i++, el = el.parentElement) {
      const t = (el.innerText || '').trim();
      if (t.length > 20 && t.length < 2500 && /\d[\d\s.,]*\s*BYN/i.test(t)) {
        card = el;
        break;
      }
    }
    if (!card) continue;
    const raw = (card.innerText || '').replace(/\s+/g, ' ').trim();
    const name = (a.innerText || a.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
    if (!name || name.length < 8) continue;
    const prices = [...raw.matchAll(/(\d[\d\s\u00a0\u202f]*[.,]\d{2})\s*BYN/gi)].map(m => m[1]);
    if (!prices.length) continue;
    seen.add(href);
    output.push({name, url: href, price_candidates: prices, card_sample: raw.slice(0, 230)});
  }
  return output;
}'''

async def discover_categories(page):
    """Find category URLs from the site's own navigation; never guess slugs."""
    await page.goto(BASE + '/ru/', wait_until='domcontentloaded', timeout=45000)
    await page.wait_for_timeout(1600)
    # Category menu may require a click.
    for selector in ['text=Каталог', 'a:has-text("Каталог")', 'button:has-text("Каталог")']:
        try:
            loc = page.locator(selector).first
            if await loc.count():
                await loc.click(timeout=2000)
                await page.wait_for_timeout(900)
                break
        except Exception:
            continue
    links = await page.locator('a[href]').evaluate_all('''els => els.map(a => ({text:(a.innerText||a.title||'').trim(), href:a.href}))''')
    found = {}
    for key, (label, tokens) in CATEGORIES.items():
        matches = []
        for link in links:
            text = ' '.join(link['text'].lower().split())
            href = link['href']
            if not href.startswith(BASE + '/ru/catalog/'):
                continue
            if any(token in text for token in tokens):
                # Prefer exact category text; reject obvious broad category labels.
                score = (100 if text == label else 0) - len(text)
                matches.append((score, href, text))
        if matches:
            matches.sort(reverse=True)
            found[key] = matches[0][1]
            print(f'CATEGORY_DISCOVERED {key}: {found[key]} (label={matches[0][2]!r})', flush=True)
        else:
            print(f'CATEGORY_NOT_FOUND {key}: navigation did not expose a matching catalogue link', flush=True)
    return found

async def next_page_url(page, visited):
    """Only follow an explicit next-page control, not an assumed ?p= scheme."""
    candidates = await page.locator('a[href]').evaluate_all('''els => els.map(a => ({
      href:a.href, text:(a.innerText||'').trim(), aria:(a.getAttribute('aria-label')||''),
      rel:(a.getAttribute('rel')||''), cls:(typeof a.className==='string'?a.className:'')
    }))''')
    for a in candidates:
        signals = ' '.join((a['text'], a['aria'], a['rel'], a['cls'])).lower()
        if not (a['rel'].lower() == 'next' or re.search(r'следующ|впер[её]д|next|pagination.*next|page.*next', signals)):
            continue
        url = a['href'].split('#')[0]
        if url.startswith(BASE + '/ru/catalog/') and url not in visited:
            return url
    return None

def price_value(raw):
    # Accept a decimal price only; don't confuse crossed-out price with sale price.
    return float(raw.replace(' ', '').replace('\u00a0', '').replace('\u202f', '').replace(',', '.'))

async def main():
    print(f'DNS CATALOG DIAGNOSTIC | MAX_PAGES={MAX_PAGES} | NO DATABASE', flush=True)
    all_products = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(locale='ru-RU', viewport={'width': 1440, 'height': 900})
        page = await context.new_page()
        try:
            categories = await discover_categories(page)
            for key, (label, _) in CATEGORIES.items():
                print(f'\n=== {label.upper()} ===', flush=True)
                start_url = categories.get(key)
                if not start_url:
                    print('STATUS: SKIPPED (category URL not discovered)', flush=True)
                    continue
                visited = set()
                current = start_url
                count = 0
                while current and count < MAX_PAGES:
                    if current in visited:
                        break
                    visited.add(current)
                    try:
                        response = await page.goto(current, wait_until='domcontentloaded', timeout=45000)
                        await page.wait_for_timeout(DELAY)
                        status = response.status if response else 'unknown'
                        if status != 200:
                            print(f'PAGE_ERROR status={status} url={current}', flush=True)
                            break
                        items = await page.evaluate(EXTRACT_JS)
                        print(f'PAGE {count + 1}: http={status} extracted={len(items)} url={page.url}', flush=True)
                        if not items:
                            print('WARNING: No priced product cards found; inspect markup / possible block.', flush=True)
                            break
                        for item in items:
                            if item['url'] in all_products:
                                continue
                            try:
                                # Usually only current price has BYN suffix; when multiple, keep last and flag.
                                prices = [price_value(x) for x in item['price_candidates']]
                                price = prices[-1]
                            except ValueError:
                                continue
                            all_products[item['url']] = {'category': key, 'name': item['name'], 'price': price,
                                                         'currency': 'BYN', 'source': 'dns-shop.by', 'url': item['url']}
                            if sum(1 for v in all_products.values() if v['category'] == key) <= MAX_ITEMS_LOG:
                                print('ITEM ' + json.dumps(all_products[item['url']], ensure_ascii=False), flush=True)
                            if len(prices) > 1:
                                print(f'PRICE_REVIEW multiple candidates={prices} url={item["url"]}', flush=True)
                        count += 1
                        next_url = await next_page_url(page, visited)
                        if count < MAX_PAGES and not next_url:
                            print('PAGINATION_NOT_FOUND: no explicit next-page link; cannot confirm catalogue completeness.', flush=True)
                        current = next_url
                    except Exception as exc:
                        print(f'PAGE_EXCEPTION {type(exc).__name__}: {str(exc)[:300]}', flush=True)
                        break
                n = sum(v['category'] == key for v in all_products.values())
                print(f'CATEGORY_SUMMARY category={key} pages={count} unique_items={n}', flush=True)
            print('\n=== TOTAL ===', flush=True)
            print(f'UNIQUE_ITEMS={len(all_products)}', flush=True)
            print('RESULT: DIAGNOSTIC_FINISHED (not a completeness guarantee)', flush=True)
        except Exception as exc:
            print(f'FATAL_ERROR {type(exc).__name__}: {str(exc)[:500]}', flush=True)
            raise
        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
