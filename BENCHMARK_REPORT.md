# Benchmark & Observability Report — Day 14

**Họ tên:** Vũ Gia Linh
**Ngày chạy:** 2026-11-25
**Môi trường:** laptop Windows 11 (Intel Core i5-1145G7, 8 luồng logic, 15,7 GB RAM), WSL2 Ubuntu 26.04 (Python 3.14), Docker Desktop 4.100.1. Mỗi container agent giới hạn 0,5 CPU / 256 MB. Load generator, agent và toàn bộ stack chạy chung một máy nên số tuyệt đối chỉ có giá trị so sánh tương đối.

Số liệu lấy từ: `reports/*.json` (load test và eval), `benchmark-results/*.csv` (Locust), `screenshots/*.png`, và log/trace chạy thật ở mục 4.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency nền của mock LLM khoảng 120–180 ms, nên p95 < 500 ms cho dư địa gấp ~2,5 lần mà người dùng vẫn thấy nhanh. Dùng p95 vì avg che giấu tail (xem 2.2). Ngưỡng alert `AgentHighLatencyP95` đặt lỏng hơn (> 1 s) để tránh báo động giả. |
| Error rate `/ask` | < 2 % | Mock LLM cố tình lỗi ~1 % (503 upstream). 2 % là gấp đôi mức nền, vượt tức là có sự cố thật. Alert (> 5 % trong 1 phút) lỏng hơn SLO. |
| Accuracy trên golden dataset | ≥ 85 % | Khớp job CI ở Exercise 7.3. Sau khi sửa KB, v2 đạt 100 %; ngưỡng 85 % chừa chỗ cho thay đổi nhỏ nhưng vẫn chặn regression lớn, kèm điều kiện không có câu nào regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Mỗi lần chạy 300 request tới agent v2 (cổng 8002, mặc định `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`).

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3,96 | 194,8 | 227,9 | 1716,9 | 1,00 % | PASS |
| 10 | 37,02 | 201,8 | 234,5 | 1682,7 | 0,67 % | PASS |
| 50 | 72,58 | 267,4 | 1428,7 | 1839,3 | 0,67 % | **FAIL** (p95) |
| 100 | 47,12 | 668,9 | 4135,9 | 4533,3 | 1,33 % | **FAIL** (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency. Từ 1 lên 10 RPS tăng khoảng 9,3 lần (gần tuyến tính vì mỗi request chỉ chờ LLM giả lập ~200 ms, các request chồng lên nhau). Từ 10 lên 50 chỉ tăng thêm 2 lần và p95 vọt từ 234,5 lên 1428,7 ms: agent bắt đầu bão hòa, request xếp hàng chờ trong một process uvicorn duy nhất. Ở concurrency 100 RPS còn **giảm** (72,6 xuống 47,1) và p95 lên 4,1 s, tức là quá tải, thêm tải chỉ làm tăng độ trễ. Lưu ý: mỗi lần chỉ có 300 request (6–8 giây ở mức tải cao) nên p95/p99 ở mức 50 và 100 chịu ảnh hưởng của giai đoạn khởi động; mình cũng chưa profile để chỉ ra chính xác nút thắt (CPU của agent hay của chính client load_test chạy cùng máy).

### 2.2 Tail latency (concurrency 20)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 192,8 | 222,2 | 244,8 |
| 0.03 (mặc định) | 222,3 | 255,0 | 1680,7 |
| 0.1 | 361,2 | 1698,2 | 1718,3 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Chỉ số nhạy nhất với request chậm là **p99**: chỉ với 3 % request chậm, avg tăng 15 % (192,8 lên 222,3) nhưng p99 tăng khoảng 6,9 lần (244,8 lên 1680,7). Khi tỉ lệ chậm lên 10 % thì cả p95 cũng nhảy vọt (222,2 lên 1698,2) và vi phạm SLO p95 < 500 ms, trong khi avg (361,2) vẫn "trông chấp nhận được". Vì vậy SLO không nên đặt theo average: avg bị kéo bởi số đông request nhanh nên che mất nhóm người dùng gặp độ trễ ~1,7 s, còn percentile phản ánh đúng trải nghiệm của nhóm đó.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4,3 % (1/23) | 91,3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 57,4 | 109,0 | 113,7 |
| Tổng cost (USD) | 0,000408 | 0,000760 | 0,000790 |
| Cost / câu đúng (USD) | 0,00040815 | 0,00003619 | 0,00003436 |
| Quality gate | FAIL (ngưỡng 80 %) | PASS (ngưỡng 80 %, baseline v1) | PASS (ngưỡng 100 %, baseline v2, 0 regression) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách sửa** (chỉ sửa `KNOWLEDGE_BASE` trong `utils/mock_llm.py`, không đụng `golden_dataset.jsonl` hay đáp án):

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm tài liệu kích hoạt bởi `hpa` / `kubernetes` / `autoscal`: "Kubernetes HPA scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi." |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu kích hoạt bởi `jwt`: "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database." |

Chỉ hai câu hỏi này chứa các từ khóa mới nên không câu nào bị ảnh hưởng: eval sau khi sửa báo 2 câu được cải thiện, 0 regression. Mình chép cùng thay đổi sang `production/utils/mock_llm.py` để stack Docker dùng cùng dữ liệu.

**Quality gate:** chạy eval v1 với `--baseline reports/eval_v2.json` cho 20 câu regression và **exit code 1**. Job CI nằm ở `.github/workflows/eval.yml` (chạy trên `pull_request`, khởi động agent v2 với `MOCK_ERROR_RATE=0`, rồi chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`). Mình mô phỏng đúng các lệnh đó trên máy: agent v2 đạt 100 % và job thoát **exit code 0**, agent v1 đạt 4,3 % và job thoát **exit code 1**, nên job fail và pull request không merge được (khi bật "Require status checks" trong branch protection). Mình chưa chạy workflow trên GitHub Actions thật.

**Trade-off chất lượng / chi phí / latency (v1 so với v2):** v2 dùng nhiều token hơn khoảng 1,9 lần (109,0 so với 57,4 token/câu) và p95 eval chậm hơn một chút (206,1 so với 188,6 ms) do thêm bước retrieval, nhưng accuracy từ 4,3 % lên 91,3 %. Chi phí trên mỗi câu trả lời **đúng** của v2 rẻ hơn v1 khoảng 11 lần (0,0000362 so với 0,000408 USD) vì v1 gần như không trả lời đúng câu nào. Chi phí tăng và latency tăng nhẹ là đáng đổi.

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability`: agent x2 + Nginx + Prometheus + Grafana + Jaeger + Locust (30 user trong các thí nghiệm). `promtool test rules` cho alert rules báo SUCCESS.

Khi dựng stack lần đầu, container agent crash liên tục (`ModuleNotFoundError: No module named 'uvicorn'`) vì Dockerfile ở `production/` thiếu `ENV PYTHONUSERBASE=/home/agent/.local`: gói cài bằng `pip --user` ở stage builder nhưng user non-root không tìm thấy. Mình thêm dòng đó vào `06-lab-complete/benchmark-observability/production/Dockerfile` rồi chạy lại. Kết quả Locust của lần crash (100 % lỗi 502) đã bị xóa, không dùng.

### 4.1 Screenshot

- [x] Dashboard Grafana khi có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger: [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 3 alert đang firing: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

Các ảnh này do Chrome chạy ẩn chụp tự động từ chính stack chạy trên máy này (xem AI log trong `MISSION_ANSWERS.md`).

### 4.2 Thí nghiệm "phá hệ thống"

Thời gian đo từ lúc `docker compose up` áp dụng thay đổi xong (T0) đến lần đầu Prometheus báo `firing`, kiểm tra mỗi 5 giây nên có sai số khoảng ±5 giây. Locust giữ 30 user suốt các thí nghiệm.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 82 s | Error rate (stat), Requests/s theo status code (503 tăng) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 138 s | Latency /ask p50/p95/p99/avg (p95, p99 vượt 1 s, avg tăng ít hơn) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 138 s (xem lưu ý) | Cost burn rate (USD/giờ) lên 16,06 USD/giờ |
| D | `docker pause` 1 instance | `AgentInstanceDown` | 41 s | Instances up (giảm còn 1) |
| E | `AGENT_VERSION=v1` | không có alert nào sau 150 s | — | Bảng "Phiên bản đang chạy" (2 instance đổi sang v1) |

**Lưu ý với C:** ngưỡng 2 USD/giờ thấp hơn chi phí của chính tải 30 user trên model nhỏ: lúc đo baseline, burn rate đã là 3,22 USD/giờ và `LLMCostBurnRateHigh` đang firing, nên alert này không chỉ phản ánh việc đổi model. Con số 138 s chỉ mang tính tham khảo. Trước khi đổi sang model lớn alert đã về trạng thái không firing; burn rate sau khi đổi là 16,06 USD/giờ.

**Lưu ý với D:** tỉ lệ 5xx do chính agent báo trong thí nghiệm này là 1,15 % (xấp xỉ mức lỗi nền 1 %), tức là panel Error rate **không** đỏ dù một instance đã ngừng trả lời; request tới instance bị pause timeout ở Nginx nên agent không đếm được.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Metric hạ tầng (latency, lỗi, CPU) chỉ cho biết hệ thống có *chạy* hay không, không cho biết câu trả lời có *đúng* không: v1 vẫn trả 200 nhanh, nhưng accuracy là 4,3 %. Để bắt loại sự cố này cần giám sát chất lượng: (1) chạy eval trên golden dataset định kỳ hoặc trong CI/CD và trước mỗi lần deploy, so với baseline và chặn nếu regression; (2) với phiên bản đã chạy thật, cho một synthetic check chạy câu hỏi mẫu có đáp án đã biết và alert khi sai; (3) lấy mẫu một phần traffic thật chấm bằng LLM-as-judge hoặc so với đáp án chuẩn; (4) thu thập phản hồi người dùng (thumbs down, khiếu nại); (5) có metric theo dõi phiên bản đang chạy (như bảng version trong dashboard) để biết nhầm phiên bản.

### 4.3 Debug bằng trace

Chọn một request chậm thật gửi sau khi stack chạy bình thường (mặc định `MOCK_SLOW_RATE=0.03`, request thứ 6 trong loop gửi thử):

- `trace_id`: `a7f7310d22eedf8c118f69271a011854`
- Tổng thời gian: 1694,9 ms (span gốc `POST /ask`; client đo 1699 ms)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (1668,4 ms, khoảng 98,4 % tổng thời gian). Còn lại: `agent.retrieve_context` 24,3 ms (khoảng 1,4 %), phần còn lại là overhead của `agent.run`. Tức là chậm do lời gọi LLM, không phải code của agent.
- Dòng log tương ứng (grep theo `trace_id` trong log container agent):

```json
{"ts": "2026-11-25T09:35:22.445494+00:00", "level": "INFO", "service": "observable-agent", "instance": "a2e4cc844e96", "event": "llm_call", "trace_id": "a7f7310d22eedf8c118f69271a011854", "span_id": "9bbdad2a2dd1483a", "request_id": "f1938f30f0d1", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 91, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1667.5}
{"ts": "2026-11-25T09:35:22.446011+00:00", "level": "INFO", "service": "observable-agent", "instance": "a2e4cc844e96", "event": "http_request", "trace_id": "a7f7310d22eedf8c118f69271a011854", "span_id": "9bbdad2a2dd1483a", "request_id": "f1938f30f0d1", "method": "POST", "route": "/ask", "status": 200, "ms": 1694.2}
```

**Từ dòng log `llm_error` sang trace (Exercise 7.5, bước 4):** chạy `docker compose logs agent | grep llm_error | head -1` được:

```json
{"ts": "2026-11-25T10:11:50.222523+00:00", "level": "INFO", "service": "observable-agent", "instance": "f297426292c8", "event": "llm_error", "trace_id": "6f08e7c0252e3cb395516eca7a07fae9", "span_id": "027f95b72e085f17", "request_id": "5c3a4888fe06", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

Tìm lại `trace_id` `6f08e7c0252e3cb395516eca7a07fae9` trong Jaeger (qua API của Jaeger) thì thấy đúng request đó: `POST /ask` 142,0 ms và các span `agent.run`, `chat mock-llm-small` đều có `status_code=2` (lỗi). Hai span `agent.run` và `chat mock-llm-small` có event `exception` với `exception.type = utils.mock_llm.LLMError` và `exception.message = "Upstream LLM error: 503 Service Unavailable (mock)"`, khớp nội dung dòng log. Span `chat` mất 91,8 ms rồi lỗi, `agent.retrieve_context` 23,7 ms không lỗi, tức là lỗi xảy ra ở lời gọi LLM, không phải ở retrieval.

Log `llm_ms: 1667.5` (của request chậm ở trên) khớp với span `chat mock-llm-small` (1668,4 ms) trong Jaeger.

Trace trong ảnh `jaeger-slow-trace.png` chính là trace này. Ảnh `jaeger-error-trace.png` là trace `54cb23ab40b88c2467dcf37762f4e0a3` (thí nghiệm A, 921,9 ms, `POST /ask` trả 503, span `chat mock-llm-small` có event `exception`).

### 4.4 Exercise 7.1 — đọc metrics của agent

Chạy agent v2 (`AGENT_VERSION=v2 PORT=8002 python app.py`), gọi `/ask` rồi xem `/metrics`.

**Một ví dụ cho mỗi loại metric** (trích từ output `/metrics`):

| Loại | Ví dụ | Vì sao thuộc loại này |
|---|---|---|
| Counter | `http_requests_total{method="POST",route="/ask",status="200"} 3.0` | Chỉ tăng, đếm số request; dùng với `rate()` |
| Gauge | `agent_in_flight_requests 0.0` | Lên xuống theo số request đang xử lý |
| Histogram | `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 2.0` | Chia latency vào các bucket để tính percentile bằng `histogram_quantile()` |

**Câu hỏi: nếu dùng URL thật (`request.url.path`) thay cho `route.path` làm label `route` thì chuyện gì xảy ra khi bot quét hàng nghìn URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`...)?** Mỗi URL khác nhau là một giá trị label khác nhau, tức là một time series mới cho mỗi metric có label đó (counter và mọi bucket của histogram). Hàng nghìn URL lạ sinh hàng nghìn series (cardinality bùng nổ), Prometheus tốn RAM và disk, truy vấn chậm, có thể bị OOM. Thêm nữa kẻ tấn công có thể cố ý quét để làm hỏng hệ thống giám sát. Dùng `route.path` (mẫu như `/ask`) và gán `unmatched` cho URL không khớp route nào giữ số series nhỏ và cố định.

**Nhiệm vụ: thêm metric phân bố độ dài câu hỏi `agent_question_length_chars`.** Đã thêm vào `06-lab-complete/benchmark-observability/develop/app.py`: một `Histogram` với các bucket `(20, 50, 100, 200, 500, 1000, 2000)` và gọi `QUESTION_LENGTH.observe(len(body.question))` ở đầu endpoint `ask`. Dùng Histogram, không dùng label `length=...`, vì độ dài có vô số giá trị. Kiểm tra bằng 3 câu hỏi (2, 40 và 150 ký tự):

```
agent_question_length_chars_bucket{le="20.0"} 1.0
agent_question_length_chars_bucket{le="50.0"} 2.0
agent_question_length_chars_bucket{le="200.0"} 3.0
agent_question_length_chars_count 3.0
agent_question_length_chars_sum 192.0
```

### 4.5 Exercise 7.4 — đọc dashboard Grafana (30 user, ramp 5)

Số đo bằng truy vấn Prometheus sau khi Locust (30 user, ramp 5) chạy 150 giây trên stack mặc định (2 agent, model nhỏ, agent v2). Đây là giá trị tức thời của cửa sổ 1 phút, nên thay đổi giữa các lần đo.

1. **p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?** p95 ≈ 0,95 s, avg ≈ 0,264 s, p50 ≈ 0,177 s. p95 gấp khoảng 3,6 lần avg và p50 gần bằng latency nền: số đông request nhanh (~0,18 s) nhưng một nhóm nhỏ request chậm (~1,7 s, do 3 % request bị `MOCK_SLOW_RATE`) kéo p95 lên cao mà avg tăng ít. Khoảng cách lớn giữa avg và p95 là dấu hiệu của tail latency. Lưu ý p95 được ước lượng từ bucket của histogram nên là giá trị nội suy và dao động theo cửa sổ.
2. **Nginx có chia đều traffic cho 2 instance không?** Có: mỗi instance nhận **9,13 request/giây** (hai giá trị trùng nhau đến 4 chữ số), đúng với round-robin của Nginx.
3. **Vì sao input tokens/s lớn hơn output tokens/s?** Đo được input ≈ 1405 token/s, output ≈ 736 token/s (khoảng 1,9 lần). Agent v2 có bước retrieval nên prompt gồm system prompt, tài liệu tìm được và câu hỏi, dài hơn câu trả lời. Ví dụ một request: 91 token vào, 55 token ra.
4. **`curl http://localhost:8080/metrics` trả về gì? Vì sao?** Trả về **404 Not Found** từ Nginx. `nginx.conf` chặn `/metrics` từ bên ngoài vì metrics lộ thông tin nội bộ (số request, latency, chi phí, phiên bản) và không nên public; Prometheus vẫn đọc được vì nó scrape trực tiếp từng agent trong mạng Docker nội bộ (service discovery qua DNS).

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10, 2 phút)

Số liệu dòng `Aggregated` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (gồm cả `POST /ask` và `GET /health`).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65,8 | 190 | 260 | 1700 | 77 / 7820 (0,98 %) |
| 3 | 65,9 | 200 | 300 | 1700 | 57 / 7841 (0,73 %) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không cải thiện** p95 (260 so với 300 ms, thực tế nhỉnh hơn nhưng nằm trong dao động giữa hai lần chạy) và RPS gần như bằng nhau (65,8 so với 65,9). Lý do: Locust dùng `wait_time = between(0.5, 2)` nên 100 user chỉ tạo khoảng 66 request/giây, và một instance (0,5 CPU) đã đủ xử lý tải này mà không xếp hàng. Nút thắt không nằm ở số lượng instance: p50 ~200 ms và p99 1700 ms do chính lời gọi LLM (latency nền 120–180 ms cộng 3 % request chậm +1500 ms), instance nào xử lý cũng chịu độ trễ đó. Failures (~1 %) là lỗi 503 do mock LLM cố tình gây ra, tỉ lệ như nhau ở hai lần chạy; chênh lệch 77 so với 57 là ngẫu nhiên. Để thấy lợi ích của scale cần tải đủ lớn để làm một instance bão hòa (ví dụ giảm `wait_time` hoặc tăng số user), như đã thấy ở mục 2.1.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. Percentile (p95/p99) mới nói đúng trải nghiệm người dùng: avg chỉ tăng 15 % trong khi p99 tăng gần 7 lần khi chỉ 3 % request chậm, nên SLO phải đặt theo percentile.
  2. Metric hạ tầng không thấy được lỗi chất lượng (thí nghiệm E) và có thể không thấy cả sự cố hạ tầng (thí nghiệm D, request timeout ở Nginx); cần eval/golden dataset và giám sát ở tầng load balancer hoặc synthetic check bên ngoài.
  3. Ba trụ cột bổ trợ nhau: dashboard báo p95 tăng, Jaeger chỉ ra span `chat` chiếm ~98 % thời gian, và `trace_id` trong log JSON liên kết thẳng tới dòng log chi tiết. Thêm nữa: không tin kết quả benchmark khi chưa kiểm tra hệ thống chạy đúng (lần đầu 100 % lỗi 502 do thiếu `PYTHONUSERBASE`).
- Nếu đưa agent này lên production thật, mình sẽ thêm:
  - Alert theo chất lượng: eval định kỳ trên golden dataset và alert khi accuracy giảm so với baseline.
  - Metric/alert ở tầng Nginx (tỉ lệ 502/504, upstream timeout) hoặc synthetic check từ bên ngoài, vì lỗi ở tầng đó agent không nhìn thấy (thí nghiệm D).
  - Chỉnh ngưỡng `LLMCostBurnRateHigh` cho phù hợp tải thật (hiện 2 USD/giờ đã bị vượt ở tải 30 user bình thường) và thêm budget cảnh báo theo ngày.
  - Sampling cho trace (ví dụ giữ 10 %, nhưng giữ 100 % trace lỗi và chậm) để giảm chi phí khi traffic lớn.
