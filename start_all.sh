#!/bin/bash
set -e

PROJECT=/Users/mima1234/PycharmProjects/ragService
cd $PROJECT

echo "==> 启动 Docker Desktop"
open -a Docker
echo "等待 Docker 就绪..."
until docker info > /dev/null 2>&1; do
  sleep 2
done
echo "Docker OK"

echo "==> 启动容器"
docker compose start
sleep 3
docker compose ps

echo "==> 提示"
cat <<EOF

接下来手动开两个终端：

【终端 1】uvicorn
  cd $PROJECT
  conda activate kbs_service
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

【终端 2】celery
  cd $PROJECT
  conda activate kbs_service
  python -m celery -A app.worker.celery_app.celery_app worker --loglevel=INFO --pool=solo

EOF