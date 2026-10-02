#!/usr/bin/env bash
# Server dry-run / go-live checklist for ASAT V2 MongoDB backups.
# Run on the DATABASE host (15.204.246.10) after install-on-host.sh and AWS setup.
#
# Usage:
#   sudo ./validate-host.sh           # checks only (no dump)
#   sudo ./validate-host.sh --dry-run # also dump registration locally
#   sudo ./validate-host.sh --full    # dump all 7 DBs and upload to S3 (quiet window)

set -euo pipefail

ENV_FILE="${BACKUP_ENV_FILE:-/etc/asat/mongodb-backup.env}"
MODE="check"
if [[ "${1:-}" == "--dry-run" ]]; then
  MODE="dry-run"
elif [[ "${1:-}" == "--full" ]]; then
  MODE="full"
fi

fail=0
ok() { echo "OK  $*"; }
bad() { echo "FAIL $*"; fail=1; }

echo "=== ASAT V2 MongoDB backup host validation (database host) ==="

if [[ ! -f "${ENV_FILE}" ]]; then
  bad "Missing ${ENV_FILE}"
else
  ok "Env file present"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${MONGO_HOST:=127.0.0.1}"
: "${MONGO_PORT:=28395}"

command -v mongodump >/dev/null && ok "mongodump installed" || bad "mongodump missing (install MongoDB Database Tools 7.x)"
command -v mongorestore >/dev/null && ok "mongorestore installed" || bad "mongorestore missing"
command -v mongosh >/dev/null && ok "mongosh installed" || bad "mongosh missing"
command -v aws >/dev/null && ok "aws cli installed" || bad "aws cli missing"
command -v sha256sum >/dev/null && ok "sha256sum installed" || bad "sha256sum missing"

if ss -lnt 2>/dev/null | grep -q ":${MONGO_PORT} "; then
  ok "Port ${MONGO_PORT} is listening"
else
  bad "Port ${MONGO_PORT} is not listening on this host"
fi

if [[ -n "${S3_BUCKET:-}" ]]; then
  if aws s3api head-bucket --bucket "${S3_BUCKET}" 2>/dev/null; then
    ok "S3 bucket reachable: ${S3_BUCKET}"
  else
    bad "Cannot head-bucket ${S3_BUCKET} (check IAM / region)"
  fi
else
  bad "S3_BUCKET unset in ${ENV_FILE}"
fi

if [[ -f /etc/systemd/system/asat-mongo-backup.timer ]]; then
  ok "systemd timer unit installed"
  if grep -q '^Timezone=UTC$' /etc/systemd/system/asat-mongo-backup.timer; then
    ok "timer Timezone=UTC (slots 02:00, 10:00, 18:00 UTC)"
  else
    bad "timer file is missing Timezone=UTC"
  fi
  if systemctl is-enabled asat-mongo-backup.timer >/dev/null 2>&1; then
    echo "     timer is ENABLED"
  else
    echo "     timer is not enabled (expected until after first successful full run)"
  fi
else
  bad "systemd units not installed — run install-on-host.sh"
fi

if [[ -n "${MONGO_BACKUP_USER:-}" && -n "${MONGO_BACKUP_PASSWORD:-}" ]]; then
  if mongosh --quiet \
      --host "${MONGO_HOST}" \
      --port "${MONGO_PORT}" \
      --username "${MONGO_BACKUP_USER}" \
      --password "${MONGO_BACKUP_PASSWORD}" \
      --authenticationDatabase "${MONGO_AUTH_DB:-admin}" \
      --eval 'db.getSiblingDB("registration").getCollectionNames().length' >/dev/null 2>&1; then
    ok "asatBackup can read registration via ${MONGO_HOST}:${MONGO_PORT}"
  else
    bad "asatBackup cannot authenticate or read registration — run create-mongo-backup-user.sh"
  fi
else
  bad "MONGO_BACKUP_USER / MONGO_BACKUP_PASSWORD unset"
fi

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mongodb-backup.sh"
if [[ ! -x "${SCRIPT}" ]]; then
  SCRIPT="/opt/asat/mongodb-backup/mongodb-backup.sh"
fi

if [[ "${MODE}" == "dry-run" || "${MODE}" == "full" ]]; then
  if [[ "${fail}" -ne 0 ]]; then
    echo "Fix FAIL items before dry-run/full."
    exit 1
  fi
fi

if [[ "${MODE}" == "dry-run" ]]; then
  echo "=== Dry-run registration dump ==="
  "${SCRIPT}" --dry-run --databases registration
  ok "Dry-run finished"
fi

if [[ "${MODE}" == "full" ]]; then
  echo "=== Full seven-database upload ==="
  "${SCRIPT}" --slot "$(date -u +%H%M)"
  ok "Full backup finished — verify daily/manifests/ in S3 before enabling the timer"
fi

echo
if [[ "${fail}" -ne 0 ]]; then
  echo "Validation FAILED"
  exit 1
fi
echo "Validation PASSED"
echo "Next: after a successful --full run, systemctl enable --now asat-mongo-backup.timer"
echo "Reminder: this timer belongs on 15.204.246.10 only."
exit 0
