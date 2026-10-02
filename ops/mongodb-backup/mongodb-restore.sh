#!/usr/bin/env bash
# Restore ASAT V2 MongoDB databases from one daily backup manifest timestamp.
# Run on the database host (15.204.246.10). Uses host mongorestore.
#
# Never restore onto production 127.0.0.1:28395 as the first step.
# Use a scratch host/port (or throwaway mongo), verify, then cut over.
#
# Usage:
#   mongodb-restore.sh --timestamp 2026-09-29T0200Z --host 127.0.0.1 --port 27018
#   mongodb-restore.sh --timestamp 2026-09-29T0200Z --host 127.0.0.1 --port 27018 --databases paymentModule
#   mongodb-restore.sh --timestamp 2026-09-29T0200Z --host 127.0.0.1 --port 28395 --databases paymentModule --drop
#
# Env: /etc/asat/mongodb-backup.env (AWS + MONGO_RESTORE_* or MONGO_ROOT_* for write auth)

set -euo pipefail

ENV_FILE="${BACKUP_ENV_FILE:-/etc/asat/mongodb-backup.env}"
TIMESTAMP=""
RESTORE_HOST=""
RESTORE_PORT=""
ONLY_DATABASES=""
DROP=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timestamp)
      TIMESTAMP="$2"
      shift 2
      ;;
    --host)
      RESTORE_HOST="$2"
      shift 2
      ;;
    --port)
      RESTORE_PORT="$2"
      shift 2
      ;;
    --databases)
      ONLY_DATABASES="$2"
      shift 2
      ;;
    --drop)
      DROP=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${TIMESTAMP}" ]]; then
  echo "Required: --timestamp (example: 2026-09-29T0200Z)" >&2
  exit 2
fi
if [[ ! "${TIMESTAMP}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{4}Z$ ]]; then
  echo "Timestamp must match a manifest name: YYYY-MM-DDTHHMMZ (example 2026-09-29T0200Z)" >&2
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${S3_BUCKET:?Set S3_BUCKET}"
: "${AWS_REGION:=us-east-1}"
: "${LOCAL_WORKDIR:=/var/lib/asat-mongodb-backup}"
: "${MONGO_HOST:=127.0.0.1}"
: "${MONGO_PORT:=28395}"
: "${MONGO_PUBLIC_HOST:=15.204.246.10}"
: "${MONGO_RESTORE_USER:=${MONGO_ROOT_USER:-}}"
: "${MONGO_RESTORE_PASSWORD:=${MONGO_ROOT_PASSWORD:-}}"
: "${MONGO_AUTH_DB:=admin}"

RESTORE_HOST="${RESTORE_HOST:-${MONGO_HOST}}"
RESTORE_PORT="${RESTORE_PORT:-${MONGO_PORT}}"

if ! command -v mongorestore >/dev/null 2>&1; then
  echo "mongorestore not found. Install MongoDB Database Tools on this host." >&2
  exit 1
fi
if ! command -v aws >/dev/null 2>&1 || ! command -v sha256sum >/dev/null 2>&1; then
  echo "aws CLI and sha256sum are required." >&2
  exit 1
fi

export AWS_DEFAULT_REGION="${AWS_REGION}"
export AWS_REGION

WORKDIR="${LOCAL_WORKDIR}/restore-${TIMESTAMP}"
mkdir -p "${WORKDIR}"
trap 'rm -rf "${WORKDIR}"' EXIT

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

if [[ "${RESTORE_PORT}" == "${MONGO_PORT}" ]]; then
  case "${RESTORE_HOST}" in
    127.0.0.1|localhost|::1|"${MONGO_PUBLIC_HOST}")
      log "WARNING: target ${RESTORE_HOST}:${RESTORE_PORT} is the production MongoDB."
      if [[ "${DROP}" -eq 1 && "${DRY_RUN}" -eq 0 ]]; then
        log "WARNING: --drop deletes current collections in the selected databases before loading the archive."
      else
        log "WARNING: prefer a scratch port (for example 27018) before restoring production."
      fi
      ;;
  esac
fi

MANIFEST_KEY="daily/manifests/${TIMESTAMP}.json"
MANIFEST_FILE="${WORKDIR}/manifest.json"
log "Downloading manifest s3://${S3_BUCKET}/${MANIFEST_KEY}"
aws s3 cp "s3://${S3_BUCKET}/${MANIFEST_KEY}" "${MANIFEST_FILE}"

if [[ -z "${MONGO_RESTORE_USER}" || -z "${MONGO_RESTORE_PASSWORD}" ]]; then
  fail "Set MONGO_RESTORE_USER / MONGO_RESTORE_PASSWORD (or MONGO_ROOT_*) in ${ENV_FILE} for mongorestore"
fi

# One JSON object per database, written by mongodb-backup.sh on a single line.
mapfile -t ENTRIES < <(grep -oE '\{"database":"[^"]+","key":"[^"]+","size":[0-9]+,"sha256":"[a-f0-9]+"\}' "${MANIFEST_FILE}")
if [[ ${#ENTRIES[@]} -eq 0 ]]; then
  fail "No database entries found in manifest ${MANIFEST_KEY}"
fi

RESTORED=0
for ENTRY in "${ENTRIES[@]}"; do
  DB="$(sed -n 's/.*"database":"\([^"]*\)".*/\1/p' <<< "${ENTRY}")"
  KEY="$(sed -n 's/.*"key":"\([^"]*\)".*/\1/p' <<< "${ENTRY}")"
  EXPECTED_SHA="$(sed -n 's/.*"sha256":"\([a-f0-9]*\)".*/\1/p' <<< "${ENTRY}")"

  if [[ -z "${DB}" || -z "${KEY}" || -z "${EXPECTED_SHA}" ]]; then
    fail "Manifest entry is incomplete: ${ENTRY}"
  fi
  if [[ "${KEY}" != daily/${DB}/* ]]; then
    fail "Manifest key for ${DB} is not under daily/${DB}/: ${KEY}"
  fi
  if [[ -n "${ONLY_DATABASES}" && ",${ONLY_DATABASES}," != *",${DB},"* ]]; then
    continue
  fi

  ARCHIVE="${WORKDIR}/$(basename "${KEY}")"
  log "Downloading ${KEY}"
  aws s3 cp "s3://${S3_BUCKET}/${KEY}" "${ARCHIVE}"

  SIZE="$(stat -c%s "${ARCHIVE}" 2>/dev/null || stat -f%z "${ARCHIVE}")"
  [[ "${SIZE}" -gt 0 ]] || fail "Downloaded empty archive for ${DB}"

  ACTUAL_SHA="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  if [[ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]]; then
    fail "SHA-256 mismatch for ${DB}: expected ${EXPECTED_SHA} got ${ACTUAL_SHA}"
  fi

  RESTORE_CMD=(
    mongorestore
    --host "${RESTORE_HOST}"
    --port "${RESTORE_PORT}"
    --username "${MONGO_RESTORE_USER}"
    --password "${MONGO_RESTORE_PASSWORD}"
    --authenticationDatabase "${MONGO_AUTH_DB}"
    --gzip
    --archive="${ARCHIVE}"
    --nsInclude="${DB}.*"
  )
  if [[ "${DROP}" -eq 1 ]]; then
    RESTORE_CMD+=(--drop)
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    RESTORE_CMD+=(--dryRun)
    log "Dry-run mongorestore ${DB} (${SIZE} bytes) into ${RESTORE_HOST}:${RESTORE_PORT}"
  else
    log "Restoring ${DB} into ${RESTORE_HOST}:${RESTORE_PORT}"
  fi

  "${RESTORE_CMD[@]}" || fail "mongorestore failed for ${DB}"
  rm -f "${ARCHIVE}"
  RESTORED=$((RESTORED + 1))
done

if [[ "${RESTORED}" -eq 0 ]]; then
  fail "No databases restored. Check --databases against the manifest."
fi

log "Restore finished: ${RESTORED} database(s) for ${TIMESTAMP} into ${RESTORE_HOST}:${RESTORE_PORT}"
