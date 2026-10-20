#!/usr/bin/env bash
set -euo pipefail

key_file=${1:?usage: 持久化DeepSeek密钥.sh <local-key-file>}
[[ -s "$key_file" ]] || { echo "key file is missing or empty" >&2; exit 2; }

remote_stage="/tmp/yanhai-deepseek-key-upload-$$"
remote_key=/etc/yanhai-agent-demo/DeepSeekAPI.txt
remote_env=/etc/yanhai-agent-demo.env

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud \
  "install -d -o root -g yanhai-agent -m 0750 /etc/yanhai-agent-demo && test ! -e '$remote_stage'"
scp -o BatchMode=yes -o ConnectTimeout=12 "$key_file" "TencentCloud:$remote_stage"

local_sha=$(sha256sum "$key_file" | cut -d' ' -f1)
remote_sha=$(ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud \
  "sha256sum '$remote_stage' | cut -d' ' -f1")
[[ "$local_sha" == "$remote_sha" ]] || { echo "key checksum mismatch" >&2; exit 3; }

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud bash -s -- \
  "$remote_stage" "$remote_key" "$remote_env" <<'REMOTE'
set -euo pipefail
stage=${1:?missing stage}
key=${2:?missing key target}
env_file=${3:?missing environment file}

[[ "$stage" == /tmp/yanhai-deepseek-key-upload-* ]]
[[ "$key" == /etc/yanhai-agent-demo/DeepSeekAPI.txt ]]
[[ "$env_file" == /etc/yanhai-agent-demo.env ]]
[[ -s "$stage" ]]
[[ -f "$env_file" ]]

install -d -o root -g yanhai-agent -m 0750 "$(dirname "$key")"
install -o root -g yanhai-agent -m 0640 "$stage" "$key"
env_tmp=$(mktemp /etc/yanhai-agent-demo.env.XXXXXX)
grep -v '^YANHAI_DEEPSEEK_KEY_FILE=' "$env_file" >"$env_tmp" || true
printf 'YANHAI_DEEPSEEK_KEY_FILE=%s\n' "$key" >>"$env_tmp"
install -o root -g root -m 0600 "$env_tmp" "$env_file"
rm -f -- "$env_tmp" "$stage"

printf 'persistent_key=%s\nkey_mode=%s\nenv_reference=%s\n' \
  "$key" "$(stat -c '%U:%G %a' "$key")" \
  "$(grep -q '^YANHAI_DEEPSEEK_KEY_FILE=/etc/yanhai-agent-demo/DeepSeekAPI.txt$' "$env_file" && echo ok || echo missing)"
runuser -u yanhai-agent -- test -r "$key"
REMOTE
