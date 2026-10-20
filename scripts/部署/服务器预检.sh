#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud 'bash -s' <<'REMOTE'
set -euo pipefail

printf 'user='; whoami
printf 'host='; hostname
sudo -n true
echo 'sudo=yes'
printf 'service='; systemctl is-active yanhai-agent-demo 2>/dev/null || true
printf 'current='; readlink -f /opt/yanhai-agent-demo/current 2>/dev/null || echo missing

echo 'releases:'
if sudo test -d /opt/yanhai-agent-demo/releases; then
  sudo find /opt/yanhai-agent-demo/releases -mindepth 1 -maxdepth 1 -printf '%f\n' | sort
else
  echo missing
fi

echo 'deployment_root:'
for path in /opt/yanhai-agent-demo /opt/yanhai-agent-demo/releases /opt/yanhai-agent-demo/current; do
  if sudo test -e "$path" || sudo test -L "$path"; then
    sudo stat -c '%U:%G %a %n' "$path"
  else
    echo "missing $path"
  fi
done

echo 'data_root:'
if sudo test -d /var/lib/yanhai-agent-demo; then
  sudo stat -c '%U:%G %a %n' /var/lib/yanhai-agent-demo
  sudo du -sh /var/lib/yanhai-agent-demo
else
  echo missing
fi

echo 'server_config:'
sudo test -f /etc/yanhai-agent-demo.env && echo 'env=present' || echo 'env=missing'
sudo test -f /etc/systemd/system/yanhai-agent-demo.service && echo 'unit=present' || echo 'unit=missing'
printf 'python='; python3 --version
printf 'nginx='; sudo nginx -t 2>&1
REMOTE
