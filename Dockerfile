FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app

# 让容器启动时自动完成初始化（幂等）：
# - Postgres migrations
# - Redis streams + consumer group
RUN chmod +x /app/scripts/docker_entrypoint.sh

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
