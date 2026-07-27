# Telegram Production Checklist

SportsHunter-AI 的 Telegram 推送由容器环境变量控制。

## 必填配置

```env
TELEGRAM_ENABLED=true
TELEGRAM_PUSH_ENABLED=true
BOT_TOKEN=你的 Bot Token
CHAT_ID=真实用户、群组或频道 chat id
```

`CHAT_ID` 不能填写 Bot 自身 ID。个人聊天需要先用 Telegram 账号给 Bot 发送 `/start`。

## 状态诊断

```bash
curl -sS http://127.0.0.1:8000/api/telegram/status | python3 -m json.tool
```

重点看：

- `health`
- `config.ready`
- `error_code`
- `error`

## 手动测试

固定测试消息：

```bash
curl -sS -X POST http://127.0.0.1:8000/api/telegram/test | python3 -m json.tool
```

今日真实赛程：

```bash
curl -sS -X POST http://127.0.0.1:8000/api/telegram/fixtures/today | python3 -m json.tool
```

今日推荐：

```bash
curl -sS -X POST http://127.0.0.1:8000/api/telegram/recommendations/today | python3 -m json.tool
```

检查是否有新的合适比赛并立即推送：

```bash
curl -sS -X POST http://127.0.0.1:8000/api/telegram/alerts/check | python3 -m json.tool
```

推送内容包含：推荐方向、仓位、比分预测、大小球判断、让球判断、猎手评分和推荐理由。
如果数据源返回真实大小球或让球盘口，推送会展示盘口差值、赔率水位和来源；缺失时才退回规则估算。

## 推送机制

系统不再按固定时间推送今日推荐。Scheduler 会定期检查预测结果，但只有发现新的
`STRONG_BUY`、`BUY` 或 `WATCH` 比赛时才发送 Telegram；已发送过的比赛会记录到
`TELEGRAM_ALERT_ARCHIVE_PATH`，避免重复推送。

```env
TELEGRAM_ALERT_SIGNALS=STRONG_BUY,BUY,WATCH
TELEGRAM_ALERT_INTERVAL_MINUTES=5
TELEGRAM_ALERT_RETENTION_DAYS=7
TELEGRAM_ALERT_ARCHIVE_PATH=reports/telegram_alerts.json
```

## 交互命令机器人

需要互动查询时启动 `telegram_bot` profile：

```bash
docker compose --profile telegram up -d --build telegram_bot
```

机器人支持：

- `/status` 查看 Telegram 配置状态
- `/today` 获取今日真实赛程
- `/recommendations` 获取今日推荐
- `/alerts` 立即检查并推送新的合适比赛
- `/report` 生成并返回自动复盘日报
- `/help` 查看命令列表

`/alerts` 会复用现有推荐筛选和防重复归档逻辑；`/today`、`/recommendations`
直接在当前聊天窗口返回结果。

## 容器配置确认

```bash
docker exec sportshunter-ai-api env | grep -E '^(TELEGRAM_ENABLED|TELEGRAM_PUSH_ENABLED|CHAT_ID|TELEGRAM_ALERT_SIGNALS|TELEGRAM_ALERT_INTERVAL_MINUTES|FREE_PROVIDER_FOOTBALL_LEAGUES)='
```

不要在日志、截图或聊天中公开 `BOT_TOKEN`。
