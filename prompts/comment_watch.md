# comment_watch — 评论机会扫描

由 cron 通过 `claude -p` 无头调用（每 2 小时）。工作目录 `~/rwa-signal`。

## 输入

用 `.venv/bin/python` + `scripts/fetch_posts.py:read_raw(36)` 读最近 36 小时、
`source == "browser"` 的帖子。再读 `state/commented.json`（已处理过的 post_id）
和 `state/quota.json`（今日剩余回复额度）。

没有新帖 → 打印 `WATCH_OK 无新机会` 后结束。**不要编造。**

---

## 关于时间窗口（重要，不要照搬"抢前排"的直觉）

当前架构是逐个轮询 profile 页，**帖子到手时通常已经 1–12 小时**。
`max_post_age_minutes: 90` 在这个架构下几乎永远命中 0 条——不要用它当硬门槛。

**实际可用的判断**：一条 8 小时前、只有 4 条回复的帖子，比一条 1 小时前、
已经 60 条回复的帖子位置好得多。**决定因素是「剩余空位」，不是「新鲜度」。**

超过 36 小时的不看（话题已经过去）。

---

## 硬性过滤（先扔掉绝大多数）

直接丢弃：
- 纯转发、纯图片、纯链接公告、纯价格播报、"gm"
- 与 RWA / 代币化 / 链上金融**无关**的帖子。
  注意 `@BTCdayu` `@ZssBecker` 大量发 meme 币和生活内容，**这些一律跳过**，
  它们在名单里只用于热点检测，不是评论目标
- 已在 `state/commented.json` 里的
- 今日额度已用尽 → 仍然产出草稿，但在输出里标注「额度已满，明天再发」

## 打分（0–100）

- **空位（权重最高）**：必须真的看原帖的现有回复。用浏览器读也行，或从
  `metrics.reply` 数配合帖子年龄估算拥挤度。
  - 回复数少（<10）且话题有深度 → 高分
  - 回复数多但全是附和（"bullish" "great thread"）→ 中高分，因为有质量空位
  - 明显角度都被高质量回复占了 → **丢弃，不要跟风复读**
- **相关度**：与 `identity.niche` / `identity.angle` 的贴合度
- **可增量**：你手上有没有原帖没给的事实/数字/先例。没有 → 低分
- **作者影响力**：按 tier 和实际互动量

低于 62 分不输出。

## 起草

**每个机会 1–2 条草稿**，标注策略：
`信息增量` `补盲区` `重新命名` `压缩` `具体反驳` `结构类比`

**语言**：`data/raw` 里的文本可能是 X 的自动翻译。
`Ondo` `Securitize` `centrifuge` `maplefinance` `arthur0x` `RWA_xyz` 等账号
**原文是英文，草稿必须用英文**。`rwa_btc` `0xNing0x` `BTCdayu` 用中文。

**长度**：英文 ≤240 字符，中文 ≤100 字。

**数字必须核实**：草稿里引用任何数字前，用 WebSearch 核一次一手来源，
并在草稿旁注明来源。**编造数字是最严重的错误**——RWA 圈的人会抓。

### 神评论判定测试
> 这条评论能不能原封不动贴到另一条帖子下面？能 → 水评论，重写。

### 禁止（出现即重写）
赞美/同意（"说得好" "great point" "this"）、复述原帖、只有 emoji、
自我推广、万能聪明话、空洞提问（"你怎么看？"）、**编造数字或先例**。

---

## 输出

### 1. 写草稿文件
每个机会写一个 `data/drafts/YYYY-MM-DD-HHMM-<handle>.json`：
```json
{
  "post_id": "...", "post_url": "https://x.com/<handle>/status/<id>",
  "author": "<handle>", "tier": "...", "score": 74,
  "post_summary": "...", "gap_reason": "为什么还有位置",
  "drafts": [{"label": "A 信息增量", "text": "...", "chars": 180, "sources": ["..."]}],
  "expires_at": "...", 
  "publish_cmd": ".venv/bin/python scripts/publish.py --draft <id> --pick A --yes"
}
```

### 2. 更新 `state/commented.json`
把处理过的 post_id 记进去（含时间戳）。
**不要动 `state/quota.json`** —— 计数只在 `publish.py` 真正发出时增加。

### 3. 高分即时推送
有 ≥72 分的机会时，写一份简报到 `data/drafts/_latest_alert.md`（简洁，
只含机会列表和草稿，不要 JSON），然后：
```
.venv/bin/python scripts/notify.py --send-file data/drafts/_latest_alert.md \
  --subject "⚡ N 个评论机会 · @最高分账号"
```

### 4. stdout 打印
最后打印一行 `WATCH_OK <机会数>` 供 cron 日志核验。

---

## 边界

- **绝不自动发布。** 任何情况下只写草稿。
- 不编造帖子内容、互动数、粉丝数。
- 名单为空时输出 `WATCH_OK 名单未填充` 并结束。
