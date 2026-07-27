#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s <release-archive.tar.gz> <release-id>\n' "$0" >&2
  exit 2
fi

ARCHIVE=$(realpath "$1")
RELEASE_ID=$2
APP_ROOT=/home/snowsong/apps/yanhai-trace
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
DATA_ROOT=/home/snowsong/.local/share/yanhai-trace
UNIT_SOURCE="$RELEASE_DIR/deploy/systemd/yanhai-wsl-local.service"
UNIT_TARGET=/etc/systemd/system/yanhai-wsl-local.service

if [[ ! -f "$ARCHIVE" ]]; then
  printf 'Release archive not found: %s\n' "$ARCHIVE" >&2
  exit 2
fi
if [[ ! "$RELEASE_ID" =~ ^[A-Za-z0-9._-]{3,80}$ ]]; then
  printf 'Invalid release id: %s\n' "$RELEASE_ID" >&2
  exit 2
fi
if [[ -e "$RELEASE_DIR" ]]; then
  printf 'Release directory already exists; refusing to overwrite: %s\n' \
    "$RELEASE_DIR" >&2
  exit 2
fi

install -d -m 0755 "$APP_ROOT/releases" "$DATA_ROOT"
install -d -m 0755 "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"

for required in \
  "$RELEASE_DIR/src/yanhai/server.py" \
  "$RELEASE_DIR/src/yanhai/storage.py" \
  "$RELEASE_DIR/web/index.html" \
  "$RELEASE_DIR/scripts/seed_local_database.py" \
  "$UNIT_SOURCE"; do
  if [[ ! -f "$required" ]]; then
    printf 'Incomplete release, missing: %s\n' "$required" >&2
    exit 2
  fi
done

ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"

PYTHONPATH="$RELEASE_DIR/src" \
YANHAI_PROJECT_ROOT="$RELEASE_DIR" \
YANHAI_DATA_DIR="$DATA_ROOT" \
python3 "$RELEASE_DIR/scripts/seed_local_database.py"

sudo install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
sudo systemctl daemon-reload
sudo systemctl enable yanhai-wsl-local.service
sudo systemctl restart yanhai-wsl-local.service

curl --fail --silent --show-error \
  --retry 15 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:8877/api/health >/dev/null

printf 'Installed release: %s\n' "$RELEASE_DIR"
printf 'Persistent data: %s\n' "$DATA_ROOT"
printf 'Local URL: http://127.0.0.1:8877/\n'
