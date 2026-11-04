(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const clean = (v) => String(v == null ? '' : v).replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').replace(/\s+/g, ' ').trim();
  const t0 = Date.now();
  let links = [];
  for (;;) {
    links = [...document.querySelectorAll('a[href*="detail.1688.com/offer/"]')];
    if (links.length > 5) break;
    if (Date.now() - t0 > 20000) break;
    await sleep(700);
  }
  await sleep(1000);
  const txt = document.body ? document.body.innerText : '';
  const state = {
    href: location.href, title: document.title, bodyLen: txt.length,
    offerLinks: links.length, isLoginPage: /login\.1688\.com/.test(location.href),
    hasLoginPrompt: txt.indexOf('立即登录') >= 0,
    sortControlText: (txt.match(/(综合|销量|价格|成交额|回头率|最新的排序方式)/g) || []).slice(0, 12)
  };
  const seen = new Set(); const items = [];
  const nums = (s) => { const m = s.match(/([\d.]+)\s*(万|億|亿)?/); if (!m) return null; const mult = { '万': 1e4, '亿': 1e8, '億': 1e8 }[m[2] || ''] || 1; return Math.round(Number(m[1]) * mult); };
  for (const a of links) {
    let id = null;
    try { const m = a.href.match(/offer\/(\d+)\.html/); id = m ? m[1] : null; } catch (e) {}
    if (!id || seen.has(id)) continue; seen.add(id);
    // 优先用 anchor 自身文本（1688 卡片把标题/价格/销量/标签都放在 <a> 里）；
    // 仅当 anchor 文本里没有价格时，才向上找"含 ¥ 且长度 < 600"的祖先容器
    let aTxt = clean(a.innerText || '');
    let card = a, cardTxt = '';
    for (let i = 0; i < 6 && card.parentElement; i++) {
      card = card.parentElement;
      const t = clean(card.innerText || '');
      if (t.length > 30 && t.length < 600) { cardTxt = t; break; }
    }
    let ct = aTxt.indexOf('¥') >= 0 || aTxt.indexOf('￥') >= 0 ? aTxt : (cardTxt || aTxt);
    const norm = ct.replace(/\s*\.\s*/g, '.').replace(/\s+/g, ' ');
    const priceM = norm.match(/¥\s*([\d.]+)(?:\s*[-~]\s*([\d.]+))?/);
    const soldM = norm.match(/(?:全网)?([\d.]+(?:万|亿)?)\+?\s*(件|个|只|套|条|盒|包)/);
    const repM = norm.match(/回头率\s*(\d+)\s*%/);
    const compM = norm.match(/([\u4e00-\u9fa5A-Za-z0-9()（）]{4,30}(?:有限公司|经营部|电子厂|商行|科技|厂|店铺))/);
    const badges = ['退货包运费', '先采后付', '官方物流', '7天无理由', '诚企认证', '实力商家', '好评率100%的口碑商品', '热卖榜', '月浏览', '厂货通'].filter(b => norm.indexOf(b) >= 0);
    const titleRaw = norm.split('¥')[0];
    items.push({
      offerId: id, url: 'https://detail.1688.com/offer/' + id + '.html',
      title: titleRaw.slice(0, 80),
      priceText: priceM ? priceM[0] : '', priceMin: priceM ? Number(priceM[1]) : null, priceMax: priceM && priceM[2] ? Number(priceM[2]) : (priceM ? Number(priceM[1]) : null),
      soldText: soldM ? soldM[0] : '', soldCount: soldM ? nums(soldM[1]) : null,
      repeatRate: repM ? Number(repM[1]) : null, company: compM ? compM[1] : '', badges,
      cardText: ct.slice(0, 200)
    });
  }
  const prices = items.map(i => i.priceMin).filter(v => typeof v === 'number' && v > 0).sort((a, b) => a - b);
  return JSON.stringify({
    elapsedMs: Date.now() - t0, state, uniqItems: items.length,
    priceStats: { n: prices.length, min: prices[0] ?? null, median: prices.length ? prices[Math.floor(prices.length / 2)] : null, max: prices[prices.length - 1] ?? null },
    invalidPriceCount: items.filter(i => !(i.priceMin > 0)).length,
    items
  });
})()
