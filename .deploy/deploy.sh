#!/bin/bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="lineba"
REMOTE_DIR="/home/l/linebaru/dopler/public_html"
SITE_URL="https://dopler.lineband.ru"

cd "$ROOT"

echo "== Portfolio deploy =="

# 1. Никаких незакоммиченных изменений
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree is not clean."
  echo "Commit or discard changes before deploy."
  exit 1
fi

# 2. Деплоим только main
BRANCH="$(git branch --show-current)"

if [ "$BRANCH" != "main" ]; then
  echo "ERROR: deploy allowed only from main."
  exit 1
fi

# 3. Проверяем GitHub
git fetch origin main

LOCAL_COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse origin/main)"

if [ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]; then
  echo "ERROR: local main and origin/main differ."
  echo "Push or pull before deploy."
  exit 1
fi

echo "Commit: $LOCAL_COMMIT"

# 4. Собираем чистую копию только из Git
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

git archive HEAD | tar -x -C "$TMP_DIR"

# 5. Загружаем production
rsync -avz \
  --exclude '.gitignore' \
  --exclude '.deploy/' \
  --exclude '.claude/' \
  --exclude 'AGENTS.md' \
  --exclude 'CLAUDE.md' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude '.DS_Store' \
  --exclude '.well-known/' \
  --exclude '.htaccess' \
  "$TMP_DIR/" \
  "$REMOTE:$REMOTE_DIR/"

# 6. Проверяем сайт
HTTP_CODE="$(curl -L -s -o /dev/null -w "%{http_code}" "$SITE_URL")"

if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: production returned HTTP $HTTP_CODE"
  exit 1
fi

echo "Production HTTP: $HTTP_CODE"
echo "DEPLOY SUCCESS"
echo "$SITE_URL"
