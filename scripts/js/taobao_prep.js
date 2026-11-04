// 淘宝搜索页准备：等卡片 / 识别登录墙与验证码 / 点击排序 tab（销量、价格）
// 复用方式：前面拼一行 `globalThis.__BOM_CFG = {...};`，再拼本文件，整体交给 evaluate。
// cfg: {minCards, waitMs, sortLabel, clicks, forceClick, clickWaitMs, afterClickMs}
(async () => {
  const cfg = globalThis.__BOM_CFG || {};
  const clean = (v) => String(v == null ? '' : v).replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').replace(/\s+/g, ' ').trim();
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const cards = () => document.querySelectorAll('[class*="doubleCardWrapper"], [data-nid], [data-spm-act-id][class*="Card"], #mainsrp-itemlist .item');
  // 卡片顺序指纹：用于判断「价格」tab 这类不改 URL/参数、只重排结果的点击是否生效
  const orderDigest = () => [...cards()].slice(0, 6).map(el => {
    const nid = (el.dataset && el.dataset.nid) || el.getAttribute('data-nid') || '';
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30);
    return nid + '|' + t;
  }).join('~');
  const tabs = () => [...document.querySelectorAll('.next-tabs-tab')];
  const activeLabel = () => tabs().filter(e => /(^|\s)active(\s|$)/.test(e.className)).map(e => clean(e.textContent)).join('|');
  const params = () => window.__last_search_params || {};
  const snap = () => ({
    sort: params().sort ?? null, page: params().page ?? null, n: params().n ?? null,
    totalResults: params().totalResults ?? null, totalPage: params().totalPage ?? null, q: params().q ?? null
  });

  const minCards = cfg.minCards || 5;
  const t0 = Date.now();
  let n = 0;
  for (;;) {
    n = cards().length;
    if (n >= minCards) break;
    if (Date.now() - t0 > (cfg.waitMs || 15000)) break;
    await sleep(500);
  }
  const body = document.body ? document.body.innerText : '';
  const out = {
    ok: n > 0,
    href: location.href,
    title: document.title,
    cardCount: n,
    activeLabel: activeLabel(),
    tabsSeen: tabs().map(e => clean(e.textContent)).slice(0, 10),
    params: snap(),
    bodyLen: body.length,
    loginWall: /亲，请登录|请登录后|扫码登录|密码登录/.test(body),
    verifyWall: /验证码|滑块|拖动滑块|安全验证|访问受限|访问过于频繁/.test(body),
    waitMs: Date.now() - t0,
    click: null
  };
  if (!out.ok) return JSON.stringify(out);

  const want = clean(cfg.sortLabel || '');
  const clicksWanted = Math.max(1, Math.min(3, cfg.clicks || 1));
  const need = want && (clicksWanted > 1 || cfg.forceClick || activeLabel() !== want);
  if (need) {
    const before = { sort: params().sort ?? null, active: activeLabel() };
    const attempts = [];
    let done = 0;
    let lastAfter = null;
    for (let round = 0; round < clicksWanted; round++) {
      const strip = tabs().filter(e => clean(e.textContent) === want);
      if (!strip.length) {
        out.click = { ok: false, reason: 'sort tab not found', tabsSeen: out.tabsSeen, attempts };
        return JSON.stringify(out);
      }
      const mark = { sort: params().sort ?? null, active: activeLabel() };
      const noDetect = !!cfg.noDetect;
      let ok = false;
      // 同一 tab 可能有多份副本（吸顶条/隐藏条），点错副本无反应 → 依次尝试
      const cands = Math.min(strip.length, 3);
      for (let i = 0; i < cands; i++) {
        const tab = strip[i];
        try { tab.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
        const dBefore = orderDigest();
        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
          tab.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, button: 0 }));
        }
        const c0 = Date.now();
        let after = null;
        if (noDetect) {
          // 「价格」这类 tab 点击后不改 __last_search_params、也不改 active 类名，
          // 只能靠「卡片顺序指纹变化」判断点击是否生效。
          for (;;) {
            if (orderDigest() !== dBefore) {
              after = { sort: params().sort ?? null, active: activeLabel(), elapsedMs: Date.now() - c0, byOrder: true };
              ok = true;
              break;
            }
            if (Date.now() - c0 > (cfg.clickWaitMs || 5000)) {
              after = { sort: params().sort ?? null, active: activeLabel(), elapsedMs: Date.now() - c0, timeout: true };
              break;
            }
            await sleep(200);
          }
          attempts.push({ round, idx: i, ok, after });
          lastAfter = after;
          if (ok) break;
          await sleep(400);
          continue;
        }
        for (;;) {
          const act = activeLabel();
          const s = params().sort ?? null;
          if ((s !== mark.sort || act !== mark.active) && (act === want || s !== mark.sort)) {
            after = { sort: s, active: act, elapsedMs: Date.now() - c0 };
            ok = true;
            break;
          }
          if (Date.now() - c0 > (cfg.clickWaitMs || 6000)) {
            after = { sort: s, active: act, elapsedMs: Date.now() - c0, timeout: true };
            break;
          }
          await sleep(200);
        }
        attempts.push({ round, idx: i, ok, after });
        lastAfter = after;
        if (ok) break;
        await sleep(400);
      }
      if (ok) done++;
      await sleep(cfg.afterClickMs ?? 900);
      const t1 = Date.now();
      for (;;) {
        if (cards().length >= minCards) break;
        if (Date.now() - t1 > 8000) break;
        await sleep(400);
      }
    }
    out.click = { ok: done >= clicksWanted, done, wanted: clicksWanted, before, after: lastAfter, attempts };
    out.activeLabel = activeLabel();
    out.params = snap();
    out.cardCount = cards().length;
    out.totalWaitMs = Date.now() - t0;
  }
  return JSON.stringify(out);
})()
