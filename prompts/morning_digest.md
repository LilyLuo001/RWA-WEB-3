# morning_digest — 每日晨报（四分区）

由 launchd 每天 07:05 通过 `claude -p` 无头调用。工作目录 `~/rwa-signal`。

## 读者是谁（决定了这份晨报该长什么样）

**top program 的经济学博士，但刚进加密圈、没有行业背景知识。**
见 `config/settings.yaml: identity`。

⚠️ **这个区分是整份晨报最容易搞错的地方**：

| 可以假设他懂 | **不能**假设他懂 |
|---|---|
| Diamond-Dybvig、逆向选择、law of one price | 什么是代币、什么是链上 |
| 期限错配、影子银行、做市商库存 | Robinhood 的代币和 Ondo 的代币差在哪 |
| 计量、识别、内生性 | mint/redeem 是什么动作 |
| 监管经济学、机制设计 | 什么是过户代理人、ATS、DVP |

**读者原话反馈**（2026-09-12）：
> 「我知道大家在争议代币发行的股票到底是不是 security，但我的问题是，
>  什么是代币发行的股票，是 coin 吗？」
> 「你发的最后一篇偏学术的报告，我基本由于过于缺乏背景和事实基础，基本看不懂。」

所以：
- **经济学术语不用解释**，直接用
- **行业名词第一次出现必须解释**，一句话，放在 ⓪ 科普区或就地括注
- **不要复述观点，要给可检验的命题**。「流动性会改善」是废话，
  「代币化国债绝大部分交易量是 mint/redeem 而非二级转让」是命题
- 他的比较优势是**分析框架**，不是信息速度

---

## 输入

1. `data/raw/` 最近 36 小时 + 7 天（`source == "browser"`），
   用 `.venv/bin/python` + `scripts/fetch_posts.py:read_raw()`
2. `config/settings.yaml` 的 `identity`（frameworks / live_hooks 是选题弹药库）
3. 前两份 `data/digests/*.md`（不重复已推过的角度）
4. **WebSearch / WebFetch —— 第②④分区必须用，账号数据不够**

---

## 输出结构：⓪ + 四分区

### ⓪ 先搞清楚（事实科普区）

**放在最前面。** 本期出现的、读者可能不知道的行业名词/机制，
每个用 2-4 句讲清楚**它是什么、它和什么容易混淆、为什么今天要知道它**。

写法要求：
- **用他懂的东西类比**。例：代币化股票 ≈ ADR（存托凭证）的结构，
  只是托管方和法律辖区不同，且有些没有赎回权
- **讲清楚差异，不要讲定义**。「什么是代币化股票」这个问题的有用答案
  不是一句定义，而是"它至少有三种法律性质完全不同的形态"
- 不确定的地方标「未核实」，不要为了讲清楚而编

数量：2-4 条。本期没有新名词就写「本期无新名词」，不要为凑而凑。

**已讲过的不要重复。** 检查前几份 `data/digests/*.md` 的 ⓪ 区。
维护一份累积词表在 `data/digests/_glossary.md`，讲过的词记进去。

### ① 头条 —— 赛道里正在吵的事

最重要的**一件**事。不要列三件。给时间线、人名、最硬的数字、为什么重要。
本地数据没有够格的头条就用 WebSearch 去找（名单账号漏掉大新闻是常态）。

**铁律**：发行方讲自家产品 = 广告，不是信号。
`tier: issuer`（Ondo/Securitize/centrifuge/maplefinance）发自家数据、AMA、
招聘、活动，**一律不计入叙事收敛**。收敛的判定标准是 ≥3 个**没有商业利益关系**
的账号在 48 小时内独立指向同一件事。

### ② 监管 —— 新规、征求意见、执法动向

来源优先级：`tier: reg`（@SECGov / @SECPaulSAtkins / @FINRA）的原文 >
律所分析（Sidley/MoFo/Greenberg Traurig 等）> 媒体转述。

每条要给：**文件名/编号、日期、实质变化是什么、影响谁**。
「SEC 对加密更友好了」不是情报；
「Regulation Crypto Assets 提案含初创豁免：四年内一次性最高 500 万美元，
满足安全港条件后该代币不再被视为投资合同标的」才是。

**注意评论期截止日**——这是可以抢的时间窗口。

### ③ 行业 —— 谁真的下场了

**区分「宣布」和「落地」**。发新闻稿说要探索代币化，和真的发了产品、
投了钱、上了量，是两件事。能拿到数字就给数字（AUM、笔数、参与机构）。

关注：银行/资管/交易所/清算机构的实际动作，`tier: inst` + WebSearch。

### ④ 学术 —— 这一区是主动检索，不是等推送

⚠️ **严肃学术工作不以推文形式存在。** 已验证：LVR 论文作者 @ciamac 的 feed
在发房产税，@nberpubs 的论文流与代币化无关。所以**这一区必须主动去搜**。

**每天检索（用 WebSearch/WebFetch）**：
- 新工作论文：SSRN / NBER / arXiv q-fin，关键词轮换 ——
  `tokenization liquidity`、`market microstructure blockchain`、
  `limits to arbitrage crypto`、`tokenized securities settlement`、
  `stablecoin monetary`、`DeFi adverse selection`
- 央行/国际组织：BIS（Annual Economic Report、BIS Quarterly、CPMI-IOSCO）、
  IMF、OFR、Fed/ECB working papers
- 已知相关文献（可作为分析工具引用）：
  - **Makarov & Schoar (2020)** 跨交易所价格背离与套利限制 ——
    直接适用于代币化资产的 law of one price 失效
  - **LVR（Milionis-Moallemi-Roughgarden-Zhang）** AMM 做市的逆向选择成本
  - **Grossman-Hart**、dual-class / voting premium 文献 ——
    适用于"有分红无投票权"的代币结构
  - **Diamond-Dybvig**、期限转换 —— 适用于代币化基金的赎回机制

**这一区的输出不是"有哪些新论文"，而是**：
> **今天的新闻里，哪一个现象可以用哪一个框架讲，而圈内没人这么讲。**

举例（这是标准）：
> AMC 代币曾交易在标的 60 倍 → 这是 law of one price 失效。
> 三个套利障碍同时存在：无赎回机制（不能把代币换回真股）、
> 无法做空代币、市场分割（非美投资者才能持有）。
> Makarov-Schoar 记录的跨交易所价差，这里被放大到 60 倍——
> 因为他们研究的比特币至少可以跨所转移，而这个代币不能。

如果当天没有够格的学术切口，**写「本日无」**，不要硬凑。

---

## 贯穿全篇的两条铁律

**一、数字必须核实，且主动找打架的数字**
名单账号帖里的数字都是一方之词，尤其发行方自报的市场规模。
用 WebSearch 核一手来源。**主动交叉比对**，冲突就单独成段说清楚该信哪个。
每个可引用数字附**来源 + 数据时点**。查不到时点的标「勿引用」。
**绝不编造**，数据不足写「数据不足」。

**二、产出能直接用的东西**
「可以写写 A 和 B 的矛盾」不是交付物。给到能动手的程度。

---

## 末尾：今天可以写的一条

一个选题，**素材必须在本期晨报里已经齐了**。给：
- 角度（必须调用 `identity.frameworks` 里的某一个，写明是哪个）
- 反共识的那一句
- 形式（单帖 / N 条推串 / 图文）
- 发布窗口

---

## 禁止出现

- 任何系统状态：cron、抓了多少条、管道、账号数、"数据窗口"
- markdown 表格（邮件渲染差，用短段落和列表）
- 「排队中」「下一步」等待办清单
- 解释**经济学**概念（Diamond-Dybvig 是什么不用讲）
- 没有来源的数字
- 行业黑话不解释就直接用（ATS / DVP / mint-redeem / 过户代理人 / ERC-3643 等，
  第一次出现必须括注或进 ⓪ 区）

---

## 完成后

1. 写入 `data/digests/YYYY-MM-DD.md`
2. `.venv/bin/python scripts/notify.py --send-file data/digests/YYYY-MM-DD.md --subject "<具体主题>"`
   主题写出今天最重要的那件事，不要写"每日晨报"
3. stdout 打印 `DIGEST_OK <路径>`
