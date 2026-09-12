# HANDOFF — 给下一个接手的 AI

> 最后更新：2026-09-11 晚。本文档自包含：读完即可接手，无需重读对话。
> 配套：README.md（架构）、各 scripts 的 docstring、prompts/（判断层规范）。

## 这是什么

用户（Lily）要做 RWA/Web3 内容账号增长。五个诉求：找大V、关注+神评论、
热点追踪推送、AI 辅助创作发布、冷账号曝光。**零预算约束：$0，不用任何
付费 API。** 整套系统在本机跑，浏览器会话自动化代替 X API。

## 关键决策记录（为什么是现在这样）

1. **X API 弃用**（2026-09-11 调研）：官方已全面转按量付费（$0.005/条
   读取，预充值制；legacy Basic $200/月仅存续）。零预算下唯一可行路径
   是浏览器会话自动化。Playwright persistent profile，用户手动登录一次。
2. **不做全自动点赞/评论**：X 反自动化风控是真实约束。架构是「草稿确认
   制」——AI 打分+起草，人一键发布。限速闸门在代码里（`common.py:
   check_safety`），周1每天3条回复起按周放开。用户的原始诉求是
   「每一条消息点赞评论」，已明确降级为「高分机会才评论」并解释原因。
3. **判断层（打分/晨报/润色）不写死成 Python**：这是推理问题，由 Claude
   按 `prompts/` 规范执行。取数/发送是机械问题，是 Python。
4. **中文界面坑**：用户 X 是中文界面，按钮文字是「关注」/「正在关注」，
   不是英文。选择器用 `button[data-testid$="-follow"]`（profile header 的
   `div[data-testid="placementTracking"]` 容器内）。
5. **Z 后缀坑**：浏览器抓的 `created_at` 是 `...Z`，Python 3.10
   `fromisoformat` 不认 → `read_raw` 曾静默丢弃全部 browser 数据。
   已修（`fetch_posts.py: parse_ts`）。
6. **网络坑**：本机走 Clash 代理（127.0.0.1:7890）。pip 直连 PyPI 偶发
   SSL 断连，用清华镜像 `pypi.tuna.tsinghua.edu.cn` 稳定。登录 X 期间
   提醒用户固定节点，否则出口 IP 一变 X 就弹验证。

## 已完成（截至 2026-09-11 晚）

- [x] 15 个核验账号名单（core 6 / adj 4 / data 2 / zh 3），每条带来源 URL，
      排除记录也有理由。`config/accounts.yaml`
- [x] 浏览器会话：用户已手动登录，headless 复用验证通过
- [x] 关注 8/15（@ThorHartvigsen 抓取 0 条待重试）
- [x] 抓取 135 条真实帖子入库（一天 2 轮，第 2 轮 cron 起）
- [x] cron：fetch 每 20 分钟 / digest 7:00 / 会话检查 23:00
- [x] 第 1 份真实晨报（见 `data/digests/2026-09-11.md`，基于 44 条 72h
      数据）：信号=代币化股票主升期；3 个选题（首选「$3B 与法律裂缝」）
- [x] email 通道（`notify.py`）：**卡在 Gmail 应用密码**，Keychain 未配置
- [x] git 仓库本地就绪（待用户授权远程 push，见下）

## 未完成 / 排队中（按优先级）

1. **Gmail 应用密码**（阻塞 email 推送）：用户去
   myaccount.google.com/apppasswords 生成，然后终端跑：
   `security add-generic-password -a lilysharp88 -s rwa-signal-gmail-app-password -w`
   （会弹安全对话框输密码，不落 transcript）。然后
   `.venv/bin/python scripts/notify.py --test` 验证。
2. **GitHub push**（阻塞远程备份）：用户 SSH key 没绑 GitHub 账号
   （`ssh -T git@github.com` 返回 Permission denied）。需要用户在
   GitHub → Settings → SSH keys 添加 `~/.ssh/id_ed25519.pub`，或改用
   HTTPS + PAT。**注意 memory 里有一条「credential_rotation_owed」——
   之前有 PAT 泄露进 transcript，新 PAT 绝不能贴进对话。**
3. **用户 handle + angle**（阻塞 comment_watch 质量）：填
   `config/settings.yaml` identity 段。angle 是差异化核心——例：
   「从传统金融合规视角拆解 RWA 项目的真实落地障碍」。
4. 关注剩余 7 个账号（明天批次，follow_list.py 直接跑）
5. comment_watch 首跑（数据密度起来后，按 prompts/comment_watch.md）
6. 互动数据回流：stats.py 增强——用浏览器访问已发帖 URL 抓
   public_metrics（audit.jsonl 里有 tweet_id）
7. Thread 发送（x_send.send_thread 已写，未实测）
8. Quote 转发（x_send.quote_post 已写，未实测）——晨报里标记了理想
   目标：Ondo 9/9「华尔街有营业时间」帖
9. 长尾关键词研究 + 中V（5K-50K 粉）名单扩充——借鉴自外部方案
   （见「外部方案对照」）

## 对话记录归档

用户要求把 AI 对话历史也存进 repo（让接手 AI 快速上手）。归档位置：
`transcripts/`。包含本项目全部会话（含本 HANDOFF 的来龙去脉）。
**注意**：transcripts 含用户敏感信息（邮箱），repo 若设为 public 需先
脱敏；建议 private repo。

## 外部方案对照（用户拿来的另一份 AI 方案，已审计）

已吸收：email 推送、cron 轮询频率、Quote 二创截流、Thread 拆解、
长尾关键词 SEO、hashtag ≤2/外链放首评（post_review.md 已有）、
中V优先于超大V 的关注策略。
拒绝：engagement pod（虚假互动网络，连坐封号风险，且「30% 回关率」
是无依据的编造数字）；全自动点赞评论（他们自己也承认会封号）。
他们的 X API 价格信息过时（说 $100/月 Pro——2026 年实际是按量付费）。

## 账号安全红线（不可协商）

- 每日回复 ≤3 条（第 1 周），逐周升到 12
- 点赞 ≤30/天（publish 流程外，x_send.like_post 手动用）
- 任何脚本检测到风控页（BLOCK_MARKERS）立即停止，账号静默 24h
- 用户密码永不进任何文件/transcript；会话 cookie 在
  state/browser-profile/（gitignored）
