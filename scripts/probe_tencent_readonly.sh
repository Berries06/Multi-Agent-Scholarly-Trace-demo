#!/usr/bin/env bash
set -euo pipefail

printf '[wsl]\n'
printf 'user=%s\n' "$(whoami)"
. /etc/os-release
printf 'distro=%s %s\n' "$NAME" "$VERSION_ID"
printf 'kernel=%s\n' "$(uname -r)"
printf 'python=%s\n' "$(python3 --version 2>&1)"
printf 'docker=%s\n' "$(docker --version 2>/dev/null || printf 'not-found')"
printf 'node=%s\n' "$(node --version 2>/dev/null || printf 'not-found')"

printf '\n[tencent]\n'
ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=accept-new \
  TencentCloud '
    set -eu
    . /etc/os-release
    printf "distro=%s %s\n" "$NAME" "$VERSION_ID"
    printf "kernel=%s\n" "$(uname -r)"
    printf "memory="; free -h | awk "NR == 2 {print \$2 \" total, \" \$3 \" used\"}"
    printf "root_disk="; df -h / | awk "NR == 2 {print \$2 \" total, \" \$3 \" used, \" \$4 \" free\"}"
    printf "nginx=%s\n" "$(command -v nginx || printf not-found)"
    if command -v systemctl >/dev/null 2>&1; then
      printf "nginx_state=%s\n" "$(systemctl is-active nginx 2>/dev/null || true)"
      printf "certbot_timer=%s\n" "$(systemctl is-active certbot.timer 2>/dev/null || true)"
    fi
    printf "certbot=%s\n" "$(command -v certbot || printf not-found)"
    printf "python=%s\n" "$(python3 --version 2>&1)"
    printf "listening_ports:\n"
    ss -lnt | awk "NR == 1 || /:22 |:80 |:443 |:7000 |:8766 /"
    if command -v nginx >/dev/null 2>&1; then
      printf "nginx_routes:\n"
      nginx -T 2>/dev/null |
        grep -E "^[[:space:]]*(listen|server_name|root|location|proxy_pass|ssl_certificate)" |
        sed -E "s#(ssl_certificate(_key)?)[[:space:]]+[^;]+;#\1 <configured>;#"
    fi
  '
