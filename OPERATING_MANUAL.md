# rwa-signal 操作手册 —— 给接手 AI 的完整指令

> **这份文件是自包含的。** 读完它 + `config/settings.yaml` + `config/accounts.yaml`，
> 你就能独立运行这套系统，不需要读历史对话。
>
> 适用于任何 Claude 模型。工作目录 `~/rwa-signal`。
> 最后更新 2026-09-13。

---

# 第一部分：你在为谁工作

**用户 Lily。top program 经济学博士，在 X 上做 RWA（真实世界资产代币化）内容账号。**
账号 `@lilysharp88`，冷启动阶段（2026-09 开号）。

## 她要什么

1. 找到 RWA 圈的核心声音并关注
2. 在他们的帖子下留有分量的评论（她原话："神评论"）
3. 定期收到整理好的热点和圈内关注，用于创作
4. 创作完成后由 AI 代为发布
5. 冷账号前几个月帮她增加曝光

## 她的比较优势，和你必须守住的东西

**她的差异化不是"懂行"，是有分析框架。** 圈里不缺消息灵通的人，缺能说出
"这个机制为什么会失效、在什么条件下失效"的人。

**⚠️ 全系统最容易搞错的一点 —— 她懂经济学，不懂加密圈：**

| 可以直接用，不用解释 | **必须解释**，第一次出现就解释 |
|---|---|
| Diamond-Dybvig、逆向选择 | 什么是代币、什么是链上 |
| law of one price、limits to arbitrage | mint/redeem 是什么动作 |
| 期限错配、影子银行、做市商库存 | 过户代理人、ATS、DVP、ERC-20 |
| 识别、内生性、计量 | Robinhood 的代币和 Ondo 的代币差在哪 |

她的原话反馈（2026-09-12）：
> 「我知道大家在争议代币发行的股票到底是不是 security，但我的问题是，
>  什么是代币发行的股票，是 coin 吗？」
> 「你发的最后一篇偏学术的报告，我基本由于过于缺乏背景和事实基础，基本看不懂。」

**所以：经济学术语直接用；行业黑话必须就地解释或进晨报 ⓪ 区。**

## 硬约束

- **零预算。$0。** 不用任何付费 API。用户明确说过"不会付一分钱"
- **不自动发布。** 所有发布动作必须她确认。这是账号安全，也是她的要求
- **绝不编造数字。** RWA 圈的人会抓数字，错一次账号可信度归零

---

# 第二部分：东西都在哪

```
~/rwa-signal/
├── config/
│   ├── settings.yaml      ← identity（她的定位和分析框架）、限速、阈值
│   ├── accounts.yaml      ← 30 个监听账号，按 tier 分层，带体检数据
│   └── notify.yaml        ← 邮件推送配置（收件人、方式）
├── prompts/               ← 判断层规范。你执行的就是这些
│   ├── morning_digest.md  ← 每日晨报（⓪ 科普 + 四分区）
│   ├── comment_watch.md   ← 评论机会扫描 + 起草
│   └── post_review.md     ← 她写完初稿后的优化
├── scripts/
│   ├── x_browser.py       ← 浏览器会话（登录、状态检查、探测 handle）
│   ├── fetch_browser.py   ← L1 取数：抓名单账号时间线
│   ├── follow_list.py     ← 分批关注
│   ├── vet_accounts.py    ← 名单体检（死号/跑题检测）
│   ├── publish.py         ← L4 发布（回复/发帖），默认 dry-run
│   ├── x_send.py          ← 浏览器发送底层（回复/发帖/点赞/引用/推串）
│   ├── notify.py          ← 邮件推送（Resend + HTML 渲染）
│   ├── stats.py           ← 复盘统计
│   ├── common.py          ← 配置读取、限速闸门、状态管理
│   └── cron_runner.sh     ← 所有定时任务的入口
├── data/
│   ├── raw/YYYY-MM-DD.jsonl   ← 抓到的帖子（gitignored）
│   ├── digests/*.md           ← 晨报（**入库**，可读）
│   ├── drafts/*.json          ← 待确认的评论草稿（gitignored）
│   ├── cron.log               ← 所有定时任务日志，排障第一站
│   └── audit.jsonl            ← 发布审计
├── state/                 ← 会话、去重游标、配额（gitignored）
│   └── browser-profile/   ← X 登录态。**不要动，不要提交**
└── launchd/               ← 定时任务 plist
```

**Python 一律用 `.venv/bin/python`**，不是系统 python。

---

# 第三部分：系统怎么跑

## 架构：四层

| 层 | 做什么 | 谁做 |
|---|---|---|
| L1 取数 | 浏览器访问名单账号主页，抓帖入库 | `fetch_browser.py`（机械活） |
| L2 信号 | 评论机会打分、叙事检测、选题 | **你**（按 `prompts/`） |
| L3 创作 | 她的初稿 → 事实核查、钩子、结构 | **你**（按 `post_review.md`） |
| L4 发布 | 回复/发帖 | `publish.py`（她确认后） |

**判断层给 AI，机械层给 Python。** "值不值得回"和"怎么写才不水"是推理问题，
硬编码的打分规则只会是它的劣质版本。

## 定时任务（launchd，不是 cron）

| 任务 | 频率 | 内容 |
|---|---|---|
| fetch | 20 分钟 | 抓 30 个账号 |
| comment_watch | 2 小时 | 抓取 + 调用你 → 草稿，≥72 分发邮件 |
| digest | 每天 07:05 | 抓取 + 调用你 → 晨报发邮件 |
| **discover** | **2 小时** | **挖新账号 → 体检 → 通过才关注（日上限 12）** |
| **like** | **2 小时** | **给名单值得的帖子点赞（日上限 30）** |
| follow | 每天 09:30 | 关注名单里已有但未关注的（名单关完会空转） |
| status | 每天 23:00 | 会话健康 + 额度统计 |

**为什么不用 cron**：macOS 睡眠时 cron 不补跑，launchd 唤醒后会补。

定时任务通过 `claude -p` 无头调用你，prompt 来自 `prompts/`。
你被这样唤起时，**直接执行，不要反问、不要复述规范**。

## 零预算怎么做到的

X API 从 2026 年起全面按量付费（$0.005/条读取，需预充值），所以：
**用户手动登录一次浏览器，会话存在 `state/browser-profile/`，
之后所有脚本以无头模式复用。** 不碰密码，不存密码。

---

# 第四部分：日常工作怎么做

## A. 出晨报（最重要的产出）

执行 `prompts/morning_digest.md`。结构是 **⓪ + 四分区**：

### ⓪ 先搞清楚（科普区，放最前面）
本期出现的行业名词，每个 2-4 句：**是什么 / 和什么容易混淆 / 今天为何要知道**。
用她懂的东西类比（例：代币化股票 ≈ ADR 结构，但托管方和法辖区不同、部分无赎回权）。
**讲差异不讲定义** —— "什么是代币化股票"的有用答案不是一句定义，
而是"它至少有三种法律性质完全不同的形态"。
已讲过的记进 `data/digests/_glossary.md`，不重复。

### ① 头条 —— 赛道在吵什么
**一件事**，不是三件。给时间线、人名、最硬的数字、为什么重要。

⚠️ **发行方讲自家产品 = 广告，不是信号。** `tier: issuer`（Ondo / Securitize /
centrifuge / maplefinance）发自家数据、AMA、招聘、活动，**一律不计入叙事收敛**。
收敛的判定：**≥3 个没有商业利益关系的账号**在 48 小时内独立指向同一件事。
（第 1 期晨报就是把 Ondo 宣传 Ondo Stocks 写成了"收敛信号"，别重犯。）

### ② 监管 —— 新规、征求意见、执法
来源优先级：`tier: reg` 原文 > 律所分析（Sidley / MoFo / Greenberg Traurig）> 媒体。
每条给：**文件名或编号、日期、实质变化、影响谁**。注意**评论期截止日**——那是可抢的窗口。

反例："SEC 对加密更友好了"
正例："Regulation Crypto Assets 提案含初创豁免：四年内一次性最高 500 万美元"

### ③ 行业 —— 谁真的下场了
**区分「宣布」和「落地」**。发新闻稿说要探索，和真发了产品、投了钱、上了量，是两件事。
能拿到数字就给（AUM、笔数、参与机构）。

### ④ 学术 —— 主动检索，不是等推送
⚠️ **严肃学术工作不以推文形式存在。** 已验证：LVR 论文作者 @ciamac 的 feed 在发
纽约房产税，@tim_roughgarden 发共识协议课程，@nberpubs 零相关。所以必须主动搜：
SSRN / NBER / arXiv q-fin / BIS / IMF / OFR / Fed / ECB。

**这一区的产出不是"有哪些新论文"，而是**：
> 今天的新闻里，哪个现象可以用哪个框架讲，而圈内没人这么讲。

标准示例：
> AMC 代币曾交易在标的 60 倍 → law of one price 失效。三个套利障碍同时存在：
> 无赎回机制（代币换不回真股）、无法做空、市场分割（仅非美投资者可持有）。
> Makarov-Schoar 记录的跨所价差，这里放大到 60 倍 —— 因为比特币至少能搬，这个搬不了。

没有够格的切口就写「本日无」，不要硬凑。

### 末尾：今天可以写的一条
一个选题，**素材必须本期已经齐了**。给：角度（写明调用哪个框架）、
反共识的那一句、形式、发布窗口。

### 晨报禁止出现
- 系统状态（cron、抓了多少条、管道、账号数、"数据窗口"）
- markdown 表格（邮件渲染差，用短段落和列表）
- 待办清单
- 解释经济学概念
- 没有来源的数字
- 行业黑话不解释直接用

### 完成后
1. 写入 `data/digests/YYYY-MM-DD.md`
2. `.venv/bin/python scripts/notify.py --send-file <路径> --subject "<具体主题>"`
   主题写出最重要的那件事，不要写"每日晨报"
3. stdout 打印 `DIGEST_OK <路径>`

## B. 扫评论机会

执行 `prompts/comment_watch.md`。要点：

**时间窗口**：架构是轮询 profile 页，帖子到手通常已 1–12 小时。
**决定因素是「剩余空位」，不是「新鲜度」** —— 一条 8 小时前只有 4 条回复的帖子，
比一条 1 小时前已有 60 条回复的好得多。超过 36 小时不看。

**草稿要用她的框架**（`identity.frameworks`）。好草稿的标准：
读者看完会想"这人是哪个方向的"，而不是"这人消息挺灵通"。

- ❌ 「代币化股票增长很快，但监管还没跟上」—— 谁都能写
- ✅ 「没有赎回权，套利就没有强制机制。Makarov-Schoar 记录的跨所价差至少还能
  搬币收敛，这里搬不了，所以能看到 60 倍」

⚠️ **但不要掉书袋**。框架用来**决定说什么**，不是用来**展示读过什么**。
能不点文献名就不点。术语用圈内说法（"no redemption"），不用论文说法。

**神评论判定**：这条评论能不能原封不动贴到另一条帖子下面？能 → 水评论，重写。

**禁止**：赞美、复述原帖、只有 emoji、自我推广、万能聪明话、空洞提问、编造数字。

**语言**：`data/raw` 里的文本可能是 X 的自动翻译。Ondo / Securitize /
centrifuge / arthur0x / Observatory13 等**原文是英文，草稿必须用英文**。
`0xNing0x` / `BTCdayu` 用中文。英文 ≤240 字符，中文 ≤100 字。

完成后写 `data/drafts/YYYY-MM-DD-HHMM-<handle>.json`，≥72 分发提醒邮件，
stdout 打印 `WATCH_OK <数量>`。

## C. 自动点赞（已自动化，每 2 小时）

`like_recent.py`，日上限 30（`settings.yaml: max_likes_per_day`），
走 `check_safety` 同一道闸门，每次间隔随机 20-70 秒（匀速是机器人特征）。

⚠️ **点赞是公开的，任何人都能查她赞过什么。** 所以有四道筛选：
1. **tier 白名单**：只赞 kol/reg/acad/issuer/inst/data/zh，**跳过 watch**
   （赞 @BTCdayu 的 meme 币帖会直接拆掉她正在建的严肃分析者定位）
2. **政治内容一律不赞** —— 公开点赞等于站队。实测 @a16zcrypto 发过
   "每一个美国公民，无论政治立场如何…"，这种绝不能赞
3. **必须命中核心词**（代币化/链上/稳定币…）。泛金融词不够 ——
   实测 @IMFNews 讲亚洲增长、欧盟入盟的帖会因"机构"命中而漏进来
4. 原帖至少 3 个赞（太冷清的赞了没意义）、非转发、正文 ≥25 字

2026-09-13 首次真实执行 3 条并独立复核（testid=unlike 确认）。
这是本系统**第一次真实写操作**。

## D. 发布（她确认后）

```bash
.venv/bin/python scripts/publish.py --draft <草稿id> --pick A          # dry-run
.venv/bin/python scripts/publish.py --draft <草稿id> --pick A --yes    # 真发
```

限速闸门在 `common.check_safety`，**不要绕过**（`--force` 会记审计日志）。
冷号第 1 周每天回复上限 3 条，按周放开到 12。点赞 ≤30/天。

⚠️ **截至 2026-09-13，一条内容（回复/发帖）都没真实发送过。**
`audit.jsonl` 只有 `dry_run` / `follow` / `like`。
发帖链路（浏览器通道、quote、thread）只过了编译和 dry-run。
**第一次真实发送时要格外小心，逐步验证。**
（点赞链路已在 09-13 验证通过，可作为参考。）

## E. 扩充名单（已自动化，每 2 小时一轮）

`discover_accounts.py` 已接入 launchd，每 2 小时自动跑完整闭环：
挖掘 → 加候选 → 抓取 → 体检 → 通过则关注 / 未过则移出并拉黑。

**天然限速**：瓶颈是"有没有挖到够格的人"，不是关注频率。
所以既满足每 2 小时新增，又不会把冷号刷爆。日上限 12（`--daily-cap`）。

打分 = 提及次数 × 提及者 tier 权重（reg/acad 3.0 > kol 2.5 > data/inst 1.5
> issuer/zh 1.0 > watch 0.4）。

⚠️ **两道必需的闸门，少一道就会灌垃圾**：
1. **相关性闸门**：只统计出现在**主题相关推文**里的提及。
   没有它，@IMFNews 这类什么都发的账号会把候选灌满欧盟入盟论文、
   非洲 AI、泰国央行 —— 而且因 acad 权重高，排名还很靠前。
   实测：加闸门后候选从 33 个降到 7 个，且全部相关。
2. **黑名单**（`state/rejected.json`）：体检未过的记下来，不再重复抓取。

手动跑：
```bash
.venv/bin/python scripts/discover_accounts.py            # 只看挖到谁
.venv/bin/python scripts/discover_accounts.py --run --max 3
```

**不要抄榜单。** 第一版名单就是抄来的，15 个里 4 个死号（最久 923 天没发帖），
2 个活跃但一条 RWA 都不发。而讽刺的是，那份"Top 5 RWA 影响力"榜单的
来源账号本身已经死了 518 天。

**正确方法：从真实对话里挖人。**
```bash
# 对已抓帖子做 @提及 频次分析，挖出圈内真实在对话的人
# 然后 → 加为 candidate → fetch → vet → 通过才升级
.venv/bin/python scripts/fetch_browser.py --accounts <新handle...> --per-account 12
.venv/bin/python scripts/vet_accounts.py --write
.venv/bin/python scripts/follow_list.py --max 8
```

体检标准：死号 >30 天（acad/reg/data 放宽到 90 天）、跑题 <30%。
**acad/reg 用产业+学术词表的并集** —— 只用学术词表会把 SEC 从 89% 误判到 22%，
只用产业词表会把 BIS 判成跑题。

实测有效：挖出的 7 个真人全部通过体检（Observatory13 82% / syrupsid 67% /
carlosdomingo 58%），远优于榜单账号（ZssBecker 9% / BTCdayu 12%）。

---

# 第五部分：名单结构

`config/accounts.yaml` 的 tier 对应晨报四分区：

| tier | 含义 | 用途 |
|---|---|---|
| `kol` | 真人分析者（7 个） | 评论主战场 |
| `reg` | 监管机构本身（3 个） | ② 监管区一手源，引用原文不会有数字错误 |
| `acad` | 学术/政策研究（3 个） | ④ 学术区，但主要靠主动检索 |
| `inst` | 传统金融机构（1 个） | ③ 行业区，判断谁真下场 |
| `issuer` | 项目官方号（4 个） | 可评论，但**不算独立信源** |
| `data` | 数据/聚合源（4 个） | 热点检测 |
| `zh` | 中文圈（1 个） | 中文互动池 |
| `watch` | 只做热点检测（7 个） | **不作为评论目标** |

**名单里最该重视的两个**：
- **@Observatory13 = Brett Redfearn**，前 SEC 交易与市场部主任，现 Securitize 总裁。
  他写过现行市场结构规则，现在从业内批评它。相关度 82%。**优先评论对象**
- **@SECGov** 相关度 100%，监管原文一手源

---

# 第六部分：踩过的坑（重犯代价很高）

1. **代理**：本机走 Clash（127.0.0.1:7890）。launchd 不继承 shell 变量，
   缺代理时 `claude -p` 请求到不了 API，**CLI 把网络层拒绝显示成
   "403 Request not allowed"**，看起来像额度用尽。
   `cron_runner.sh` 已加代理自举。排障第一步：`nc -z 127.0.0.1 7890`

2. **无头调用要显式下指令**：直接把规范文档塞进 `claude -p`，模型会当成
   一份文档来读，回你"我看到了这个文件，你想让我做什么？"。
   必须明确说"这不是待讨论的文档，是你现在要完成的任务"。同时 `< /dev/null`
   重定向 stdin，否则卡在等输入。

3. **浏览器 profile 互斥**：Playwright persistent profile 同时只能一个进程打开。
   撞上时报的是「会话失效」——**会误导人去重新登录**。
   真因通常是上一轮的孤儿进程。`cron_runner.sh` 已加锁和 `reap_orphans`。
   手动清理：`pkill -f "user-data-dir=$HOME/rwa-signal/state/browser-profile"`

4. **中文界面**：关注按钮 `button[data-testid$="-follow"]`，位于
   `div[data-testid="placementTracking"]` 内。已关注文字是「**正在关注**」，
   不是「关注中」。

5. **Z 后缀时间戳**：浏览器抓的 `created_at` 是 `...Z`，Python 3.10 的
   `fromisoformat` 不认 → 曾导致 `read_raw` 静默丢弃全部数据。已修（`parse_ts`）。

6. **推串取 post id**：`send_post` 发完后浏览器停在 `/compose/post`，URL 里
   没有 `/status/`。必须回自己主页取最新帖（`_newest_own_post_id`）。

7. **纯文本邮件**：markdown 表格在 text/plain 里是一堆竖线。`notify.py` 已加
   `md_to_html`。这是第 1 期晨报排版崩掉的原因。

8. **pip**：直连 PyPI 偶发 SSL 断连，用清华镜像
   `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

---

# 第七部分：工作纪律（这套系统失败过一次，原因在这）

**2026-09-12 做过一次完整审计，发现交付层大面积虚报。** 根因是
**验收标准错了：全程在验"脚本退出码 0"，没有一处验"产出是不是对的"。**

当时的实际状况：
- 名单 15 个里 4 个死号、2 个完全跑题，而"已核验"只是"这个 handle 在某个榜单出现过"
- cron 的 digest 分支只 `echo` 一行字，等于晨报永远不会产生，却对用户说"每天 7 点自动发"
- comment_watch 从未产出过一条真草稿
- 晨报把发行方营销包装成"叙事收敛"

**所以你必须守住四条：**

### 1. 每一项完成必须有可执行的验收命令
不要说"已完成"。跑一条命令，把输出念给用户听。
- 关注了？→ 上 X 逐个核对按钮状态
- 定时任务配好了？→ 在 `env -i` 的干净环境下真跑一次
- 名单核验了？→ `vet_accounts.py` 的输出是什么

### 2. 数字必须核到一手来源，并主动找打架的数字
名单账号帖里的数字都是一方之词，尤其发行方自报的市场规模。
**主动交叉比对**，冲突就单独成段说清楚该信哪个、为什么。
每个可引用数字附**来源 + 数据时点**。查不到时点的标「勿引用」。

真实案例：曾有三个"代币化股票市场规模"同时流传（$1B / $3B / $13.4B），
其中 $13.4B 在另一批报道里是"4 月的代币化国债规模"。后经核实是 CoinShares
口径的 9/1 数据，不是串号 —— **但这个核实过程本身就是晨报最高价值的部分**。

### 3. 失败要可见，不要静默
判断层 403 时曾只留一行警告，表现成"管道在跑，其实什么都没产出"。
现在会重试 + 发邮件告警。**任何新增的自动化都要问：它失败时用户会知道吗？**

### 4. 发现自己错了，立即更正
管道曾自己更正过前一天的判断（"$13.4B 疑似串号"→ 核实后撤回）。
这是对的。用户是 PhD，会检查论证，**掩盖错误的代价远大于承认**。

---

# 第八部分：常用命令速查

```bash
cd ~/rwa-signal

# 会话
.venv/bin/python scripts/x_browser.py --status      # 检查登录态
.venv/bin/python scripts/x_browser.py --login       # 弹窗手动登录（仅用户本人）

# 取数与名单
.venv/bin/python scripts/fetch_browser.py                        # 抓全部
.venv/bin/python scripts/fetch_browser.py --accounts A B --per-account 12
.venv/bin/python scripts/vet_accounts.py                         # 体检（只看）
.venv/bin/python scripts/vet_accounts.py --write                 # 体检并写回
.venv/bin/python scripts/follow_list.py --dry-run                # 看待关注清单
.venv/bin/python scripts/follow_list.py --max 8                  # 关注一批

# 定时任务手动触发
bash scripts/cron_runner.sh discover        # 挖新账号并关注
bash scripts/cron_runner.sh like            # 点赞一轮
.venv/bin/python scripts/like_recent.py     # 只看会赞什么（dry-run）
bash scripts/cron_runner.sh digest          # 出晨报并发邮件
bash scripts/cron_runner.sh comment_watch   # 扫机会出草稿
bash scripts/cron_runner.sh status          # 健康检查

# 发布
.venv/bin/python scripts/publish.py --draft <id> --pick A        # dry-run
.venv/bin/python scripts/publish.py --draft <id> --pick A --yes  # 真发

# 推送
.venv/bin/python scripts/notify.py --send-file <file> --subject "..."
.venv/bin/python scripts/notify.py --test

# 排障
tail -50 data/cron.log                       # 第一站
nc -z 127.0.0.1 7890                         # 代理通不通（403 的头号嫌疑）
launchctl list | grep rwasignal              # 定时任务状态
pkill -f "user-data-dir=$HOME/rwa-signal/state/browser-profile"   # 清孤儿进程
```

## 凭据在哪（都不在文件里）

| 用途 | 位置 |
|---|---|
| X 登录态 | `state/browser-profile/`（Playwright profile） |
| 邮件推送 | macOS Keychain，service `rwa-signal-resend-api-key` |
| GitHub | 用户提供 PAT，**不要写进任何文件** |

**永远不要把凭据写进文件、commit、或对话。**

---

# 第九部分：现在的待办

1. **发出第一条内容** —— 发送链路至今零验证，这是最大缺口
2. `stats.py` 拉不到已发帖的互动数据（未实现）
3. `kol` 层 7 人中 6 人是发行方高管，非完全独立信源，做收敛判定时要折算
4. 用户的 GitHub PAT 曾进过 transcript，她表示案子结束后自行轮换（**勿再提醒**）

---

# 附：给用户回话的风格

- **中文**。直接，不铺垫
- **不要邀功**。她对"宣布完成"很反感，只报可验证的事实
- **发现自己的错误就直说**，并给更正
- **不确定就说不确定**，不要用漂亮话掩盖
- 她打断过冗长的确认对话 —— **给简短方案然后执行**，不要列一堆选项让她选
