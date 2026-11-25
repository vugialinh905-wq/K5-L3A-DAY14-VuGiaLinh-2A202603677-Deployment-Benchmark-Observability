# Day 14 Lab — Mission Answers

> Môi trường chạy: Windows 11 + WSL2 (Ubuntu 26.04, Python 3.14) + Docker Desktop 4.100.1 (Docker Engine 29.9.3).
> Mọi output bên dưới được chạy thật trên máy này ngày 2026-11-25.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

1. **API key và DB password hard-code trong code** (`OPENAI_API_KEY = "sk-..."`, `DATABASE_URL = "postgresql://admin:password123@..."`). Push lên GitHub là lộ secret ngay.
2. **Không có config management**: `DEBUG = True`, `MAX_TOKENS = 500` viết cứng, không đọc từ environment nên không đổi được giữa dev/staging/prod.
3. **Dùng `print()` thay vì logging có cấu trúc**, và còn **in cả secret ra log** (`print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`). Khi chạy thật, log của develop chứa đúng chuỗi `sk-hardcoded-fake-key-never-do-this`.
4. **Không có health check**: gọi `GET /health` trả **404**, platform không biết khi nào cần restart container.
5. **Port và host cố định**: `host="localhost"`, `port=8000`. `localhost` không nhận kết nối từ bên ngoài container; Railway/Render cấp port qua biến `PORT`.
6. **`reload=True`** (chế độ debug reload) khi chạy production.
7. **Không có graceful shutdown** (không có lifespan, không xử lý SIGTERM).
8. **Câu hỏi nhận qua query string** (`/ask?question=...`) không validate, nội dung câu hỏi lọt vào URL và access log.

### Exercise 1.2: Chạy bản develop

```
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -o /dev/null -w "%{http_code}" http://localhost:8000/health
404
```

Nó chạy được, nhưng không production-ready vì các lý do ở 1.1.

### Exercise 1.3: So sánh develop và production

| Feature | Develop (basic) | Production (advanced) | Tại sao quan trọng? |
|---------|-----------------|-----------------------|---------------------|
| Config | Hard-code trong code | Đọc từ env vars qua `config.py` (`Settings`), có `validate()` fail-fast | Đổi môi trường không cần sửa code, secret không nằm trong git |
| Secrets | Key nằm trong source, in ra log | `OPENAI_API_KEY`, `AGENT_API_KEY` lấy từ env, không log | Tránh lộ secret qua repo và log |
| Health check | Không có (`/health` → 404) | `GET /health` (liveness) và `GET /ready` (readiness) | Platform tự restart khi chết, load balancer chỉ route vào instance đã sẵn sàng |
| Logging | `print()` | JSON log (`{"event": ..., ...}`), không log secret | Log aggregator (Datadog, Loki) parse được, tìm kiếm dễ |
| Shutdown | Đột ngột | Graceful: lifespan, `is_ready=False` rồi dọn dẹp, bắt SIGTERM | Request đang chạy không bị cắt khi deploy/scale |
| Host / Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên Railway/Render |
| Debug reload | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Reload tốn tài nguyên và không an toàn ở production |
| CORS | Không | Giới hạn origin theo config | Chặn trình duyệt lạ gọi API |
| Input | Query param, không validate | Body JSON, trả 422 khi thiếu `question` | Kiểm soát đầu vào |

Output chạy bản production:

```
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":3.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:13:27+00:00"}
$ curl http://localhost:8000/ready
{"ready":true}
```

### Checkpoint 1
- Hardcode secret nguy hiểm vì nó đi theo git history, ai có quyền đọc repo đều thấy; xoá file không đủ, phải đổi key.
- Dùng environment variables theo 12-factor.
- `/health` cho platform biết process còn sống; `/ready` cho load balancer biết có nên đưa traffic vào.
- Graceful shutdown: nhận SIGTERM, ngừng nhận request mới, xử lý xong request đang chạy rồi mới thoát.

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (bản đầy đủ, khoảng 1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Vì sao COPY `requirements.txt` trước:** tận dụng Docker layer cache. Layer cài dependencies chỉ build lại khi `requirements.txt` đổi; sửa code `app.py` không làm cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định, dễ bị ghi đè khi chạy `docker run image <lệnh khác>`. `ENTRYPOINT` là chương trình cố định của container, tham số truyền thêm khi `docker run` được nối vào sau nó. Thường dùng ENTRYPOINT cho chương trình chính và CMD cho tham số mặc định.

### Exercise 2.2: Build và run

```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=What+is+Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ docker images my-agent:develop
REPOSITORY:TAG      SIZE
my-agent:develop    1.67GB     (1,667,788,058 bytes)
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (builder):** `python:3.11-slim` + `gcc`, `libpq-dev`, rồi `pip install --user` vào `/root/.local`. Stage này cần công cụ build.
- **Stage 2 (runtime):** `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` và mã nguồn, tạo user non-root `appuser`, có `HEALTHCHECK`, chạy `uvicorn --workers 2`.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc, apt cache và build tools của stage 1; base `slim` thay cho bản đầy đủ.

```
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
$ docker images my-agent
my-agent:advanced   240MB    (239,815,338 bytes)
my-agent:develop    1.67GB   (1,667,788,058 bytes)
```

- Develop: **1668 MB**
- Production (advanced): **240 MB**
- Chênh lệch: giảm khoảng **85,6%** (nhỏ hơn khoảng 7 lần).

Kiểm tra container advanced: `GET /health` → `{"status":"ok",...,"version":"2.0.0"}`, `docker exec ... id` → `uid=999(appuser)` (không chạy root), `docker inspect` → `health=healthy`.

### Exercise 2.4: Docker Compose stack

Các service (`02-docker/production/docker-compose.yml`):

```
Client ──> nginx:80 ──> agent:8000 ──> redis:6379
                              └──────> qdrant:6333
         (tất cả nằm trong network `internal`; chỉ nginx publish port 80/443)
```

- **nginx**: reverse proxy + load balancer + rate limit (10 req/s/IP, trả 429), security headers.
- **agent**: FastAPI, không publish port ra ngoài, chỉ nhận qua nginx.
- **redis**: cache session và rate limiting. **qdrant**: vector DB.
- Agent `depends_on` redis và qdrant với `condition: service_healthy`, nên chỉ khởi động khi hai service đó healthy. Các service nói chuyện với nhau bằng tên service qua DNS của Docker network.

```
$ docker compose -p k5-day14-docker up -d --build
agent    running  healthy
nginx    running  0.0.0.0:80->80
qdrant   running  healthy
redis    running  healthy

$ curl http://localhost/health
{"status":"ok","uptime_seconds":7.5,"version":"2.0.0",...}   HTTP 200
$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}   HTTP 200
$ curl http://localhost:8000/health      # gọi thẳng agent, không qua nginx
(không kết nối được — đúng thiết kế, agent không expose port)
```

(Ghi chú: compose cần file `.env.local`, repo không có nên mình tạo file rỗng bằng `touch`; file này nằm trong `.gitignore`.)

### Checkpoint 2
- Đã hiểu cấu trúc Dockerfile, lợi ích multi-stage (nhỏ hơn, an toàn hơn), Compose điều phối nhiều service.
- Debug container: `docker logs <id>`, `docker exec -it <id> sh`, `docker inspect`.

---

## Part 3: Cloud Deployment

> **Trạng thái:** phần deploy thật (Exercise 3.1 Railway / 3.2 Render) **chưa thực hiện**: cần tài khoản và đăng nhập nền tảng. Các mục dưới đây đánh dấu rõ cái gì đã làm, cái gì còn thiếu. Xem thêm `DEPLOYMENT.md`.

### Exercise 3.1 / 3.2: Deploy

- Config sẵn sàng deploy cho agent Part 6: `06-lab-complete/railway.toml` và `06-lab-complete/render.yaml` (đã PASS tiêu chí 12 của script chấm).
- **URL public:** _chưa có — cần điền sau khi deploy_
- **Screenshot:** _chưa có — `screenshots/dashboard.png`, `running.png`, `test.png`_

### So sánh `railway.toml` và `render.yaml` (Exercise 3.2)

| | Railway (`railway.toml`) | Render (`render.yaml`) |
|---|---|---|
| Định dạng | TOML, chỉ mô tả **một service** (build + deploy) | YAML Blueprint, mô tả **cả hạ tầng** (nhiều service, Redis…) |
| Build | `builder = "NIXPACKS"` hoặc `"DOCKERFILE"` | `runtime: python` + `buildCommand`, hoặc `runtime: docker` |
| Start | `startCommand` dùng `$PORT` | `startCommand` dùng `$PORT` |
| Health check | `healthcheckPath`, `healthcheckTimeout` | `healthCheckPath` |
| Restart | `restartPolicyType` / `restartPolicyMaxRetries` | Do nền tảng tự quản lý |
| Redis | Thêm service Redis trên dashboard rồi gắn `REDIS_URL` | Khai báo ngay trong file (`type: redis` / `keyvalue`) |
| Secret | Đặt qua dashboard hoặc `railway variables set` | `sync: false` (nhập tay) hoặc `generateValue: true` (tự sinh) |
| Cách deploy | `railway up` từ CLI | Push GitHub, rồi New → Blueprint |

### Exercise 3.3: Cloud Run — mô tả pipeline CI/CD

`cloudbuild.yaml` chạy khi push lên nhánh main gồm 4 bước tuần tự: (1) chạy `pytest` trong container Python, lỗi test thì dừng; (2) build Docker image gắn tag `$COMMIT_SHA` và `latest`, dùng `--cache-from` để tận dụng layer cache; (3) push image lên Container Registry; (4) `gcloud run deploy` lên Cloud Run vùng `asia-southeast1` với `min-instances=1`, `max-instances=10`, 512Mi RAM, secret `OPENAI_API_KEY` lấy từ Secret Manager. `service.yaml` là định nghĩa Cloud Run dạng IaC: autoscale 1–10 instance, mỗi instance tối đa 80 request đồng thời, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`, secret lấy từ Secret Manager bằng `secretKeyRef`.

---

## Part 4: API Security

### Exercise 4.1: API key authentication (`04-api-gateway/develop`)

- **API key được check ở đâu:** hàm `verify_api_key` (dependency `Depends(verify_api_key)` trên `/ask`), đọc header `X-API-Key` và so với biến môi trường `AGENT_API_KEY`.
- **Sai key:** thiếu key → 401, sai key → 403 (bản develop tách hai trường hợp; bản Part 6 gộp cả hai về 401 theo hợp đồng của script chấm).
- **Rotate key:** đổi giá trị biến môi trường `AGENT_API_KEY` rồi restart/redeploy; không cần sửa code.

```
$ AGENT_API_KEY=secret-key-123 python app.py
no key      -> {"detail":"Missing API key. Include header: X-API-Key: <your-key>"} [401]
wrong key   -> {"detail":"Invalid API key."} [403]
correct key -> {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock)..."} [200]
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production`)

Flow: `POST /auth/token` với username/password → server ký JWT (HS256, hết hạn 60 phút, chứa `sub`, `role`, `iat`, `exp`) → client gửi `Authorization: Bearer <token>` → server verify chữ ký, không cần tra database (stateless). Lưu ý: đường dẫn lấy token là `/auth/token` và tài khoản demo là `student / demo123`, không phải `/token` và `admin / secret` như ghi trong `CODE_LAB.md`.

```
no token   -> {"detail":"Authentication required. Include: Authorization: Bearer <token>"} [401]
bad login  -> {"detail":"Invalid credentials"} [401]          (admin / secret)
token      -> eyJhbGciOiJIUzI1NiIs...   (đã che phần còn lại)
with token -> {"question":"Explain JWT","answer":"Agent đang hoạt động tốt! ...","usage":{"requests_remaining":9,...}} [200]
```

### Exercise 4.3: Rate limiting

- **Algorithm:** Sliding Window Counter (mỗi user một `deque` timestamp trong 60 giây; xoá timestamp cũ rồi đếm).
- **Limit:** user thường **10 request/phút**; admin **100 request/phút**.
- **Bypass cho admin:** không bỏ hẳn limit mà dùng `rate_limiter_admin` (100/phút) khi `role == "admin"`.
- Hạn chế: state nằm trong RAM của từng process, nên khi scale nhiều instance mỗi instance đếm riêng. Bản Part 6 chuyển sang Redis để khắc phục.

Gọi liên tục sau khi đã dùng 1 request (user `student`): 9 request tiếp theo → 200, từ request thứ 10 trở đi → **429**.

```
call 1..9  -> 200
call 10..14 -> 429
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
```

Tài khoản `teacher` (admin): 15 request liên tiếp đều trả 200.

### Exercise 4.4: Cost guard — cách mình làm

Cài đặt thật nằm ở `06-lab-complete/app/cost_guard.py`:

- Mỗi request ghi chi phí vào Redis bằng `INCRBYFLOAT` vào khoá theo ngày `cost:YYYY-MM-DD`, kèm `EXPIRE` 2 ngày. `INCRBYFLOAT` là atomic nên nhiều worker/instance cộng dồn an toàn.
- Chi phí = `input_tokens/1000 × 0.00015 + output_tokens/1000 × 0.0006` (giá gpt-4o-mini; token ước lượng ≈ 1.3 × số từ vì mock LLM không trả usage thật).
- `check_budget()` chạy **trước** khi gọi LLM: nếu tổng đã chi `>= DAILY_BUDGET_USD` thì trả **402**; Redis lỗi thì trả 503 (fail closed).
- Khác với lời giải gợi ý trong `CODE_LAB.md` (budget $10/tháng theo từng user), bản này theo hợp đồng của `06-lab-complete/README.md`: budget theo ngày, đọc từ biến `DAILY_BUDGET_USD`. Script chấm chạy với budget `0.000001` và nhận 402 ở request thứ 1.

Quan sát thêm ở bản demo `04-api-gateway/production`: trường `usage.budget_remaining_usd` trong response `/ask` thực ra đang trả **chi phí đã dùng** (`usage.total_cost_usd`), không phải số còn lại (ví dụ `1.6e-05` ngay sau request đầu). Đây là lỗi đặt tên trong code mẫu, mình không sửa vì ngoài phạm vi bài.

### Checkpoint 4
- Đã chạy API key auth, JWT, rate limiting, và cài cost guard (Part 6).

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

Code đã có sẵn hai endpoint; mình chạy và kiểm tra:

```
$ curl localhost:8000/health
{"status":"ok","uptime_seconds":3.6,"version":"1.0.0",...,"checks":{"memory":{"status":"ok","used_percent":13.1}}}   [200]
$ curl localhost:8000/ready
{"ready":true,"in_flight_requests":1}   [200]
```

- `/health` (liveness): process còn sống không, kèm kiểm tra bộ nhớ qua `psutil`.
- `/ready` (readiness): trả 503 khi chưa khởi động xong hoặc đang shutdown.

### Exercise 5.2: Graceful shutdown

Gửi 6 request song song rồi `kill -TERM` ngay sau 50 ms:

```
in-flight req 3 -> 200
in-flight req 4 -> 200
in-flight req 2 -> 200
in-flight req 5 -> 000   (không kết nối được)
in-flight req 6 -> 000
in-flight req 1 -> 000
--- server log:
INFO:     Shutting down
INFO:     Waiting for connections to close.
INFO:     Waiting for application shutdown.
🔄 Graceful shutdown initiated...
✅ Shutdown complete
Received signal 15 — uvicorn will handle graceful shutdown
process still alive? no
```

Kết luận có giới hạn: 3 request đã vào server trước SIGTERM **được xử lý xong (200)**, rồi process tắt hẳn. 3 request còn lại trả `000` vì chúng chưa kịp kết nối khi server đã ngừng nhận kết nối mới (đúng hành vi "ngừng nhận request mới"). Điều này khớp định nghĩa graceful shutdown: không cắt request đang chạy, nhưng không nhận thêm request mới.

### Exercise 5.3: Stateless design

Anti-pattern là giữ `conversation_history` trong dict trong RAM: mỗi instance có bộ nhớ riêng, request tiếp theo rơi vào instance khác thì mất history. Bản `05-scaling-reliability/production/app.py` lưu session trong Redis (`session:<id>`, `setex` TTL 3600 giây, giữ tối đa 20 message), nên instance nào cũng đọc được.

### Exercise 5.4: Load balancing

```
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
agent-1, agent-2, agent-3  healthy; redis healthy; nginx :8080

10 request liên tiếp:
req 1 -> instance-7f770a    req 6  -> instance-a093c4
req 2 -> instance-896590    req 7  -> instance-7f770a
req 3 -> instance-a093c4    req 8  -> instance-896590
req 4 -> instance-7f770a    req 9  -> instance-a093c4
req 5 -> instance-896590    req 10 -> instance-7f770a
```

Nginx phân tán round-robin đều trên 3 instance (7f770a → 896590 → a093c4 lặp lại).

### Exercise 5.5: Test stateless

```
$ python test_stateless.py
Session ID: 1db1283c-...
Request 1: [instance-896590]   Request 2: [instance-a093c4]   Request 3: [instance-7f770a]
Request 4: [instance-896590]   Request 5: [instance-a093c4]
Instances used: {'instance-7f770a', 'instance-a093c4', 'instance-896590'}
✅ All requests served despite different instances!
Total messages: 10   (5 user + 5 assistant, đủ cả 5 lượt)
✅ Session history preserved across all instances via Redis!
```

Thử thêm: tạo session, `docker kill` một instance agent, rồi tiếp tục gửi 4 request cùng `session_id`: cả 4 đều **200**, chỉ do 2 instance còn lại phục vụ (Nginx có `proxy_next_upstream`), history vẫn còn, không mất session.

### Checkpoint 5
- Đã chạy health/readiness, kiểm tra graceful shutdown, chứng minh stateless với Redis, load balancing 3 instance bằng Nginx.

---

## Part 6: Final Project — kết quả `check_production_ready.py`

Chạy đầy đủ (có Docker) trong WSL2, Python 3.14. Image build ra **238 MB**, `docker stop` tắt trong **1,0 giây** với exit code 0.

```
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Ghi chú: `requirements.txt` của `06-lab-complete` được đổi từ ghim phiên bản cứng (`pydantic==2.9.0`...) sang khoảng tối thiểu (`pydantic>=2.9.0,<3.0`...) vì Python 3.14 trên máy chạy script không cài được `pydantic==2.9.0` (không có bản dựng sẵn, phải biên dịch Rust). Image Docker vẫn dùng Python 3.11. `check_production_ready.py` không bị sửa.

---

## AI log

Theo `RULES.md`, mọi lần dùng AI cho code Part 6 hoặc câu trả lời đều được ghi ở đây.

| # | Công cụ | Hỏi gì | Nhận được gì | Kiểm tra thế nào |
|---|---------|--------|--------------|------------------|
| 1 | Claude Code (Sonnet 5.5) | Đọc đề lab, tóm tắt rubric và cách nộp | Bản tóm tắt README, RUBRIC, SUBMISSION, CHECKPOINTS, RULES | Đối chiếu với file trong repo |
| 2 | Claude Code | Hoàn thành các TODO của Part 6 trong `06-lab-complete/` | Code `app/*.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` | Chạy `check_production_ready.py` đầy đủ, kết quả PASS 12/12 (dán ở trên) |
| 3 | Claude Code | Sửa lỗi cài thư viện trên Python 3.14 | Nới ghim phiên bản trong `requirements.txt` | Cài lại thành công, script chấm vẫn PASS |
| 4 | Claude Code | Chạy các exercise Part 1–5 và viết `MISSION_ANSWERS.md` | Lệnh chạy, output thật và bản nháp câu trả lời | Output dán trong file là output của lệnh đã chạy trên máy; câu trả lời khái niệm cần tự đọc lại và hiểu trước khi nộp |
