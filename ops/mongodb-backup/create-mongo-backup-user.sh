#!/usr/bin/env bash
# Create the dedicated MongoDB backup reader on the database host.
#
# Run on 15.204.246.10:
#   export MONGO_ADMIN_USER=admin
#   export MONGO_ADMIN_PASSWORD='...'   # rotate; do not commit
#   ./create-mongo-backup-user.sh
#
# Reads MONGO_BACKUP_PASSWORD from /etc/asat/mongodb-backup.env if present.

set -euo pipefail

ENV_FILE="${BACKUP_ENV_FILE:-/etc/asat/mongodb-backup.env}"
ADMIN_USER="${MONGO_ADMIN_USER:?Set MONGO_ADMIN_USER}"
ADMIN_PASSWORD="${MONGO_ADMIN_PASSWORD:?Set MONGO_ADMIN_PASSWORD}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

# Keep the admin credential from the shell. The env file is for the backup user.
MONGO_ADMIN_USER="${ADMIN_USER}"
MONGO_ADMIN_PASSWORD="${ADMIN_PASSWORD}"

: "${MONGO_HOST:=127.0.0.1}"
: "${MONGO_PORT:=28395}"
: "${MONGO_AUTH_DB:=admin}"
: "${MONGO_BACKUP_USER:=asatBackup}"
: "${MONGO_BACKUP_PASSWORD:?Set MONGO_BACKUP_PASSWORD in env or ${ENV_FILE}}"

if ! command -v mongosh >/dev/null 2>&1; then
  echo "mongosh not found. Install mongosh on this host." >&2
  exit 1
fi

DATABASES=(registration cms paymentModule universal phishing notification breach)

ROLES_JSON=""
for DB in "${DATABASES[@]}"; do
  if [[ -n "${ROLES_JSON}" ]]; then
    ROLES_JSON+=", "
  fi
  ROLES_JSON+="{ role: 'read', db: '${DB}' }"
done

# Password is read from the process environment so quotes in the secret do not break the script.
export MONGO_BACKUP_PASSWORD
JS=$(cat <<EOF
db = db.getSiblingDB('${MONGO_AUTH_DB}');
var user = '${MONGO_BACKUP_USER}';
var pwd = process.env.MONGO_BACKUP_PASSWORD;
var roles = [ ${ROLES_JSON} ];
if (!pwd) {
  throw new Error('MONGO_BACKUP_PASSWORD is empty');
}
var existing = db.getUser(user);
if (existing) {
  db.updateUser(user, { pwd: pwd, roles: roles });
  print('Updated user ' + user);
} else {
  db.createUser({ user: user, pwd: pwd, roles: roles });
  print('Created user ' + user);
}
EOF
)

mongosh --quiet \
  --host "${MONGO_HOST}" \
  --port "${MONGO_PORT}" \
  --username "${MONGO_ADMIN_USER}" \
  --password "${MONGO_ADMIN_PASSWORD}" \
  --authenticationDatabase "${MONGO_AUTH_DB}" \
  --eval "${JS}"

echo "Backup user ${MONGO_BACKUP_USER} is ready (read on: ${DATABASES[*]})."
echo "Verify: /opt/asat/mongodb-backup/mongodb-backup.sh --dry-run --databases registration"
