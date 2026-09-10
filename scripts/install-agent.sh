#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <relay-ws-url> <token> [device-name]"
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m venv "$repo_root/.venv"
"$repo_root/.venv/bin/pip" install -e "$repo_root"

cat > "$repo_root/.agent.env" <<EOF
AIWM_RELAY_URL=$1
AIWM_TOKEN=$2
AIWM_DEVICE_NAME=${3:-$(hostname)}
EOF

echo "Agent installed. Load .agent.env, then run .venv/bin/aiwm-agent."
