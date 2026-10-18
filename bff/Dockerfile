# 小程序 BFF —— 无状态，任何支持容器的云平台都能直接跑
#
# 构建：docker build -t campus-bff .
# 运行：docker run -p 8100:8100 --env-file .env.bff campus-bff

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py cards.py ./

# 云平台通常通过 PORT 注入端口，没有就用 8100
ENV PORT=8100
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
