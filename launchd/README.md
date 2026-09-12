# launchd 定时任务

用 launchd 而不是 cron：**macOS 睡眠时 cron 不会补跑**，7:05 的晨报
如果电脑在睡就永远不会发。launchd 的 StartCalendarInterval 会在唤醒后补跑。

## 安装
```bash
cp launchd/com.rwasignal.*.plist ~/Library/LaunchAgents/
for j in fetch commentwatch digest follow status; do
  launchctl load ~/Library/LaunchAgents/com.rwasignal.$j.plist
done
launchctl list | grep rwasignal   # 确认已注册
```

## 调度
| 任务 | 频率 | 做什么 |
|---|---|---|
| fetch | 每 20 分钟 | 抓名单账号时间线 |
| commentwatch | 每 2 小时 | 抓取 + claude -p 出评论草稿，高分发邮件 |
| digest | 每天 07:05 | 抓取 + claude -p 出晨报并发邮件 |
| follow | 每天 09:30 | 关注名单里还没关注的（每批 ≤8） |
| status | 每天 23:00 | 会话健康检查 + 额度统计 |

## 日志
`data/cron.log`（任务内容）、`data/launchd.log`（launchd 本身的 stdout/stderr）

## 排障
症状「未登录或会话失效」**通常不是真的掉登录**，而是上一轮残留的
chrome-headless-shell 占着 profile。cron_runner.sh 的 reap_orphans 会自动清理；
手动清理：`pkill -f 'user-data-dir=.../state/browser-profile'`
