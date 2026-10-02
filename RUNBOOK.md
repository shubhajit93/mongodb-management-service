# MongoDB management service runbook

Private control API for ASAT V2 MongoDB backups. Run it only on the database host `15.204.246.10`. It calls the shell scripts in [ops/mongodb-backup/](ops/mongodb-backup/). It does not replace `mongodump`, `mongorestore`, or the three daily timer slots.

| Role | Host |
|---|---|
| Application Compose stack | `15.204.211.185` |
| MongoDB, backup scripts, timer, and this API | `15.204.246.10` |

| Item | Path |
|---|---|
| API | `http://127.0.0.1:8091` |
| API unit | `asat-mongodb-management.service` |
| API env | `/etc/asat/mongodb-management.env` (mode `600`) |
| Backup scripts | `/opt/asat/mongodb-backup` |
| Backup env | `/etc/asat/mongodb-backup.env` (mode `600`) |
| Backup timer | `asat-mongo-backup.timer` (02:00, 10:00, 18:00 UTC) |
| Job history | `/var/lib/asat-mongodb-management/jobs.db` |
| Dump scratch | `/var/lib/asat-mongodb-backup` |
| S3 prefix | `daily/` (manifests under `daily/manifests/`) |

Do not open port `8091` on the public internet. Do not add these routes to the application gateway. Do not install this timer or API on `15.204.211.185`.

Production policy stays in **ASAT-V2-BACKEND** `docs/MONGODB_BACKUP_POLICY.md`. AWS bucket, KMS, IAM, and Parameter Store stay in **ASAT-V2-DEPLOYMENT-BACKEND** `5-s3-bucket.tf`.

Databases in every full backup: `registration`, `cms`, `paymentModule`, `universal`, `phishing`, `notification`, `breach`.

---

## 1. Confirm this machine

```bash
hostname -I
ss -lnt | grep 28395
```

`hostname -I` must include `15.204.246.10`. Port `28395` must be listening. If either check fails, stop.

## 2. Install tools

`mongodump`, `mongorestore`, and `mongosh` must already be installed. Install AWS CLI v2 from Amazon. Do not use `snap install aws-cli`.

```bash
cd /tmp
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
/usr/local/bin/aws --version
command -v mongodump && command -v mongorestore && command -v mongosh && command -v aws
python3 --version
```

`aws --version` must show `aws-cli/2`. Python 3.11 or newer is required for the API.

The backup IAM user cannot read Parameter Store. Copy the four decrypted values from the AWS console into the backup env file in the next steps. Do not put an admin AWS key on this host.

## 3. Confirm AWS resources already exist

Terraform apply for the backup bucket is done from **ASAT-V2-DEPLOYMENT-BACKEND**, not from this host. These Parameter Store names must exist in `us-east-1`:

| Parameter | Env line |
|---|---|
| `/asat/prod/mongodb-backup/aws.accessKeyId` | `AWS_ACCESS_KEY_ID` |
| `/asat/prod/mongodb-backup/aws.secretAccessKey` | `AWS_SECRET_ACCESS_KEY` |
| `/asat/prod/mongodb-backup/s3.bucket` | `S3_BUCKET` |
| `/asat/prod/mongodb-backup/s3.kmsKeyId` | `S3_KMS_KEY_ID` |

`S3_KMS_KEY_ID` is the full KMS ARN from the decrypted parameter. Paste it exactly. Do not retype the account id.

`MONGO_BACKUP_PASSWORD` is not in Parameter Store. You choose it on this host when creating `asatBackup`.

## 4. Install scripts and API

Clone this repository on `15.204.246.10`, then from the repo root:

```bash
sudo ./install-on-host.sh
```

That one command:

- Copies `ops/mongodb-backup/` to `/opt/asat/mongodb-backup`
- Installs `asat-mongo-backup.service` and `asat-mongo-backup.timer`
- Leaves the timer **disabled**
- Installs the Python app to `/opt/asat/mongodb-management`
- Installs `asat-mongodb-management.service`
- Leaves the API **disabled**
- Keeps an existing `/etc/asat/mongodb-backup.env` or `/etc/asat/mongodb-management.env`

If those env files did not exist, the installer creates them from the examples. You still must fill the real values.

## 5. Fill `/etc/asat/mongodb-backup.env`

```bash
sudo nano /etc/asat/mongodb-backup.env
sudo chmod 600 /etc/asat/mongodb-backup.env
sudo chown root:root /etc/asat/mongodb-backup.env
```

Every line is blank, a `#` comment, or `NAME=value`. A sentence without `#` makes the backup script fail.

```bash
MONGO_HOST=127.0.0.1
MONGO_PORT=28395
MONGO_AUTH_DB=admin
MONGO_PUBLIC_HOST=15.204.246.10

MONGO_BACKUP_USER=asatBackup
MONGO_BACKUP_PASSWORD='a-password-that-is-not-the-admin-password'

MONGO_RESTORE_USER=admin
MONGO_RESTORE_PASSWORD='the-mongodb-admin-password'

AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=paste-from-aws.accessKeyId
AWS_SECRET_ACCESS_KEY='paste-from-aws.secretAccessKey'
S3_BUCKET=paste-from-s3.bucket
S3_KMS_KEY_ID=paste-the-full-kms-arn-from-s3.kmsKeyId

LOCAL_WORKDIR=/var/lib/asat-mongodb-backup
SIZE_RATIO_MIN=0.5
```

Keep single quotes around `MONGO_BACKUP_PASSWORD`, `MONGO_RESTORE_PASSWORD`, and `AWS_SECRET_ACCESS_KEY`. The quotes are not part of the secret. They stop the shell from changing `$` inside the value.

`MONGO_BACKUP_USER` must be `asatBackup`. If that line is `admin`, `create-mongo-backup-user.sh` can replace the admin user's roles with read-only access.

`asatBackup` is read-only. Restore uses `MONGO_RESTORE_USER`.

## 6. Create the backup MongoDB user

```bash
export MONGO_ADMIN_USER=admin
export MONGO_ADMIN_PASSWORD='the-mongodb-admin-password'
sudo -E /opt/asat/mongodb-backup/create-mongo-backup-user.sh
```

`sudo -E` is required so the script can see the admin password. Success line: `Backup user asatBackup is ready`.

## 7. Check the host, then take the first backup

```bash
sudo /opt/asat/mongodb-backup/validate-host.sh
sudo /opt/asat/mongodb-backup/validate-host.sh --dry-run
sudo /opt/asat/mongodb-backup/validate-host.sh --full
```

- The first command only checks tools, S3, the timer file, and `asatBackup`. It must end with `Validation PASSED`. The timer may still be disabled. That is expected.
- `--dry-run` dumps `registration` locally and does not upload.
- `--full` dumps all seven databases and uploads them to S3. Wait for `Backup completed successfully` and `Full backup finished`.

List the manifest:

```bash
sudo bash -c 'set -a; source /etc/asat/mongodb-backup.env; set +a; aws s3 ls "s3://${S3_BUCKET}/daily/manifests/"'
```

You should see one `.json` file. The timestamp is the file name without `.json`, for example `2026-10-02T1342Z`.

## 8. Turn on the daily schedule

Do this only after step 7 succeeded.

```bash
grep '^Timezone=' /etc/systemd/system/asat-mongo-backup.timer
sudo systemctl enable --now asat-mongo-backup.timer
systemctl list-timers | grep asat-mongo
```

The timer file must contain `Timezone=UTC`. The three runs are 02:00, 10:00, and 18:00 UTC (08:00, 16:00, and 00:00 Bangladesh). After the next scheduled run:

```bash
journalctl -u asat-mongo-backup.service -n 80 --no-pager
```

The log must end with `Backup completed successfully`.

If the host was off at a slot, `Persistent=true` runs the job once at the next boot. That catch-up object uses the actual UTC time in its name and still lands under `daily/manifests/`.

Timer-started backups are **not** rows in the API job database. They appear in `journalctl` and in S3. Jobs started through the API appear in both the API and S3.

## 9. Set the API token and start the API

```bash
sudo nano /etc/asat/mongodb-management.env
```

Set a long random token, at least 16 characters:

```bash
API_TOKEN='paste-a-long-random-token'
BIND_HOST=127.0.0.1
BIND_PORT=8091
BACKUP_ENV_FILE=/etc/asat/mongodb-backup.env
BACKUP_SCRIPT=/opt/asat/mongodb-backup/mongodb-backup.sh
RESTORE_SCRIPT=/opt/asat/mongodb-backup/mongodb-restore.sh
DATA_DIR=/var/lib/asat-mongodb-management
AWS_CLI=/usr/local/bin/aws
PRODUCTION_MONGO_PORT=28395
DEFAULT_RESTORE_PORT=27018
PRODUCTION_CONFIRM_PHRASE=RESTORE_PRODUCTION
```

```bash
sudo chmod 600 /etc/asat/mongodb-management.env
sudo systemctl enable --now asat-mongodb-management.service
systemctl status asat-mongodb-management.service --no-pager
```

The installed unit listens on `127.0.0.1:8091`. Check health. Replace the token with the real `API_TOKEN`:

```bash
curl -s -H "Authorization: Bearer YOUR_API_TOKEN" http://127.0.0.1:8091/api/v1/health
```

`data.healthy` should be `true`. OpenAPI for the frontend is `http://127.0.0.1:8091/docs` on this host only.

Every `/api/v1` call needs:

```http
Authorization: Bearer YOUR_API_TOKEN
```

A missing or wrong token returns HTTP 401 and `{ "success": false, "data": null }`.

---

## 10. Use the API

Save the token in the shell for the examples below. Do not put it in a world-readable file.

```bash
export API_TOKEN='YOUR_API_TOKEN'
export AUTH="Authorization: Bearer ${API_TOKEN}"
```

### Health

```bash
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/health
```

Checks that the backup script, restore script, backup env file, and timer unit exist, and that port `28395` accepts a connection.

### Schedule (read only)

```bash
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/schedule
```

This reports whether the timer is enabled and the next elapse. It does not enable or disable the timer. Use `systemctl` for that.

### Config

GET never returns passwords or the AWS secret. It returns whether each secret is set.

```bash
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/config
```

PUT updates `/etc/asat/mongodb-backup.env`. Secret fields are write-only. The file stays mode `600`. The update is refused while a backup or restore job is running.

```bash
curl -s -X PUT -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"SIZE_RATIO_MIN":"0.5"}' \
  http://127.0.0.1:8091/api/v1/config
```

### Start a backup

Returns immediately with a job id. The script runs in the background. Only one backup or restore may run at a time. A second start returns HTTP 409.

Dry-run (no S3 upload):

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"databases":["registration"],"dryRun":true}' \
  http://127.0.0.1:8091/api/v1/backups
```

Full upload of all seven databases. Omit `databases`. Optional `slot` is `0200`, `1000`, `1800`, or any four digits. If you omit `slot`, the script labels the object from the current UTC hour.

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"dryRun":false}' \
  http://127.0.0.1:8091/api/v1/backups
```

The API runs:

```text
/opt/asat/mongodb-backup/mongodb-backup.sh
  --env-file /etc/asat/mongodb-backup.env
  [--slot HHMM]
  [--databases registration,cms]
  [--dry-run]
```

Poll until `status` is `succeeded` or `failed`. Copy `id` from the start response.

```bash
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/backups/JOB_ID
curl -s -H "$AUTH" "http://127.0.0.1:8091/api/v1/backups?page=1&size=20"
```

`logTail` holds the end of the script output. `stamp` is the manifest timestamp when the script printed one.

### List manifests

```bash
curl -s -H "$AUTH" "http://127.0.0.1:8091/api/v1/manifests?page=1&size=20"
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/manifests/2026-10-02T1342Z
```

The timestamp is the manifest file name without `.json`. It must look like `YYYY-MM-DDTHHMMZ`.

### Restore

Default target is `127.0.0.1:27018`. That port must already be a separate MongoDB you started for the test. This command does not start a scratch server for you.

Scratch restore of one database (no `--drop`):

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"timestamp":"2026-10-02T1342Z","host":"127.0.0.1","port":27018,"databases":["paymentModule"]}' \
  http://127.0.0.1:8091/api/v1/restores
```

Production port `28395` is refused unless the body contains the exact phrase `RESTORE_PRODUCTION`. `--drop` on that port needs the same phrase. Without it, the API does not start `mongorestore`.

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"timestamp":"2026-10-02T1342Z","host":"127.0.0.1","port":28395,"databases":["paymentModule"],"drop":true,"confirmProduction":"RESTORE_PRODUCTION"}' \
  http://127.0.0.1:8091/api/v1/restores
```

Do not send that production call as the first restore. Restore to `27018`, check the data, then restore production only after the incident owner confirms the database name.

Poll:

```bash
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/restores/JOB_ID
```

The API runs:

```text
/opt/asat/mongodb-backup/mongodb-restore.sh
  --env-file /etc/asat/mongodb-backup.env
  --timestamp TIMESTAMP
  --host HOST
  --port PORT
  [--databases paymentModule]
  [--drop]
  [--dry-run]
```

---

## 11. Response shape

Success:

```json
{ "success": true, "message": "Backup job accepted", "data": {} }
```

Error:

```json
{ "success": false, "message": "A backup or restore job is already running", "data": null }
```

Job `status` is `queued`, `running`, `succeeded`, or `failed`.

List routes accept `page` (default 1) and `size` (default 20, maximum 100).

---

## 12. Day-to-day checks

```bash
systemctl status asat-mongodb-management.service --no-pager
journalctl -u asat-mongodb-management.service -n 100 --no-pager
systemctl list-timers asat-mongo-backup.timer
journalctl -u asat-mongo-backup.service -n 80 --no-pager
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/health
curl -s -H "$AUTH" http://127.0.0.1:8091/api/v1/schedule
```

Restart the API after an env or code update:

```bash
sudo systemctl restart asat-mongodb-management.service
```

Re-copy scripts and the API from a new checkout with `sudo ./install-on-host.sh`. Existing env files are kept. Then restart the API. Leave the timer disabled until you intend the schedule to be on.

---

## 13. Monthly restore practice

Once a month, restore one database from the latest manifest into port `27018`, verify it, then remove the scratch MongoDB. Rotate so `paymentModule` and `registration` are each tested at least quarterly. This is a test, not another backup copy.

1. `GET /api/v1/manifests` and pick the newest timestamp.
2. Start a scratch `mongod` on `127.0.0.1:27018`.
3. `POST /api/v1/restores` with that timestamp, `port` `27018`, and one database. Do not set `confirmProduction`.
4. Poll the job until `succeeded`.
5. Check the data with `mongosh`, then stop the scratch server.

---

## 14. When something fails

| What you see | What to do |
|---|---|
| `Install: command not found` from the env file | A line in `/etc/asat/mongodb-backup.env` is not `NAME=value` and does not start with `#`. Fix the file. |
| `asatBackup cannot authenticate` | Run step 6. Confirm `MONGO_BACKUP_USER=asatBackup`. |
| `Unknown options: --object-lock-mode` | The installed `mongodb-backup.sh` is old. Re-run `sudo ./install-on-host.sh` from this repo so upload uses `put-object-retention`. |
| HTTP 409 | A backup or restore job is still `queued` or `running`. Wait, then `GET` that job. |
| HTTP 422 on restore to `28395` | Add `"confirmProduction":"RESTORE_PRODUCTION"`. |
| Health says the script is missing | Run `sudo ./install-on-host.sh` again. |
| Timer fires at Bangladesh local time | `Timezone=UTC` is missing from the timer file. Reinstall from this repo. |
| API job list has no 02:00 backup | That run was started by the timer. Check `journalctl` and `GET /api/v1/manifests`. |

Do not chmod the env files to `777`. Root reads them. The API and the backup unit both run as root because the files are mode `600`.

---

## 15. What this service does not do

- It does not delete S3 objects or bypass governance retention.
- It does not enable the timer for you.
- It does not start a scratch MongoDB on port `27018`.
- It does not call Parameter Store.
- It does not dump through PyMongo. Dump and restore stay `mongodump` and `mongorestore`.
