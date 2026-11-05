# 品牌实测采集记录（立创商城）

> 本文件是 `probe/vendors/` 脚本的**原始实测记录**，用来支撑
> `skills/bom-sourcing/data/knowledge/vendors.yaml` 里的 tier 判定。
> 人读版维护流程见 `skills/bom-sourcing/references/vendors.md`。

## 1. 采集口径

| 项 | 值 |
| --- | --- |
| 采集时间 | 2026-11-05 |
| 关键词数 | 25 |
| 商品记录数 | 645 |
| 不同品牌数 | 144 |
| 数据入口 | 浏览器打开 `https://so.szlcsc.com/global.html?k=<关键词>`，解析页面内嵌 `__NEXT_DATA__`（SSR，非 XHR） |
| 单关键词上限 | 30 条（搜索结果首屏，按「综合」排序） |
| 价格口径 | 商品阶梯价的**最小数量档**单价，人民币含税；不同品牌起订量不同，仅作量级比较 |
| 库存口径 | 采集瞬时的「现货」数，会变 |

为什么不用 `scripts/lcsc.py search`：该脚本打 `POST https://so.szlcsc.com/query/product`，
当前被腾讯 EdgeOne WAF 拦成 `HTTP 203` 挑战页（`STGW-STATUS-CODE: 203`），返回 HTML 而非 JSON；
在页面内 `fetch` 同一端点仍是 203，说明是端点级封禁。搜索结果页改成了 Next.js SSR，
`props.pageProps.soData.searchResult` 里有全部首屏数据，因此走 `__NEXT_DATA__`。

## 2. 各关键词采集结果

| # | 关键词 | 记录数 | 品牌数 | 最低单价 | 最高单价 | 最低价品牌 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `AMS1117-3.3` | 30 | 18 | ¥0.2271 | ¥1.2589 | GMIC(绿微) |
| 2 | `W25Q64` | 30 | 2 | ¥6.3900 | ¥43.6900 | Winbond(华邦) |
| 3 | `STM32F103C8T6` | 8 | 7 | ¥5.5400 | ¥146.4000 | FCM(闪芯微) |
| 4 | `10k 0603 1%` | 30 | 16 | ¥0.0090 | ¥0.2921 | Sunway(信维通信) |
| 5 | `100nF 0603 50V` | 30 | 12 | ¥0.0202 | ¥0.4389 | YAGEO(国巨) |
| 6 | `SS34` | 30 | 17 | ¥0.1356 | ¥3.1000 | Zhengxin(正芯) |
| 7 | `1N4148W` | 30 | 23 | ¥0.0392 | ¥0.3036 | FOSAN(富捷/富信) |
| 8 | `AO3400` | 30 | 22 | ¥0.1012 | ¥0.6888 | FOSAN(富捷/富信) |
| 9 | `LM358` | 30 | 15 | ¥0.1767 | ¥12.3300 | GMIC(绿微) |
| 10 | `NE555` | 30 | 19 | ¥0.1420 | ¥3.2000 | GMIC(绿微) |
| 11 | `PC817` | 30 | 9 | ¥0.1026 | ¥0.6783 | DDF(鼎德丰) |
| 12 | `SRD-05VDC-SL-C` | 1 | 1 | ¥2.7100 | ¥2.7100 | 松乐 |
| 13 | `Type-C 16P 母座` | 30 | 5 | ¥0.5506 | ¥8.3500 | LX(连欣科技) |
| 14 | `2.54 排针 40P` | 30 | 13 | ¥0.8429 | ¥6.6700 | HanElectricity(瀚源) |
| 15 | `16MHz 贴片晶振` | 30 | 6 | ¥0.4100 | ¥2.4500 | YXC(扬兴晶振) |
| 16 | `10uH 电感` | 30 | 11 | ¥0.1697 | ¥1.6009 | Sunlord(顺络) |
| 17 | `0603 磁珠` | 30 | 5 | ¥0.0545 | ¥0.5458 | FH(风华) |
| 18 | `100uF 25V 铝电解` | 30 | 15 | ¥0.1719 | ¥1.0624 | ROQANG(容强) |
| 19 | `10uF 16V 钽电容` | 30 | 7 | ¥0.6843 | ¥4.4500 | XY(振华新云) |
| 20 | `MT3608` | 5 | 2 | ¥0.3411 | ¥0.7932 | 西安航天民芯 |
| 21 | `CH340C` | 1 | 1 | ¥3.3300 | ¥3.3300 | WCH(南京沁恒) |
| 22 | `LM2596` | 30 | 10 | ¥2.1547 | ¥11.9400 | XBLW(芯伯乐) |
| 23 | `S8050` | 30 | 24 | ¥0.0393 | ¥0.2078 | FOSAN(富捷/富信) |
| 24 | `TL431` | 30 | 12 | ¥0.1375 | ¥3.8100 | MSKSEMI(美森科) |
| 25 | `SS8050` | 30 | 21 | ¥0.0626 | ¥4.0900 | SEP(威旺) |

## 3. 品牌频次 Top 40

频次 = 该品牌在 25 个关键词的 645 条记录中出现的次数；「品类数」= 命中的不同关键词数。
**同一品牌横跨大量不相关品类，是贸易商/贴牌的机械特征**（原厂只在自家品类出现）。

| # | productGradePlateName | 记录数 | 品类数 | tier | 命中关键词 |
| --- | --- | --- | --- | --- | --- |
| 1 | TI(德州仪器) | 32 | 4 | original_idm | LM2596、LM358、NE555、TL431 |
| 2 | Winbond(华邦) | 28 | 1 | original_idm | W25Q64 |
| 3 | YXC(扬兴晶振) | 22 | 1 | original_idm | 16MHz 贴片晶振 |
| 4 | R+O(宏嘉诚) | 21 | 7 | trader | 1N4148W、LM2596、LM358、S8050… |
| 5 | UMW(友台半导体) | 19 | 9 | domestic_second | AMS1117-3.3、AO3400、LM2596、LM358… |
| 6 | muRata(村田) | 18 | 3 | original_idm | 0603 磁珠、100nF 0603 50V、10uH 电感 |
| 7 | JSMSEMI(杰盛微) | 17 | 10 | trader | 1N4148W、AMS1117-3.3、AO3400、LM358… |
| 8 | GOODWORK(固得沃克) | 17 | 9 | trader | 1N4148W、AMS1117-3.3、AO3400、NE555… |
| 9 | VISHAY(威世) | 14 | 3 | original_idm | 10k 0603 1%、10uF 16V 钽电容、1N4148W |
| 10 | YONGYUTAI(永裕泰) | 12 | 7 | domestic_second | 1N4148W、AMS1117-3.3、AO3400、NE555… |
| 11 | HXY MOSFET(华轩阳电子) | 11 | 6 | domestic_second | 1N4148W、AO3400、NE555、PC817… |
| 12 | LX(连欣科技) | 11 | 1 | domestic_second | Type-C 16P 母座 |
| 13 | cjiang(长江微电) | 11 | 1 | domestic_second | 10uH 电感 |
| 14 | CJ(江苏长电/长晶) | 10 | 5 | original_idm | 16MHz 贴片晶振、1N4148W、S8050、SS34… |
| 15 | TDSEMIC(拓电半导体) | 10 | 5 | domestic_second | 1N4148W、NE555、S8050、SS8050… |
| 16 | Sunlord(顺络) | 10 | 2 | original_idm | 0603 磁珠、10uH 电感 |
| 17 | SHARP(夏普) | 10 | 1 | original_idm | PC817 |
| 18 | FOSAN(富捷/富信) | 9 | 8 | trader | 100uF 25V 铝电解、1N4148W、AMS1117-3.3、AO3400… |
| 19 | MSKSEMI(美森科) | 9 | 8 | domestic_second | AMS1117-3.3、AO3400、LM358、NE555… |
| 20 | TWGMC(迪嘉) | 9 | 6 | domestic_second | 1N4148W、AMS1117-3.3、AO3400、LM2596… |
| 21 | MDD(辰达半导体) | 9 | 5 | domestic_second | 1N4148W、S8050、SS34、SS8050… |
| 22 | SHOU HAN(首韩) | 9 | 2 | domestic_second | 10uH 电感、Type-C 16P 母座 |
| 23 | TDK | 9 | 2 | original_idm | 0603 磁珠、100nF 0603 50V |
| 24 | YAGEO(国巨) | 9 | 2 | original_idm | 100nF 0603 50V、10k 0603 1% |
| 25 | GMIC(绿微) | 8 | 5 | domestic_second | AMS1117-3.3、AO3400、LM358、NE555… |
| 26 | TECH PUBLIC(台舟) | 8 | 4 | domestic_second | AMS1117-3.3、AO3400、LM2596、NE555 |
| 27 | JIERR(捷而瑞) | 8 | 2 | domestic_second | 100uF 25V 铝电解、10uH 电感 |
| 28 | Kyocera AVX | 8 | 1 | original_idm | 10uF 16V 钽电容 |
| 29 | Slkor(萨科微) | 7 | 6 | domestic_second | 1N4148W、AMS1117-3.3、PC817、S8050… |
| 30 | XBLW(芯伯乐) | 7 | 5 | unknown | AMS1117-3.3、AO3400、LM2596、LM358… |
| 31 | FH(风华) | 7 | 4 | original_idm | 0603 磁珠、100nF 0603 50V、10k 0603 1%、10uH 电感 |
| 32 | HGSEMI(华冠) | 7 | 3 | domestic_second | LM2596、LM358、NE555 |
| 33 | KEMET(基美) | 7 | 2 | original_idm | 100nF 0603 50V、10uF 16V 钽电容 |
| 34 | HKT(合科泰) | 6 | 6 | domestic_second | 1N4148W、AO3400、S8050、SS34… |
| 35 | ST(意法半导体) | 6 | 3 | original_idm | LM358、STM32F103C8T6、TL431 |
| 36 | BORN(伯恩半导体) | 5 | 3 | domestic_second | AO3400、S8050、SS34 |
| 37 | HGC(深圳汉芯) | 5 | 3 | domestic_second | AMS1117-3.3、LM2596、LM358 |
| 38 | AOTE(奥特) | 5 | 2 | domestic_second | NE555、PC817 |
| 39 | FOJAN(富捷) | 5 | 2 | domestic_second | 100nF 0603 50V、10k 0603 1% |
| 40 | KNSCHA(科尼盛) | 5 | 2 | domestic_second | 100uF 25V 铝电解、10uF 16V 钽电容 |

## 4. 同型号多品牌价差（替代判定的风险来源）

同一 MPN 在商城上挂着多个品牌的 C 号，**料号一样但不代表能互换**。
下表列出实测中品牌数最多的型号，价差倍数 = 最高价 / 最低价。

| 型号 | 品牌数 | 最低价 | 最高价 | 价差 | 最低价品牌 | 最高价品牌 |
| --- | --- | --- | --- | --- | --- | --- |
| `S8050` | 17 | ¥0.0393（FOSAN(富捷/富信)） | ¥0.1004（BORN(伯恩半导体)） | 2.6× | FOSAN(富捷/富信) | BORN(伯恩半导体) |
| `1N4148W` | 16 | ¥0.0392（FOSAN(富捷/富信)） | ¥0.1092（YANGJIE(扬杰)） | 2.8× | FOSAN(富捷/富信) | YANGJIE(扬杰) |
| `SS8050` | 15 | ¥0.0626（SEP(威旺)） | ¥0.1681（ALJ(龙晶微)） | 2.7× | SEP(威旺) | ALJ(龙晶微) |
| `SS34` | 13 | ¥0.1356（Zhengxin(正芯)） | ¥3.1000（onsemi(安森美)） | 22.9× | Zhengxin(正芯) | onsemi(安森美) |
| `AMS1117-3.3` | 13 | ¥0.2308（国芯佳品） | ¥1.2589（Advanced Monolithic Systems） | 5.5× | 国芯佳品 | Advanced Monolithic Systems |
| `AO3400` | 12 | ¥0.1012（FOSAN(富捷/富信)） | ¥0.3563（BORN(伯恩半导体)） | 3.5× | FOSAN(富捷/富信) | BORN(伯恩半导体) |
| `AO3400A` | 10 | ¥0.1772（baocheng(宝乘)） | ¥0.5430（AOS） | 3.1× | baocheng(宝乘) | AOS |
| `TL431` | 8 | ¥0.1409（FOSAN(富捷/富信)） | ¥0.3286（HKT(合科泰)） | 2.3× | FOSAN(富捷/富信) | HKT(合科泰) |
| `PC817C` | 6 | ¥0.1389（AOTE(奥特)） | ¥0.5416（Slkor(萨科微)） | 3.9× | AOTE(奥特) | Slkor(萨科微) |
| `NE555` | 5 | ¥0.2799（IDCHIP(英锐芯)） | ¥0.7481（Gcore(扬州国芯)） | 2.7× | IDCHIP(英锐芯) | Gcore(扬州国芯) |
| `DSS34` | 5 | ¥0.1987（Slkor(萨科微)） | ¥0.3147（BORN(伯恩半导体)） | 1.6× | Slkor(萨科微) | BORN(伯恩半导体) |
| `AMS1117-3.3V` | 4 | ¥0.2996（MSKSEMI(美森科)） | ¥0.3993（WPMtek(维攀)） | 1.3× | MSKSEMI(美森科) | WPMtek(维攀) |

## 5. tier 分布（写入 vendors.yaml 的 144 个品牌）

| tier | 品牌数 |
| --- | --- |
| `domestic_second` | 75 |
| `original_idm` | 42 |
| `unknown` | 12 |
| `original_fabless` | 9 |
| `trader` | 6 |

## 6. 高风险品牌（本次实测里命中的贸易商 / 未判定）

| 品牌 | tier | 记录数 | 品类数 | 命中关键词 | 风险 |
| --- | --- | --- | --- | --- | --- |
| JSMSEMI(杰盛微) | trader | 17 | 10 | 1N4148W、AMS1117-3.3、AO3400、LM358、NE555 | 见 vendors.yaml 的 risk_note |
| GOODWORK(固得沃克) | trader | 17 | 9 | 1N4148W、AMS1117-3.3、AO3400、NE555、PC817 | 见 vendors.yaml 的 risk_note |
| FOSAN(富捷/富信) | trader | 9 | 8 | 100uF 25V 铝电解、1N4148W、AMS1117-3.3、AO3400、S8050 | 见 vendors.yaml 的 risk_note |
| R+O(宏嘉诚) | trader | 21 | 7 | 1N4148W、LM2596、LM358、S8050、SS34 | 见 vendors.yaml 的 risk_note |
| XBLW(芯伯乐) | unknown | 7 | 5 | AMS1117-3.3、AO3400、LM2596、LM358、NE555 | 见 vendors.yaml 的 risk_note |
| IDCHIP(英锐芯) | unknown | 2 | 2 | LM358、NE555 | 见 vendors.yaml 的 risk_note |
| ST(先科) | unknown | 2 | 2 | 100uF 25V 铝电解、1N4148W | 见 vendors.yaml 的 risk_note |
| Gcore(扬州国芯) | unknown | 1 | 1 | NE555 | 见 vendors.yaml 的 risk_note |
| HKR(香港电阻) | unknown | 1 | 1 | 10k 0603 1% | 见 vendors.yaml 的 risk_note |
| LIZ(丽智电子) | unknown | 1 | 1 | 10k 0603 1% | 见 vendors.yaml 的 risk_note |
| OSHWHub(立创开源硬件平台) | unknown | 1 | 1 | STM32F103C8T6 | 见 vendors.yaml 的 risk_note |
| SAE(世盟/世爱) | unknown | 1 | 1 | 10k 0603 1% | 见 vendors.yaml 的 risk_note |
| SIE(永星科技) | unknown | 1 | 1 | 10k 0603 1% | 见 vendors.yaml 的 risk_note |
| Sunway(信维通信) | unknown | 1 | 1 | 10k 0603 1% | 见 vendors.yaml 的 risk_note |
| YTL(亚特联) | trader | 1 | 1 | STM32F103C8T6 | 见 vendors.yaml 的 risk_note |

## 7. 复现方式

```powershell
cd D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\vendors
python collect.py      # 逐关键词采集 -> raw/*.json（每请求间隔 >=1s，25 个词约 2 分钟）
python stats.py        # 品牌频次 + 同型号多品牌 -> brand-stats.json
python by_keyword.py   # 按关键词铺开 -> by_keyword.txt
python gen_vendors.py  # 实测 + 人工目录 -> vendors.yaml
python report.py       # 本文件
```

`collect.py` 依赖本机 Kimi WebBridge daemon（`http://127.0.0.1:10086`）与浏览器扩展；
daemon 不在时直接报连接错误。
