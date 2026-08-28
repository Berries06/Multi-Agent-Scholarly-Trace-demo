#!/usr/bin/env bash
set -euo pipefail

version=${1:?usage: 服务器全量发布.sh <version> <sha256>}
expected_sha=${2:?missing sha256}

[[ "$version" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'invalid version' >&2; exit 2; }
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || { echo 'invalid sha256' >&2; exit 2; }

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud bash -s -- "$version" "$expected_sha" <<'REMOTE'
set -euo pipefail

version=${1:?missing version}
expected_sha=${2:?missing sha256}
deploy_root=/opt/yanhai-agent-demo
release_root=/opt/yanhai-agent-demo/releases
current_link=/opt/yanhai-agent-demo/current
data_root=/var/lib/yanhai-agent-demo
stage="/tmp/yanhai-agent-demo-${version}"
archive="$stage/release.tar.gz"
new_release="$release_root/$version"
service_name=yanhai-agent-demo
service_unit=/etc/systemd/system/yanhai-agent-demo.service
nginx_locations=/etc/nginx/snippets/agentdemo.locations.conf
nginx_rate_limit=/etc/nginx/conf.d/agentdemo-rate-limit.conf

[[ "$version" =~ ^[A-Za-z0-9._-]+$ ]]
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]]
[[ "$(realpath -m "$deploy_root")" == /opt/yanhai-agent-demo ]]
[[ "$(realpath -m "$release_root")" == /opt/yanhai-agent-demo/releases ]]
[[ "$(dirname "$(realpath -m "$new_release")")" == "$release_root" ]]
[[ "$(realpath -m "$stage")" == "/tmp/yanhai-agent-demo-${version}" ]]
[[ -f "$archive" ]]
[[ "$(sha256sum "$archive" | cut -d' ' -f1)" == "$expected_sha" ]]

install -d -o root -g root -m 0755 "$deploy_root" "$release_root"
if [[ -e "$new_release" ]]; then
    [[ "$(dirname "$(realpath -m "$new_release")")" == "$release_root" ]]
    rm -rf -- "$new_release"
fi
install -d -o root -g root -m 0755 "$new_release"
tar -xzf "$archive" -C "$new_release"
[[ -f "$new_release/src/yanhai/api.py" ]]
[[ -f "$new_release/frontend/dist/index.html" ]]
[[ -f "$new_release/deploy/systemd/yanhai-agent-demo.service" ]]

python3 -m venv "$new_release/.venv"
"$new_release/.venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"$new_release/.venv/bin/python" -m pip install --disable-pip-version-check "$new_release"

install -d -m 0700 "$stage/preflight-data"
PYTHONPATH="$new_release/src" \
YANHAI_PROJECT_ROOT="$new_release" \
YANHAI_DATA_DIR="$stage/preflight-data" \
"$new_release/.venv/bin/python" - <<'PY'
from yanhai.api import app

assert app.title
print(f"preflight_app={app.title}")
PY

# 配置文件来自 Windows 工作区时可能带 CRLF；部署前统一为 Linux 行尾。
sed -i 's/\r$//' \
    "$new_release/deploy/systemd/yanhai-agent-demo.service" \
    "$new_release/deploy/nginx/agentdemo.locations.conf" \
    "$new_release/deploy/nginx/agentdemo-rate-limit.conf"

old_current=$(readlink -f "$current_link" 2>/dev/null || true)
switched=0
accepted=0
unit_changed=0
nginx_changed=0

rollback() {
    status=$?
    if (( status != 0 && accepted == 0 )); then
        echo "deployment_failed_status=$status" >&2
        if (( unit_changed == 1 )) && [[ -f "$stage/yanhai-agent-demo.service.bak" ]]; then
            install -o root -g root -m 0644 "$stage/yanhai-agent-demo.service.bak" "$service_unit" || true
            systemctl daemon-reload || true
        fi
        if (( nginx_changed == 1 )); then
            [[ -f "$stage/agentdemo.locations.conf.bak" ]] && install -o root -g root -m 0644 "$stage/agentdemo.locations.conf.bak" "$nginx_locations" || true
            [[ -f "$stage/agentdemo-rate-limit.conf.bak" ]] && install -o root -g root -m 0644 "$stage/agentdemo-rate-limit.conf.bak" "$nginx_rate_limit" || true
            nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
        fi
        if (( switched == 1 )) && [[ -n "$old_current" && -d "$old_current" ]]; then
            rollback_link="$deploy_root/.current-rollback-${version}"
            rm -f -- "$rollback_link"
            ln -s "$old_current" "$rollback_link"
            mv -Tf "$rollback_link" "$current_link"
        fi
        systemctl start "$service_name" || true
    fi
    exit "$status"
}
trap rollback EXIT

systemctl stop "$service_name"

next_link="$deploy_root/.current-next-${version}"
rm -f -- "$next_link"
ln -s "$new_release" "$next_link"
mv -Tf "$next_link" "$current_link"
switched=1

if ! cmp -s "$new_release/deploy/systemd/yanhai-agent-demo.service" "$service_unit"; then
    [[ -f "$service_unit" ]] && cp -a "$service_unit" "$stage/yanhai-agent-demo.service.bak"
    install -o root -g root -m 0644 "$new_release/deploy/systemd/yanhai-agent-demo.service" "$service_unit"
    unit_changed=1
fi

if ! cmp -s "$new_release/deploy/nginx/agentdemo.locations.conf" "$nginx_locations" || \
   ! cmp -s "$new_release/deploy/nginx/agentdemo-rate-limit.conf" "$nginx_rate_limit"; then
    [[ -f "$nginx_locations" ]] && cp -a "$nginx_locations" "$stage/agentdemo.locations.conf.bak"
    [[ -f "$nginx_rate_limit" ]] && cp -a "$nginx_rate_limit" "$stage/agentdemo-rate-limit.conf.bak"
    install -o root -g root -m 0644 "$new_release/deploy/nginx/agentdemo.locations.conf" "$nginx_locations"
    install -o root -g root -m 0644 "$new_release/deploy/nginx/agentdemo-rate-limit.conf" "$nginx_rate_limit"
    nginx_changed=1
fi

systemctl daemon-reload
nginx -t
systemctl start "$service_name"

ready=0
for _ in $(seq 1 30); do
    if curl --fail --silent --show-error http://127.0.0.1:8766/api/ready | grep -q '"status":"ready"'; then
        ready=1
        break
    fi
    sleep 1
done
[[ "$ready" == 1 ]]
systemctl is-active --quiet "$service_name"
if grep -q '^YANHAI_DEEPSEEK_KEY_FILE=' /etc/yanhai-agent-demo.env; then
    key_file=$(sed -n 's/^YANHAI_DEEPSEEK_KEY_FILE=//p' /etc/yanhai-agent-demo.env | tail -n 1)
    [[ -n "$key_file" && -s "$key_file" ]]
    runuser -u yanhai-agent -- test -r "$key_file"
fi
if (( nginx_changed == 1 )); then
    systemctl reload nginx
fi
accepted=1

deleted=0
while IFS= read -r -d '' old_release; do
    [[ "$(dirname "$(realpath -m "$old_release")")" == "$release_root" ]]
    rm -rf -- "$old_release"
    deleted=$((deleted + 1))
done < <(find "$release_root" -mindepth 1 -maxdepth 1 ! -name "$version" -print0)

[[ "$(find "$release_root" -mindepth 1 -maxdepth 1 | wc -l)" == 1 ]]
[[ "$(readlink -f "$current_link")" == "$new_release" ]]
systemctl is-active --quiet "$service_name"

printf 'release=%s\nold_releases_deleted=%s\nservice=%s\ncurrent=%s\ndata_root=%s\n' \
    "$version" "$deleted" "$(systemctl is-active "$service_name")" \
    "$(readlink -f "$current_link")" "$(du -sh "$data_root" | cut -f1)"

trap - EXIT
rm -rf -- "$stage"
REMOTE
