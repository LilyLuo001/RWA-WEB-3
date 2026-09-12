# HANDOFF — 给下一个接手的 AI

> 最后更新：2026-09-12（经过一次完整审计与重建）。读完即可接手。
> 配套：README.md（架构）、prompts/（判断层规范）、scripts/ 的 docstring。

## 这是什么

用户 Lily（**top program 经济学博士**）要做 RWA/Web3 内容账号。
五个原始诉求：找大V、关注+神评论、热点追踪推送、AI 辅助发布、冷账号曝光。
**零预算：$0，不用任何付费 API。** 浏览器会话自动化代替 X API。

账号：`@lilysharp88`（自动探测写入 settings.yaml）。邮箱 lilysharp88@gmail.com。
仓库：github.com/LilyLuo001/RWA-WEB-3（**public**，所以 transcripts 不入库）。

## 定位（决定一切产出的质量）

见 `config/settings.yaml: identity`。核心：
> 把代币化当作一个**市场设计问题**来研究，而不是当作一个赛道来喊单。

econ PhD 的比较优势是**分析框架**，不是信息速度。所以产出的价值不在"最快知道"，
在"给出别人没有的切入角度"。`identity.frameworks` 有 7 个可调用框架，
`identity.live_hooks` 有 4 个已识别的现成切口（law of one price 失效、
流动性收益未兑现、权利分离、持仓分布）。

## 每日自动流程（launchd，不是 cron）

| 任务 | 频率 | 内容 |
|---|---|---|
| fetch | 20 分钟 | 抓 27 个名单账号 |
| comment_watch | 2 小时 | 抓取 + `claude -p` 出草稿，≥72 分发邮件 |
| digest | 07:05 | 抓取 + `claude -p` 出四分区晨报并发邮件 |
| follow | 09:30 | 关注名单里未关注的（≤8/批） |
| status | 23:00 | 会话健康 + 额度统计 |

plist 在 `launchd/`，安装方法见 `launchd/README.md`。
**为什么不用 cron**：macOS 睡眠时 cron 不补跑，launchd 唤醒后会补。

## 关键决策记录（为什么是现在这样）

1. **X API 弃用**：2026 起全面按量付费（$0.005/条读取，需预充值）。
   零预算下只能走浏览器会话，用户手动登录一次，profile 存 `state/`。
2. **不做全自动点赞/评论**：架构是草稿确认制。限速闸门在代码里
   （`common.check_safety`），第 1 周每日回复上限 3，按周放开。
3. **判断层用 `claude -p` 无头调用**，不写死成 Python。
   第一版的 cron digest 分支只 `echo` 一行，等于晨报永远不会产生 —— 别重犯。
4. **发行方官方号 ≠ 独立信源**。tier `issuer`（Ondo/Securitize/centrifuge/
   maplefinance）发自家产品是广告，**不计入叙事收敛**。
   第 1 期晨报就是把 Ondo 宣传 Ondo Stocks 写成了"收敛信号"。
5. **学术层必须主动检索，不能等推送**。实测：LVR 论文作者 @ciamac 的 feed
   在发纽约房产税，@tim_roughgarden 发共识协议课程，@nberpubs 零相关。
   严肃学术工作在工作论文和央行报告里，不在推文里。

## 踩过的坑（重犯代价很高）

- **中文界面**：关注按钮是 `button[data-testid$="-follow"]`，位于
  `div[data-testid="placementTracking"]` 内；已关注文字是「正在关注」不是「关注中」
- **Z 后缀时间戳**：浏览器抓的 `created_at` 是 `...Z`，Python 3.10 的
  `fromisoformat` 不认 → 曾导致 `read_raw` 静默丢弃全部数据。已修（`parse_ts`）
- **浏览器 profile 互斥**：Playwright persistent profile 同时只能一个进程开。
  撞上时 Playwright 报的是「会话失效」——**会误导人去重新登录**。
  已加 `acquire_lock` + `reap_orphans`
- **推串取 id**：`send_post` 发完后浏览器停在 `/compose/port`，URL 里没有
  `/status/`。必须回自己主页取最新帖 id（`_newest_own_post_id`）
- **纯文本邮件**：markdown 表格在 text/plain 里是一堆竖线。已加 `md_to_html`
- **名单体检的词表**：用产业黑话筛学术账号会把 BIS 判成跑题；
  用学术词表筛 SEC 会从 89% 掉到 22%。acad/reg 用**并集**
- **网络**：本机走 Clash（127.0.0.1:7890），pip 用清华镜像稳定

## 现状

**已验证可用**
- 27 个账号全部关注（上 X 逐个核对过）
- 四分区晨报自动产出并发邮件（09-12 那份是全自动的）
- comment_watch 自动产出带来源的草稿 + 告警邮件
- `vet_accounts.py` 名单体检（tier-aware）

**从未验证 —— 这是最大的缺口**
- **一条内容都没发过**。`data/audit.jsonl` 只有 `dry_run:2` + `follow:27`
- `publish.py` 的浏览器发送通道、`quote_post`、`send_thread`
  全部只过了编译和 dry-run，**没有一次真实发送**
- 用户原始需求 #2（评论）#4（帮我发）#5（冷启动曝光）因此都还是 0

**下一个接手的人第一件该做的事**：
挑一条高分草稿，走完整流程发出去一次，验证发送链路。
在那之前，这个系统只有情报功能，没有发布功能。

## 未决

- PAT 泄露进 transcript，用户表示案子结束后自行轮换（已知悉，勿再提醒）
- `stats.py` 拉不到已发帖的互动数据（需要读取配额或浏览器抓取，未实现）
- kol 层 7 人中 6 人是发行方高管，非完全独立信源，做收敛判定时要折算
