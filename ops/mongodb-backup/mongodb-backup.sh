#!/usr/bin/env bash
# ASAT V2 production MongoDB backup (database host 15.204.246.10).
# Full mongodump of every platform database via 127.0.0.1:28395, upload to S3 daily/.
# Schedule: 02:00, 10:00, 18:00 UTC (three full dumps per day). Retention: 30 days.
#
# Requires: mongodump (MongoDB Database Tools), aws CLI, sha256sum.
# Env file: /etc/asat/mongodb-backup.env (see backup.env.example)
# Install and run this on the DATABASE host only — not on 15.204.211.185.
#
# Usage:
#   mongodb-backup.sh                  # normal run (slot from current UTC hour)
#   mongodb-backup.sh --slot 0200      # force slot label (HHMM UTC)
#   mongodb-backup.sh --databases registration
#   mongodb-backup.sh --dry-run        # dump + hash only; no S3 upload

set -euo pipefail

ENV_FILE="${BACKUP_ENV_FILE:-/etc/asat/mongodb-backup.env}"
FORCE_SLOT=""
ONLY_DATABASES=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slot)
      FORCE_SLOT="$2"
      shift 2
      ;;
    --databases)
      ONLY_DATABASES="$2"
      shift 2
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
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi
# Export so aws and child processes see the credentials. systemd already exports
# EnvironmentFile; a manual run only sources this file.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${MONGO_HOST:=127.0.0.1}"
: "${MONGO_PORT:=28395}"
: "${MONGO_BACKUP_USER:?Set MONGO_BACKUP_USER in ${ENV_FILE}}"
: "${MONGO_BACKUP_PASSWORD:?Set MONGO_BACKUP_PASSWORD in ${ENV_FILE}}"
: "${MONGO_AUTH_DB:=admin}"
: "${MONGO_PUBLIC_HOST:=15.204.246.10}"
: "${S3_BUCKET:?Set S3_BUCKET in ${ENV_FILE}}"
: "${AWS_REGION:=us-east-1}"
: "${S3_KMS_KEY_ID:?Set S3_KMS_KEY_ID in ${ENV_FILE}}"
: "${LOCAL_WORKDIR:=/var/lib/asat-mongodb-backup}"
: "${SIZE_RATIO_MIN:=0.5}"

if ! command -v mongodump >/dev/null 2>&1; then
  echo "mongodump not found. Install MongoDB Database Tools on this host." >&2
  exit 1
fi
if [[ -x /usr/local/bin/aws ]]; then
  AWS_CLI=/usr/local/bin/aws
elif command -v aws >/dev/null 2>&1; then
  AWS_CLI="$(command -v aws)"
else
  AWS_CLI=""
fi
if [[ "${DRY_RUN}" -eq 0 && -z "${AWS_CLI}" ]]; then
  echo "aws CLI not found. Install AWS CLI v2 before uploading." >&2
  exit 1
fi
if ! command -v sha256sum >/dev/null 2>&1 || ! command -v awk >/dev/null 2>&1; then
  echo "sha256sum and awk are required." >&2
  exit 1
fi

ALL_DATABASES=(registration cms paymentModule universal phishing notification breach)
if [[ -n "${ONLY_DATABASES}" ]]; then
  IFS=',' read -r -a DATABASES <<< "${ONLY_DATABASES}"
else
  DATABASES=("${ALL_DATABASES[@]}")
fi

SEEN=" "
for DB in "${DATABASES[@]}"; do
  if [[ "${SEEN}" == *" ${DB} "* ]]; then
    echo "Duplicate database '${DB}'" >&2
    exit 2
  fi
  SEEN+="${DB} "
  known=0
  for CANDIDATE in "${ALL_DATABASES[@]}"; do
    if [[ "${DB}" == "${CANDIDATE}" ]]; then
      known=1
      break
    fi
  done
  if [[ "${known}" -eq 0 ]]; then
    echo "Unknown database '${DB}'. Allowed: ${ALL_DATABASES[*]}" >&2
    exit 2
  fi
done

UTC_DATE="$(date -u +%Y-%m-%d)"
UTC_HOUR="$(date -u +%H)"

if [[ -n "${FORCE_SLOT}" ]]; then
  if [[ ! "${FORCE_SLOT}" =~ ^[0-9]{4}$ ]]; then
    echo "--slot must be HHMM, for example 0200, 1000, or 1800" >&2
    exit 2
  fi
  SLOT="${FORCE_SLOT}"
elif [[ "${UTC_HOUR}" == "02" ]]; then
  SLOT="0200"
elif [[ "${UTC_HOUR}" == "10" ]]; then
  SLOT="1000"
elif [[ "${UTC_HOUR}" == "18" ]]; then
  SLOT="1800"
else
  SLOT="$(date -u +%H%M)"
fi

TIMESTAMP="${UTC_DATE}T${SLOT}Z"
STAMP="$(date -u +%Y-%m-%d)T${SLOT}Z"
SOURCE_HOST="${MONGO_PUBLIC_HOST}:${MONGO_PORT}"

WORKDIR="${LOCAL_WORKDIR}/${TIMESTAMP}"
mkdir -p "${WORKDIR}"
trap 'rm -rf "${WORKDIR}"' EXIT

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

export AWS_DEFAULT_REGION="${AWS_REGION}"
export AWS_REGION

retain_until_30d() {
  date -u -d "+30 days" +%Y-%m-%dT%H:%M:%SZ
}

s3_cp_upload() {
  local local_file="$1"
  local s3_key="$2"
  local retain_until
  retain_until="$(retain_until_30d)"
  # High-level "s3 cp" uploads with KMS, including large files.
  # It does not accept Object Lock flags. Retention is a second API call.
  "${AWS_CLI}" s3 cp "${local_file}" "s3://${S3_BUCKET}/${s3_key}" \
    --sse aws:kms \
    --sse-kms-key-id "${S3_KMS_KEY_ID}"
  "${AWS_CLI}" s3api put-object-retention \
    --bucket "${S3_BUCKET}" \
    --key "${s3_key}" \
    --retention "Mode=GOVERNANCE,RetainUntilDate=${retain_until}"
}

previous_size() {
  local db="$1"
  local prev
  prev="$("${AWS_CLI}" s3api list-objects-v2 \
    --bucket "${S3_BUCKET}" \
    --prefix "daily/${db}/${db}-" \
    --query "reverse(sort_by(Contents[?ends_with(Key, '.archive.gz')], &LastModified))[0].Size" \
    --output text 2>/dev/null || echo "None")"
  if [[ -z "${prev}" || "${prev}" == "None" || "${prev}" == "null" ]]; then
    echo "0"
  else
    echo "${prev}"
  fi
}

declare -a MANIFEST_LINES=()

log "Starting backup slot=${SLOT} stamp=${STAMP} dry_run=${DRY_RUN} host=${MONGO_HOST}:${MONGO_PORT} dbs=${DATABASES[*]} aws=${AWS_CLI}"

for DB in "${DATABASES[@]}"; do
  ARCHIVE="${WORKDIR}/${DB}-${STAMP}.archive.gz"
  log "Dumping database ${DB}"
  if ! mongodump \
      --host "${MONGO_HOST}" \
      --port "${MONGO_PORT}" \
      --username "${MONGO_BACKUP_USER}" \
      --password "${MONGO_BACKUP_PASSWORD}" \
      --authenticationDatabase "${MONGO_AUTH_DB}" \
      --db "${DB}" \
      --archive="${ARCHIVE}" \
      --gzip; then
    fail "mongodump failed for ${DB}"
  fi

  SIZE="$(stat -c%s "${ARCHIVE}" 2>/dev/null || stat -f%z "${ARCHIVE}")"
  if [[ "${SIZE}" -le 0 ]]; then
    fail "Empty archive for ${DB}"
  fi

  SHA="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  log "${DB}: size=${SIZE} sha256=${SHA}"

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    MANIFEST_LINES+=("{\"database\":\"${DB}\",\"key\":\"daily/${DB}/${DB}-${STAMP}.archive.gz\",\"size\":${SIZE},\"sha256\":\"${SHA}\"}")
    continue
  fi

  PREV="$(previous_size "${DB}")"
  if [[ "${PREV}" != "0" ]]; then
    # SIZE_RATIO_MIN is a fraction (default 0.5): reject a sudden shrink.
    if ! awk -v s="${SIZE}" -v p="${PREV}" -v r="${SIZE_RATIO_MIN}" 'BEGIN { exit !(s+0 >= p * r) }'; then
      fail "${DB} archive ${SIZE} bytes is below ${SIZE_RATIO_MIN} of previous ${PREV} bytes"
    fi
  fi

  KEY="daily/${DB}/${DB}-${STAMP}.archive.gz"
  s3_cp_upload "${ARCHIVE}" "${KEY}"
  MANIFEST_LINES+=("{\"database\":\"${DB}\",\"key\":\"${KEY}\",\"size\":${SIZE},\"sha256\":\"${SHA}\"}")
  rm -f "${ARCHIVE}"
done

MANIFEST_FILE="${WORKDIR}/manifest-${STAMP}.json"
{
  echo "{"
  echo "  \"timestamp\": \"${STAMP}\","
  echo "  \"slot\": \"${SLOT}\","
  echo "  \"host\": \"${SOURCE_HOST}\","
  echo "  \"databases\": ["
  for i in "${!MANIFEST_LINES[@]}"; do
    if [[ $i -lt $((${#MANIFEST_LINES[@]} - 1)) ]]; then
      echo "    ${MANIFEST_LINES[$i]},"
    else
      echo "    ${MANIFEST_LINES[$i]}"
    fi
  done
  echo "  ]"
  echo "}"
} > "${MANIFEST_FILE}"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "Dry-run complete. Manifest:"
  cat "${MANIFEST_FILE}"
  exit 0
fi

if [[ ${#DATABASES[@]} -eq ${#ALL_DATABASES[@]} ]]; then
  if [[ ${#MANIFEST_LINES[@]} -ne ${#ALL_DATABASES[@]} ]]; then
    fail "Incomplete set: expected ${#ALL_DATABASES[@]} databases"
  fi
fi

MANIFEST_KEY="daily/manifests/${STAMP}.json"
s3_cp_upload "${MANIFEST_FILE}" "${MANIFEST_KEY}"
log "Uploaded manifest s3://${S3_BUCKET}/${MANIFEST_KEY}"
log "Backup completed successfully for ${STAMP}"
