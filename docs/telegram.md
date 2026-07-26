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

## 容器配置确认

```bash
docker exec sportshunter-ai-api env | grep -E '^(TELEGRAM_ENABLED|TELEGRAM_PUSH_ENABLED|CHAT_ID|FREE_PROVIDER_FOOTBALL_LEAGUES)='
```

不要在日志、截图或聊天中公开 `BOT_TOKEN`。
