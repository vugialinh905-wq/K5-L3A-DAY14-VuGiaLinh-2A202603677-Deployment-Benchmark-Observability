# ---------- Stage 1: builder — cài dependencies ----------
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
# --user cài vào /root/.local để stage runtime chỉ cần copy thư mục này
RUN pip install --no-cache-dir --user -r requirements.txt

# ---------- Stage 2: runtime — chỉ chứa kết quả, chạy bằng user non-root ----------
FROM python:3.11-slim AS runtime

RUN useradd --create-home --uid 1000 agent
WORKDIR /app

COPY --from=builder /root/.local /home/agent/.local
COPY --chown=agent:agent app/ ./app/
COPY --chown=agent:agent utils/ ./utils/

# Không có dòng này user non-root sẽ không tìm thấy package → container crash
ENV PYTHONUSERBASE=/home/agent/.local \
    PATH=/home/agent/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

USER agent
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:%s/health' % os.environ.get('PORT','8000'), timeout=3)"

# exec → uvicorn là PID 1, nhận SIGTERM khi `docker stop`; lắng nghe theo biến PORT
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
