#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  printf 'Usage: %s <stage> <release-id> <version> <web-sha256> <qt-sha256>\n' "$0" >&2
  exit 2
fi

STAGE=$1
RELEASE_ID=$2
VERSION=$3
EXPECTED_WEB_HASH=$4
EXPECTED_QT_HASH=$5

[[ "$STAGE" == /tmp/yanhai-agent-demo-* ]] || {
  printf 'Unsafe stage path: %s\n' "$STAGE" >&2
  exit 2
}
[[ "$RELEASE_ID" =~ ^[A-Za-z0-9._-]+$ ]] || {
  printf 'Invalid release id: %s\n' "$RELEASE_ID" >&2
  exit 2
}
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  printf 'Invalid version: %s\n' "$VERSION" >&2
  exit 2
}
[[ "$EXPECTED_WEB_HASH" =~ ^[0-9a-f]{64}$ ]] || exit 2
[[ "$EXPECTED_QT_HASH" =~ ^[0-9a-f]{64}$ ]] || exit 2

APP_ROOT=/opt/yanhai-agent-demo
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
CURRENT_LINK="$APP_ROOT/current"
SITE_ROOT=/var/www/mysite
SERVICE_FILE=/etc/systemd/system/yanhai-agent-demo.service
ENV_FILE=/etc/yanhai-agent-demo.env
BACKUP_ROOT=/var/backups/yanhai-agent-demo
WEB_ARCHIVE="$STAGE/yanhai-web-$VERSION.tar.gz"
QT_ARCHIVE="$STAGE/YanhaiTrace-Windows-x64-$VERSION.zip"
KEY_FILE="$STAGE/DeepSeekAPI.txt"

for required in \
  "$WEB_ARCHIVE" \
  "$QT_ARCHIVE" \
  "$KEY_FILE" \
  "$STAGE/yanhai-agent-demo.service" \
  "$STAGE/install-index.html" \
  "$STAGE/install-styles.css"; do
  [[ -f "$required" ]] || {
    printf 'Missing staged file: %s\n' "$required" >&2
    exit 1
  }
done

printf '%s  %s\n' "$EXPECTED_WEB_HASH" "$WEB_ARCHIVE" | sha256sum -c -
printf '%s  %s\n' "$EXPECTED_QT_HASH" "$QT_ARCHIVE" | sha256sum -c -
[[ -s "$KEY_FILE" ]] || {
  printf 'Server DeepSeek key file is empty.\n' >&2
  exit 1
}
chmod 0600 "$KEY_FILE"
[[ ! -e "$RELEASE_DIR" ]] || {
  printf 'Release already exists: %s\n' "$RELEASE_DIR" >&2
  exit 1
}

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$BACKUP_ROOT/$timestamp"
install -d -m 0700 "$backup_dir"
old_release=$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)
printf '%s\n' "$old_release" > "$backup_dir/previous-release.txt"
[[ -f "$SERVICE_FILE" ]] && cp -a "$SERVICE_FILE" "$backup_dir/"
[[ -f "$ENV_FILE" ]] && cp -a "$ENV_FILE" "$backup_dir/"
[[ -f "$SITE_ROOT/AgentDemo/install/index.html" ]] &&
  cp -a "$SITE_ROOT/AgentDemo/install/index.html" "$backup_dir/"

install -d -o root -g root -m 0755 "$RELEASE_DIR"
tar -xzf "$WEB_ARCHIVE" -C "$RELEASE_DIR"
chown -R root:root "$RELEASE_DIR"
find "$RELEASE_DIR" -type d -exec chmod 0755 {} +
find "$RELEASE_DIR" -type f -exec chmod 0644 {} +
install -d -o root -g yanhai-agent -m 0750 "$RELEASE_DIR/secret"
install -o root -g yanhai-agent -m 0640 "$KEY_FILE" \
  "$RELEASE_DIR/secret/DeepSeekAPI.txt"

install -o root -g root -m 0644 "$STAGE/yanhai-agent-demo.service" \
  "$SERVICE_FILE"
env_tmp="$ENV_FILE.new"
install -o root -g root -m 0600 /dev/null "$env_tmp"
printf '%s\n' \
  'YANHAI_REGISTRATION_OPEN=1' \
  'YANHAI_COOKIE_SECURE=1' \
  'YANHAI_COOKIE_PATH=/AgentDemo/start/' > "$env_tmp"
mv -f "$env_tmp" "$ENV_FILE"

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
systemctl daemon-reload
service_ready=0
if systemctl restart yanhai-agent-demo; then
  for _attempt in $(seq 1 30); do
    if systemctl is-active --quiet yanhai-agent-demo &&
      curl --fail --silent http://127.0.0.1:8765/api/health \
        > "$backup_dir/new-health.json"; then
      service_ready=1
      break
    fi
    sleep 0.5
  done
fi
if [[ "$service_ready" -ne 1 ]]; then
  printf 'New service failed; restoring previous release.\n' >&2
  if [[ -n "$old_release" ]]; then
    ln -sfn "$old_release" "$CURRENT_LINK"
  fi
  [[ -f "$backup_dir/yanhai-agent-demo.service" ]] &&
    cp -a "$backup_dir/yanhai-agent-demo.service" "$SERVICE_FILE"
  if [[ -f "$backup_dir/yanhai-agent-demo.env" ]]; then
    cp -a "$backup_dir/yanhai-agent-demo.env" "$ENV_FILE"
  else
    rm -f "$ENV_FILE"
  fi
  systemctl daemon-reload
  systemctl restart yanhai-agent-demo
  exit 1
fi

install -d -m 0755 "$SITE_ROOT/AgentDemo/install"
install -o root -g root -m 0644 "$STAGE/install-index.html" \
  "$SITE_ROOT/AgentDemo/install/index.html"
install -o root -g root -m 0644 "$STAGE/install-styles.css" \
  "$SITE_ROOT/AgentDemo/install/styles.css"
install -o root -g root -m 0644 "$QT_ARCHIVE" \
  "$SITE_ROOT/AgentDemo/install/YanhaiTrace-Windows-x64-$VERSION.zip"

rm -f "$KEY_FILE"
printf 'release=%s\nbackup=%s\n' "$RELEASE_DIR" "$backup_dir"
