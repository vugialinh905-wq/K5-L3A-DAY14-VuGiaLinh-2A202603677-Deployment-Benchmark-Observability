# Deployment Information

## Public URL
https://day14-agent-2ps9.onrender.com

## Platform
Render (Blueprint từ `06-lab-complete/render.yaml`, nhánh `lab/day14-part6`): một web service Docker `day14-agent` và một Key Value (Redis) `day14-redis`.

## Test Commands

`BASE` là URL public ở trên. `AGENT_API_KEY` là key Render tự sinh (`generateValue: true`), lấy ở Dashboard → service → Environment; **không ghi key vào repo**.

### 1. Health check
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# 200   body: {"status":"ok","environment":"production"}
```

### 2. Readiness (kết nối Redis)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# 200   body: {"status":"ready"}
```

### 3. Không có API key → bị từ chối
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
# 401   body: {"detail":"Invalid or missing API key"}
```

### 4. Có API key → trả lời
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# 200
```

Kết quả đã chạy ngày 2026-11-25: lệnh 1, 2, 3, 4 trả lần lượt **200, 200, 401, 200**.

## Environment Variables Set (trên Render, không ghi giá trị vào repo)
- `AGENT_API_KEY` — Render tự sinh (`generateValue: true`)
- `REDIS_URL` — lấy từ Key Value `day14-redis` (`fromService` / `connectionString`)
- `ENVIRONMENT=production`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `PORT` — do Render cấp; Dockerfile lắng nghe theo `${PORT}`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
