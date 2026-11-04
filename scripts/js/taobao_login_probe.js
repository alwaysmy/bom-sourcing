// 登录态探测：在淘宝首页判断当前浏览器有没有登录淘宝账号
(async () => {
  const clean = (v) => String(v == null ? '' : v).replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').replace(/\s+/g, ' ').trim();
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 30; i++) {
    if (document.body && document.body.innerText.length > 400) break;
    await sleep(500);
  }
  const txt = document.body ? document.body.innerText.slice(0, 4000) : '';
  const nickEl = document.querySelector('[class*="siteNavUser"], [class*="site-nav-user"], #J_SiteNavLogin .site-nav-menu-hd, [class*="userNick"]');
  return JSON.stringify({
    href: location.href,
    title: document.title,
    bodyLen: txt.length,
    nick: clean(nickEl ? nickEl.innerText : '').slice(0, 40),
    loginPrompt: /亲，请登录|免费注册/.test(txt),
    loggedIn: !!nickEl && !/亲，请登录/.test(txt),
    markers: ['我的淘宝', '购物车', '免费开店', '消息', '亲，请登录'].filter(k => txt.indexOf(k) >= 0)
  });
})()
