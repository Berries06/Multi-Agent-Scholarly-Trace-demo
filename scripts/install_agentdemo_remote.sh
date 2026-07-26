#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s <stage-directory> <release-id>\n' "$0" >&2
  exit 2
fi

STAGE=$1
RELEASE_ID=$2
APP_ROOT=/opt/yanhai-agent-demo
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
SITE_ROOT=/var/www/mysite
BACKUP_ROOT=/var/backups/yanhai-agent-demo
EXPECTED_NGINX_HASH=120607dfff4498e5c62b2ac0cbff7d7d6060aeeb3b47938d1a8e7dd19f2856b1
EXPECTED_QT_HASH=feabdb6e6c820a42a97996dc7e1c0a15f076600289425efe34ac8165ab09633a
EXPECTED_WEB_HASH=bc7883a56bacd0530f0295bb5067ed72b2dfb23ac30ddebac4c7b1fe36c34b48
NGINX_SITE=/etc/nginx/sites-available/mysite

for required in \
  "$STAGE/yanhai-web-0.1.0.tar.gz" \
  "$STAGE/YanhaiTrace-Windows-x64-0.1.0.zip" \
  "$STAGE/deploy/main-site/index.html" \
  "$STAGE/deploy/landing/index.html" \
  "$STAGE/deploy/install/index.html" \
  "$STAGE/deploy/install/styles.css" \
  "$STAGE/deploy/nginx/agentdemo-rate-limit.conf" \
  "$STAGE/deploy/nginx/agentdemo.locations.conf" \
  "$STAGE/deploy/nginx/mysite.with-agentdemo.conf" \
  "$STAGE/deploy/systemd/yanhai-agent-demo.service"; do
  [[ -f "$required" ]] || {
    printf 'Missing staged file: %s\n' "$required" >&2
    exit 1
  }
done

actual_nginx_hash=$(sha256sum "$NGINX_SITE" | awk '{print $1}')
if [[ "$actual_nginx_hash" != "$EXPECTED_NGINX_HASH" ]]; then
  printf 'Nginx site changed since inspection; refusing overwrite.\n' >&2
  printf 'Expected %s, found %s\n' "$EXPECTED_NGINX_HASH" "$actual_nginx_hash" >&2
  exit 1
fi

printf '%s  %s\n' "$EXPECTED_QT_HASH" \
  "$STAGE/YanhaiTrace-Windows-x64-0.1.0.zip" | sha256sum -c -
printf '%s  %s\n' "$EXPECTED_WEB_HASH" \
  "$STAGE/yanhai-web-0.1.0.tar.gz" | sha256sum -c -

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$BACKUP_ROOT/$timestamp"
install -d -m 0700 "$backup_dir"
cp -a "$NGINX_SITE" "$backup_dir/mysite.nginx"
cp -a "$SITE_ROOT/index.html" "$backup_dir/mysite.index.html"
if [[ -e "$SITE_ROOT/AgentDemo" ]]; then
  cp -a "$SITE_ROOT/AgentDemo" "$backup_dir/AgentDemo"
fi
if [[ -e /etc/systemd/system/yanhai-agent-demo.service ]]; then
  cp -a /etc/systemd/system/yanhai-agent-demo.service "$backup_dir/"
fi

if ! id yanhai-agent >/dev/null 2>&1; then
  useradd --system --home /nonexistent --shell /usr/sbin/nologin yanhai-agent
fi

if [[ -e "$RELEASE_DIR" ]]; then
  printf 'Release already exists: %s\n' "$RELEASE_DIR" >&2
  exit 1
fi
install -d -o root -g root -m 0755 "$RELEASE_DIR"
tar -xzf "$STAGE/yanhai-web-0.1.0.tar.gz" -C "$RELEASE_DIR"
chown -R root:root "$RELEASE_DIR"
find "$RELEASE_DIR" -type d -exec chmod 0755 {} +
find "$RELEASE_DIR" -type f -exec chmod 0644 {} +
ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"

install -m 0644 "$STAGE/deploy/systemd/yanhai-agent-demo.service" \
  /etc/systemd/system/yanhai-agent-demo.service
systemctl daemon-reload
systemctl enable --now yanhai-agent-demo
systemctl is-active --quiet yanhai-agent-demo

install -m 0644 "$STAGE/deploy/main-site/index.html" "$SITE_ROOT/index.html"
install -d -m 0755 "$SITE_ROOT/AgentDemo/install"
install -m 0644 "$STAGE/deploy/landing/index.html" \
  "$SITE_ROOT/AgentDemo/index.html"
install -m 0644 "$STAGE/deploy/install/index.html" \
  "$SITE_ROOT/AgentDemo/install/index.html"
install -m 0644 "$STAGE/deploy/install/styles.css" \
  "$SITE_ROOT/AgentDemo/install/styles.css"
install -m 0644 "$STAGE/YanhaiTrace-Windows-x64-0.1.0.zip" \
  "$SITE_ROOT/AgentDemo/install/YanhaiTrace-Windows-x64-0.1.0.zip"

install -m 0644 "$STAGE/deploy/nginx/agentdemo-rate-limit.conf" \
  /etc/nginx/conf.d/agentdemo-rate-limit.conf
install -m 0644 "$STAGE/deploy/nginx/agentdemo.locations.conf" \
  /etc/nginx/snippets/agentdemo.locations.conf
install -m 0644 "$STAGE/deploy/nginx/mysite.with-agentdemo.conf" "$NGINX_SITE"

if ! nginx -t; then
  cp -a "$backup_dir/mysite.nginx" "$NGINX_SITE"
  rm -f /etc/nginx/conf.d/agentdemo-rate-limit.conf
  rm -f /etc/nginx/snippets/agentdemo.locations.conf
  nginx -t
  printf 'Nginx validation failed; original configuration restored.\n' >&2
  exit 1
fi

systemctl reload nginx
printf 'release=%s\nbackup=%s\n' "$RELEASE_DIR" "$backup_dir"
