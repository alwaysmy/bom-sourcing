async function taobao_get_search_results(rawInput = {}) {
  const route = (url) => {
    if (url.hostname === 's.taobao.com' &&
        url.pathname.replace(/\/+$/, '') === '/search') {
      const query = url.searchParams.get('q') || '';
      const page = url.searchParams.get('page') || '1';
      const tab = url.searchParams.get('tab') || 'all';
      return {type: 'search', identity: `search:${query}:${page}:${tab}`};
    }
    if ((url.hostname === 'item.taobao.com' ||
         url.hostname === 'detail.tmall.com') &&
        url.pathname === '/item.htm') {
      const itemId = url.searchParams.get('id');
      if (/^\d{5,32}$/.test(itemId || ''))
        return {type: 'item', identity: `item:${itemId}`};
    }
    return null;
  };
  const taobaoAdapter = {
    matches: (url) => url.protocol === 'https:' && route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['taobao_get_search_results'] :
        ['taobao_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!taobaoAdapter.matches(routeUrl) ||
      !taobaoAdapter.toolNames(routeUrl).includes('taobao_get_search_results'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 淘宝 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['maxItems', 'maxScrolls'].includes(key)) &&
        (!('maxItems' in rawInput) ||
         (Number.isInteger(rawInput['maxItems']) && rawInput['maxItems'] >= 1 &&
          rawInput['maxItems'] <= 200)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 50))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const unique = (values) => [...new Set(values.map(clean).filter(Boolean))];
    const publicAssetUrl = (value) => {
      const resolved = absolute(value);
      return /^https:\/\//.test(resolved) ? resolved : '';
    };
    const countValue = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([万萬亿億kmb])?/i);
      if (!match)
        return null;
      const base = Number(match[1]);
      if (!Number.isFinite(base))
        return null;
      const multipliers =
          {k: 1e3, m: 1e6, b: 1e9, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8};
      return Math.round(
          base * (multipliers[(match[2] || '').toLowerCase()] || 1));
    };
    const priceValue = (value) => {
      const match = clean(value).replace(/,/g, '').match(/[\d]+(?:\.[\d]+)?/);
      const parsed = Number(match?.[0]);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const itemIdFrom = (node) => {
      const html = node;
      const candidates =
          [html.dataset.spmActId, html.dataset.nid, html.dataset.itemId];
      const links = node.matches('a[href]') ?
          [node] :
          Array.from(node.querySelectorAll('a[href]'));
      for (const link of links) {
        try {
          candidates.push(
              new URL(link.href, location.href).searchParams.get('id') ||
              undefined);
        } catch { /* Try another link. */
        }
      }
      return candidates.map(clean).find((value) => /^\d{5,32}$/.test(value)) ||
          '';
    };
    const searchCards = () => {
      const selectors = [
        'a[class*="doubleCardWrapper"][href]', '#mainsrp-itemlist .item',
        '[data-spm-act-id][class*="Card"]', '[data-nid].item'
      ];
      const nodes = selectors.flatMap(
          (selector) => Array.from(document.querySelectorAll(selector)));
      return [...new Set(nodes)].filter((node) => itemIdFrom(node));
    };
    const cardText = (card, selectors) => {
      for (const selector of selectors) {
        const value = clean(card.querySelector(selector)?.textContent);
        if (value)
          return value;
      }
      return '';
    };
    const cardList = (card, selectors) => unique(selectors.flatMap(
        (selector) => Array.from(card.querySelectorAll(selector))
                          .map((node) => node.textContent)));
    const searchItem = (card, observedIndex) => {
      const itemId = itemIdFrom(card);
      const rawHref = card.matches('a[href]') ?
          card.href :
          card.querySelector('a[href]')?.href || '';
      let source = 'taobao';
      try {
        source =
            new URL(rawHref, location.href).hostname === 'detail.tmall.com' ?
            'tmall' :
            'taobao';
      } catch { /* Keep Taobao fallback. */
      }
      const url = `${
          source === 'tmall' ? 'https://detail.tmall.com' :
                               'https://item.taobao.com'}/item.htm?id=${
          encodeURIComponent(itemId)}`;
      const priceText = cardText(card, [
        '[class*="innerPriceWrapper--"]', '[class*="priceInt--"]',
        '.price strong', '.price'
      ]);
      const image = card.querySelector('[class*="mainImg--"], img');
      const position =
          Number(card.dataset.spm || card.getAttribute('data-index'));
      const locationParts =
          cardList(card, ['[class*="procity--"]', '.location']);
      return {
        itemId,
        position: Number.isFinite(position) && position > 0 ? position :
                                                              observedIndex + 1,
        source,
        url,
        title:
            cardText(card, ['[class*="title--"]', '.row-2.title', '.title']) ||
            clean(card.textContent).slice(0, 300),
        imageUrl: publicAssetUrl(image?.currentSrc || image?.src) || null,
        price: {
          currency: 'CNY',
          value: priceValue(priceText),
          text: priceText || null,
          qualifier: cardText(card, ['[class*="priceDesc--"]']) || null
        },
        salesText:
            cardText(
                card, ['[class*="realSales--"]', '.deal-cnt', '.sale-num']) ||
            null,
        salesCount: countValue(cardText(
            card, ['[class*="realSales--"]', '.deal-cnt', '.sale-num'])),
        location: locationParts.join(' ') || null,
        shop: {
          name: cardText(
                    card,
                    ['[class*="shopNameText--"]', '.shopname', '.shop a']) ||
              null,
          badges: cardList(card, ['[class*="shopTagWrapper--"]'])
        },
        attributes: cardList(
            card,
            ['[class*="abstractInnerWrapper--"]', '[class*="descBox--"]']),
        promotions: cardList(
            card,
            [
              '[class*="secondKillInfoWrapper--"]', '[class*="coupon"]',
              '[class*="subIconWrapper--"]'
            ]),
        ranking: cardText(card, ['[class*="rankTitleWrapper--"]']) || null,
        sponsored: /(?:m?click\.simba\.taobao\.com)/.test(rawHref),
        rawText: clean(card.textContent).slice(0, 2000)
      };
    };
    {
      const maxItems =
          Math.min(200, Math.max(1, Number(input.maxItems ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const originalY = window.scrollY;
      const collected = new Map();
      let scrolls = 0;
      let idle = 0;
      const collect = () => {
        const before = collected.size;
        for (const card of searchCards()) {
          const item = searchItem(card, collected.size);
          if (item.itemId && !collected.has(item.itemId))
            collected.set(item.itemId, item);
        }
        return collected.size - before;
      };
      collect();
      while (collected.size < maxItems && scrolls < maxScrolls && idle < 3) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(700, window.innerHeight * 0.8), behavior: 'auto'});
        await pause(400);
        const added = collect();
        scrolls += 1;
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 12;
        idle = added === 0 &&
                (atEnd ||
                 beforeHeight === document.documentElement.scrollHeight) ?
            idle + 1 :
            0;
      }
      if (scrolls) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      const all = [...collected.values()].sort(
          (left, right) => left.position - right.position);
      const items = all.slice(0, maxItems);
      const pageState = win.__last_search_params || {};
      const page = Number(
          pageState.page ?? new URL(location.href).searchParams.get('page') ??
          1);
      const stopReason = all.length >= maxItems ? 'max_items' :
          maxScrolls === 0 || (scrolls >= maxScrolls && idle < 3) ?
                                                  'max_scrolls' :
                                                  'page_end';
      const truncated = stopReason !== 'page_end';
      return {
        data: {
          query: clean(decodeURIComponent(
              String(
                  pageState.q || new URL(location.href).searchParams.get('q') ||
                  '')
                  .replace(/\+/g, ' '))),
          page: Number.isFinite(page) ? page : 1,
          tab: clean(
              pageState.tab || new URL(location.href).searchParams.get('tab') ||
              'all'),
          sort: clean(pageState.sort) || null,
          pageSize: Number(pageState.pageSize || pageState.n) || null,
          totalResults: Number(pageState.totalResults) || null,
          totalPages: Number(pageState.totalPage) || null,
          count: items.length,
          observedCount: all.length,
          scrolls,
          complete: !truncated,
          truncated,
          stopReason,
          items
        },
        warnings: [
          '结果只覆盖当前搜索结果页；不会自动翻到下一页。',
          ...(pageState.pageSize && all.length < Number(pageState.pageSize) &&
                      !truncated ?
                  [`页面声明每页 ${pageState.pageSize} 个结果，实际找到 ${
                      all.length} 个可识别商品卡片。`] :
                  [])
        ]
      };
    }
  }
}

