# Image chạy tool trên server. Kết quả ghi vào /app/output (gắn volume ra ngoài để giữ lại).
# Cùng phiên bản Python với máy local (.venv 3.14) để chạy giống nhau
FROM python:3.14-slim

# TZ=ICT-7: giờ Việt Nam (UTC+7) cho log, không cần cài thêm gói tzdata
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=ICT-7

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py ./
COPY lead_crawler ./lead_crawler

VOLUME ["/app/output"]

ENTRYPOINT ["python", "main.py"]
