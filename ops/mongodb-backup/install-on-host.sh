#!/usr/bin/env bash
# Scripts-only install. Prefer the repo-root installer which also installs the API:
#   sudo ../install-on-host.sh
# or from the repo root:
#   sudo ./install-on-host.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -x "${ROOT}/install-on-host.sh" ]]; then
  echo "Delegating to ${ROOT}/install-on-host.sh (scripts + API)."
  exec "${ROOT}/install-on-host.sh"
fi

echo "ERROR: repo-root install-on-host.sh not found at ${ROOT}/install-on-host.sh" >&2
exit 1
