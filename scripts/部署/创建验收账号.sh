#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud bash -s <<'REMOTE'
set -euo pipefail
umask 077

current=/opt/yanhai-agent-demo/current
data_root=/var/lib/yanhai-agent-demo
python="$current/.venv/bin/python"
[[ -x "$python" ]]
[[ "$(readlink -f "$current")" == /opt/yanhai-agent-demo/releases/0.6.0-20260828-full ]]

login_email="acceptance-$(date -u +%Y%m%d-%H%M%S)-$(printf '%04x' "$((RANDOM % 65536))")@snowsong.top"
login_password=$(python3 - <<'PY'
import secrets
print("Mat!" + secrets.token_urlsafe(15))
PY
)
export YANHAI_NEW_EMAIL="$login_email"
export YANHAI_NEW_PASSWORD="$login_password"

PYTHONPATH="$current/src" \
YANHAI_PROJECT_ROOT="$current" \
YANHAI_DATA_DIR="$data_root" \
"$python" - <<'PY'
import os

from yanhai.resources import database_path
from yanhai.storage import AppRepository

user = AppRepository(database_path()).register_user(
    os.environ["YANHAI_NEW_EMAIL"],
    "验收账号",
    os.environ["YANHAI_NEW_PASSWORD"],
)
assert user["email"] == os.environ["YANHAI_NEW_EMAIL"]
PY

"$python" - <<'PY'
import json
import os
import urllib.request

base = "https://snowsong.top/AgentDemo/start"
for path, expected in (("/api/health", "ok"), ("/api/ready", "ready")):
    with urllib.request.urlopen(base + path, timeout=20) as response:
        payload = json.load(response)
        assert response.status == 200
        assert payload["status"] == expected

body = json.dumps(
    {
        "identifier": os.environ["YANHAI_NEW_EMAIL"],
        "password": os.environ["YANHAI_NEW_PASSWORD"],
    }
).encode("utf-8")
request = urllib.request.Request(
    base + "/api/auth/login",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as response:
    payload = json.load(response)
    assert response.status == 200
    assert payload["user"]["email"] == os.environ["YANHAI_NEW_EMAIL"]
PY

printf 'PUBLIC_URL=%s\nLOGIN_EMAIL=%s\nLOGIN_PASSWORD=%s\nPUBLIC_HEALTH=%s\nPUBLIC_LOGIN=%s\n' \
    'https://snowsong.top/AgentDemo/start/' "$login_email" "$login_password" ok ok
REMOTE
