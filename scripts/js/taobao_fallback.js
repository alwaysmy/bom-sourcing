(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const clean = (v) => String(v == null ? '' : v).replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').replace(/\s+/g, ' ').trim();
  const t0 = Date.now();
  let n = 0;
  for (;;) {
    n = document.querySelectorAll('[class*="doubleCardWrapper"], [data-nid], [data-spm-act-id][class*="Card"], #mainsrp-itemlist .item').length;
    if (n > 4) break;
    if (Date.now() - t0 > 15000) break;
    await sleep(500);
  }
  await sleep(600);
  const p = window.__last_search_params || {};
  const cards = [...document.querySelectorAll('[class*="doubleCardWrapper"], [data-nid], [data-spm-act-id][class*="Card"], #mainsrp-itemlist .item')];
  const seen = new Set();
  const items = [];
  for (const card of cards) {
    const links = card.matches('a[href]') ? [card] : [...card.querySelectorAll('a[href]')];
    let id = null, href = null;
    for (const a of links) {
      try { const u = new URL(a.href, location.href); const v = u.searchParams.get('id'); if (v && /^\d{5,32}$/.test(v)) { id = v; href = u.href; break; } } catch (e) {}
    }
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const txt = (sel) => { const el = card.querySelector(sel); return el ? clean(el.textContent) : ''; };
    const pr = clean((card.querySelector('[class*="innerPriceWrapper--"]') || card.querySelector('[class*="priceInt--"]') || card.querySelector('.price') || {}).textContent || '');
    const sv = clean((card.querySelector('[class*="realSales--"]') || card.querySelector('.deal-cnt') || card.querySelector('.sale-num') || {}).textContent || '');
    const shop = clean((card.querySelector('[class*="shopNameText--"]') || card.querySelector('.shopname') || card.querySelector('.shop a') || {}).textContent || '');
    const loc = clean((card.querySelector('[class*="procity--"]') || card.querySelector('.location') || {}).textContent || '');
    const badges = [...card.querySelectorAll('[class*="shopTagWrapper--"]')].map(e => clean(e.textContent)).filter(Boolean);
    const priceNum = (() => { const m = pr.replace(/,/g, '').match(/\d+(?:\.\d+)?/); return m ? Number(m[0]) : null; })();
    const salesNum = (() => { const s = sv.replace(/,/g, ''); const m = s.match(/([\d.]+)\s*(万|萬|亿|億|k|m|b)?/i); if (!m) return null; const mult = { '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8, k: 1e3, m: 1e6, b: 1e9 }[(m[2] || '').toLowerCase()] || 1; return Math.round(Number(m[1]) * mult); })();
    items.push({
      itemId: id, title: txt('[class*="title--"]').slice(0, 60), priceText: pr, priceNum, salesText: sv, salesNum,
      shop, badges, loc, sponsored: /m?click\.simba\.taobao\.com/.test(href || ''),
      url: 'https://item.taobao.com/item.htm?id=' + id,
      abs: (card.querySelector('[class*="abstractInnerWrapper--"]') ? clean(card.querySelector('[class*="abstractInnerWrapper--"]').textContent) : '').slice(0, 120)
    });
  }
  const sortTabs = [...document.querySelectorAll('a, li, span')].filter(e => /^(综合|销量|价格)$/.test(clean(e.textContent)) && e.textContent.trim().length <= 3).slice(0, 12).map(e => ({ tag: e.tagName, cls: e.className, href: e.getAttribute('href') || null, text: clean(e.textContent), parentCls: e.parentElement ? e.parentElement.className : null }));
  return JSON.stringify({
    href: location.href,
    params: { sort: p.sort || null, n: p.n || null, page: p.page || null, totalResults: p.totalResults || null, totalPage: p.totalPage || null, q: p.q || null },
    cardCount: n, uniqItems: items.length,
    sortTabs,
    activeTabGuess: [...document.querySelectorAll('[class*="active"],[class*="Selected"]')].map(e => clean(e.textContent)).filter(t => /^(综合|销量|价格)$/.test(t)).slice(0, 5),
    items
  });
})()
