#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
scp -o BatchMode=yes -o ConnectTimeout=12 \
  "$script_dir/生产端到端验收.py" TencentCloud:/tmp/yanhai-production-e2e.py

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud bash -s <<'REMOTE'
set -euo pipefail

current=/opt/yanhai-agent-demo/current
set -a
. /etc/yanhai-agent-demo.env
set +a
export PYTHONPATH="$current/src"
export YANHAI_PROJECT_ROOT="$current"
export YANHAI_DATA_DIR=/var/lib/yanhai-agent-demo
"$current/.venv/bin/python" /tmp/yanhai-production-e2e.py
REMOTE
