# rwa-signal

RWA / Web3 内容账号的监听—信号—草稿—发布管道。**零预算版：全部通过
本机浏览器会话自动化，不调用任何付费 API。**

**设计原则：AI 做 95%，你做 5% 的一键确认。**
不做全自动点赞/评论——冷账号被风控是真实约束（浏览器自动化在 X 的 ToS
灰区，平台会检测行为模式）。评论区是稀缺位置，早+准 > 多。限速闸门写在
代码里（`scripts/common.py`），不给"这次特殊"留口子。

## 成本结构

| 项 | 花费 |
|---|---|
| X API | $0（不用——2026 年起官方全面收费，按量计费需预充值，放弃） |
| Playwright + Chromium | $0（已装在 `.venv/`） |
| 判断层（评分/晨报/草稿） | 你已有的 Claude Code 订阅，$0 增量 |

## 四层

| 层 | 做什么 | 工具 |
|---|---|---|
| L1 监听 | 用你的浏览器会话逐个访问名单主页，抓最近帖子入库 | `scripts/fetch_browser.py` |
| L1b 关注 | 分批关注 `accounts.yaml` 名单（每次 ≤8，随机间隔） | `scripts/follow_list.py` |
| L2 信号 | 评论机会打分 / 叙事收敛检测 / 选题 | Claude（`prompts/`） |
| L3 创作 | 你的初稿 → 钩子、结构、发布时机 | Claude（`prompts/post_review.md`） |
| L4 发布 | 回复/发帖/点赞，浏览器 DOM 执行，发送后验证 | `scripts/publish.py` / `scripts/x_send.py` |

判断层交给 Claude 而不是 Python 硬编码——"值不值得回"和"怎么写才不水"
是推理问题。取数和发送是机械问题，所以是 Python。

## 会话模型（代替密码）

**永远不要把 X 密码给任何脚本或对话。**
`x_browser.py --login` 弹出一个可见浏览器，你亲手登录一次（含 2FA）。
会话 cookie 存 `state/browser-profile/`（已 gitignore），之后所有脚本
以无头模式复用。失效时脚本会明确报错要求重新 login，而不是假装成功。

## 目录

```
config/accounts.yaml          监听名单 15 个（已核验，每条带来源）
config/settings.yaml          阈值、限速、定位  ← 需要你填 identity 段
prompts/comment_watch.md      高频评论机会扫描（每 20 分钟一次的机会）
prompts/morning_digest.md     每日晨报（收敛检测 → 选题建议）
prompts/post_review.md        你的初稿优化
scripts/                      取数、关注、发送、统计
data/raw/                     抓到的帖子（jsonl，按天）
data/digests/                 生成的晨报
data/drafts/                  待你确认的评论/帖子草稿
state/                        去重游标、限速计数、浏览器会话
```

## 快速开始（按顺序）

```bash
cd ~/rwa-signal
# ① 一次性登录（弹窗，你亲手输密码）
.venv/bin/python scripts/x_browser.py --login
.venv/bin/python scripts/x_browser.py --status

# ② 分批关注名单（今天 8 个，明天再来一批）
.venv/bin/python scripts/follow_list.py            # --dry-run 可先看清单

# ③ 抓第一批数据
.venv/bin/python scripts/fetch_browser.py

# ④ 在 Claude Code 里说"跑 comment_watch" 或 "出晨报"
#    我按 prompts/ 执行，产出 data/drafts/ + data/digests/

# ⑤ 你确认后一键发布
.venv/bin/python scripts/publish.py --draft <id> --pick A --yes
```

风控处理：任何脚本检测到验证/限流页面会立即停止并提示。账号安静 24h，
手动打开浏览器过一次。若 Chromium 无头模式频繁被 X 拦截，加
`--headed` 或 `--channel chrome`（用系统 Chrome，指纹更自然）。

## 状态

- [x] 骨架、配置 schema、判断层 prompts
- [x] X API 档位调研 → 结论：2026 起全付费（$200/月起或按量充值），零预算弃用
- [x] `accounts.yaml` 填充：15 个核验账号（core 6 / adj 4 / data 2 / zh 3），每条带来源 URL
- [x] L1 浏览器后端：`fetch_browser.py`（复用 canonical schema，换数据源不影响 L2-L4）
- [x] L1b `follow_list.py` + L4 `x_send.py`（回复/发帖/点赞 + 发送验证）
- [x] `publish.py` 双通道：API（将来愿意付费可启用）/ 浏览器（默认），限速闸门共用
- [x] L4 dry-run 回归通过（含中文加权字符校验：31 汉字 = 62/280）
- [x] 浏览器登录完成（2026-09-11，会话有效，headless 复用正常）
- [ ] `settings.yaml: identity.handle` 和 `identity.angle` 待填——angle 决定神评论的差异化，没有它草稿只是通用聪明话
- [x] 首跑闭环（2026-09-11）：关注 8/15 → 抓取 135 条真实帖 → 修了 Z-suffix 时间解析 bug → comment_watch 硬性过滤真跑通（90 分钟窗口内 1 条候选——单次快照薄，cron 密集抓取后自然解决）
