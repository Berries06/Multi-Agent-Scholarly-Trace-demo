#!/usr/bin/env bash
set -euo pipefail

archive=${1:?usage: 上传发布包.sh <archive> <version> <sha256>}
version=${2:?missing version}
expected_sha=${3:?missing sha256}

[[ -f "$archive" ]] || { echo "archive not found: $archive" >&2; exit 2; }
[[ "$version" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'invalid version' >&2; exit 2; }
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || { echo 'invalid sha256' >&2; exit 2; }

stage="/tmp/yanhai-agent-demo-${version}"
ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud \
  "if test -e '$stage'; then test -d '$stage'; else install -d -m 0700 '$stage'; fi"
scp -o BatchMode=yes -o ConnectTimeout=12 "$archive" \
  "TencentCloud:$stage/release.tar.gz"

actual_sha=$(ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud \
  "sha256sum '$stage/release.tar.gz' | cut -d' ' -f1")
[[ "$actual_sha" == "$expected_sha" ]] || {
  echo "sha256 mismatch: expected=$expected_sha actual=$actual_sha" >&2
  exit 3
}

ssh -o BatchMode=yes -o ConnectTimeout=12 TencentCloud "bash -s" <<REMOTE
set -euo pipefail
archive='$stage/release.tar.gz'
tar -tzf "\$archive" >/dev/null
tar -tzf "\$archive" | grep -x 'frontend/dist/index.html' >/dev/null
tar -tzf "\$archive" | grep -x 'src/yanhai/api.py' >/dev/null
printf 'stage=%s\nsha256=%s\nbytes=' '$stage' '$actual_sha'
stat -c '%s' "\$archive"
REMOTE
