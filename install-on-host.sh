#!/usr/bin/env bash
# Install MongoDB backup scripts + management API on the database host only: 15.204.246.10
# Does NOT enable the backup timer or the API service. Does NOT overwrite existing env files.
#
# Usage (from a clone of mongodb-management-service on 15.204.246.10):
#   sudo ./install-on-host.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

echo "This installer is for the MongoDB database host (15.204.246.10)."
echo "Application host is 15.204.211.185 — do not install here."
echo

if ! command -v mongodump >/dev/null 2>&1; then
  echo "ERROR: mongodump not found. Install MongoDB Database Tools before continuing." >&2
  exit 1
fi
if ! command -v mongorestore >/dev/null 2>&1; then
  echo "ERROR: mongorestore not found." >&2
  exit 1
fi
if ! command -v aws >/dev/null 2>&1 && [[ ! -x /usr/local/bin/aws ]]; then
  echo "WARNING: aws CLI not found. Install AWS CLI v2 before the first upload." >&2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_DIR="${SCRIPT_DIR}/ops/mongodb-backup"
API_DIR="/opt/asat/mongodb-management"
BACKUP_DIR="/opt/asat/mongodb-backup"
ENV_DIR="/etc/asat"
BACKUP_ENV="${ENV_DIR}/mongodb-backup.env"
API_ENV="${ENV_DIR}/mongodb-management.env"
WORKDIR="/var/lib/asat-mongodb-backup"
API_DATA="/var/lib/asat-mongodb-management"

if [[ ! -d "${OPS_DIR}" ]]; then
  echo "ERROR: missing ${OPS_DIR}" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}" "${API_DIR}" "${ENV_DIR}" "${WORKDIR}" "${API_DATA}"
chmod 755 /opt/asat "${BACKUP_DIR}"
chmod 700 "${WORKDIR}" "${API_DATA}"

# --- Backup scripts + timer units ---
rsync -a --delete \
  --exclude 'AWS_SETUP.md' \
  "${OPS_DIR}/" "${BACKUP_DIR}/" 2>/dev/null \
  || cp -a "${OPS_DIR}/." "${BACKUP_DIR}/"

chmod 755 "${BACKUP_DIR}"/*.sh
chmod 644 "${BACKUP_DIR}"/*.md "${BACKUP_DIR}"/*.service "${BACKUP_DIR}"/*.timer "${BACKUP_DIR}"/*.example 2>/dev/null || true

if [[ ! -f "${BACKUP_ENV}" ]]; then
  cp "${BACKUP_DIR}/backup.env.example" "${BACKUP_ENV}"
  echo "Created ${BACKUP_ENV} from example — set secrets from Parameter Store."
else
  echo "Keeping existing ${BACKUP_ENV}"
fi
chmod 600 "${BACKUP_ENV}"

cp "${BACKUP_DIR}/asat-mongo-backup.service" /etc/systemd/system/
cp "${BACKUP_DIR}/asat-mongo-backup.timer" /etc/systemd/system/

if grep -q '^Timezone=UTC$' /etc/systemd/system/asat-mongo-backup.timer; then
  echo "Timer file sets Timezone=UTC."
else
  echo "WARNING: /etc/systemd/system/asat-mongo-backup.timer is missing Timezone=UTC."
fi

# --- Management API ---
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.git' \
  "${SCRIPT_DIR}/" "${API_DIR}/"

python3 -m venv "${API_DIR}/.venv"
"${API_DIR}/.venv/bin/pip" install --upgrade pip
"${API_DIR}/.venv/bin/pip" install -r "${API_DIR}/requirements.txt"

if [[ ! -f "${API_ENV}" ]]; then
  cp "${API_DIR}/mongodb-management.env.example" "${API_ENV}"
  echo "Created ${API_ENV} — set API_TOKEN before starting the API."
else
  echo "Keeping existing ${API_ENV}"
fi
chmod 600 "${API_ENV}"

cp "${API_DIR}/systemd/asat-mongodb-management.service" /etc/systemd/system/
systemctl daemon-reload

echo
echo "Installed backup scripts: ${BACKUP_DIR}"
echo "Backup env:              ${BACKUP_ENV} (mode 600)"
echo "Installed API:           ${API_DIR}"
echo "API env:                 ${API_ENV} (mode 600)"
echo "Backup timer is NOT enabled."
echo "API service is NOT enabled."
echo
echo "  create user:  MONGO_ADMIN_USER=... MONGO_ADMIN_PASSWORD=... ${BACKUP_DIR}/create-mongo-backup-user.sh"
echo "  validate:     ${BACKUP_DIR}/validate-host.sh"
echo "  dry-run:      ${BACKUP_DIR}/validate-host.sh --dry-run"
echo "  full upload:  ${BACKUP_DIR}/validate-host.sh --full"
echo "  enable timer: systemctl enable --now asat-mongo-backup.timer"
echo "  enable API:   edit ${API_ENV} then systemctl enable --now asat-mongodb-management.service"
echo "  health:       curl -H \"Authorization: Bearer \$API_TOKEN\" http://127.0.0.1:8091/api/v1/health"
