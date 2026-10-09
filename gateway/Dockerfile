FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /srv

# 先装依赖，利用镜像层缓存
COPY gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/app ./app

# 数据落卷（compose 里挂到 /data）
RUN mkdir -p /data

EXPOSE 8000

# --app-dir 让 `app` 包可被导入；workers=1 是刻意的：
# 后台 worker 与内存态（限流器、告警去重）都是单进程假设，多 worker 会重复派发。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/srv", "--workers", "1"]
