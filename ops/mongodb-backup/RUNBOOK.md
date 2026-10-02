# ASAT V2 MongoDB Backup and Recovery Runbook

Production policy: keep the ASAT V2 production policy in the **ASAT-V2-BACKEND** repository (`docs/MONGODB_BACKUP_POLICY.md`). This runbook and the shell workers live in **mongodb-management-service**.

| Role | Host |
|---|---|
| Application Compose stack | `15.204.211.185` |
| MongoDB + backup job + systemd timer | `15.204.246.10` (port `28395`) |

Redis is out of scope. Do not install or enable the backup timer on the application host.

## Schedule (UTC)

| Slot (UTC) | Bangladesh (UTC+6) | Action | S3 prefix | Retention |
|---|---|---|---|---|
| 02:00 | 08:00 | Full `mongodump` of all 7 databases | `daily/` | 30 days |
| 10:00 | 16:00 | Full `mongodump` of all 7 databases | `daily/` | 30 days |
| 18:00 | 00:00 | Full `mongodump` of all 7 databases | `daily/` | 30 days |

Recovery point: last **successful** slot. Worst accepted loss: about **8 hours**. Objects older than 30 days are deleted. There is no `weekly/` or `monthly/` prefix.

Databases in every full run: `registration`, `cms`, `paymentModule`, `universal`, `phishing`, `notification`, `breach`.

## Install order (database host only)

Do all of the following on **`15.204.246.10`** unless a step says otherwise. Do not enable the timer until the first full upload succeeds.

### 1. Rotate any exposed application MongoDB password

Rotate the admin password on `15.204.246.10`. Update only the application host `.env` `MONGODB_URI` on `15.204.211.185`, then recreate Compose there. Do not put the application password into the backup env file.

### 2. Confirm MongoDB on the database host

```bash
ss -lnt | grep 28395
mongosh "mongodb://127.0.0.1:28395/?authSource=admin" -u admin -p
# db.version()
# try { rs.status() } catch (e) { print(e) }
```

Expect MongoDB 7.x and no replica set.

### 3. Install tools on `15.204.246.10`

MongoDB Database Tools and `mongosh` must already be on the host. Install AWS CLI v2 from Amazon. Do not use `snap install aws-cli`.

```bash
cd /tmp
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
aws --version
command -v mongodump && command -v mongorestore && command -v mongosh && command -v aws
```

The backup IAM user cannot read Parameter Store. Copy the four SecureString values from the AWS console (open the parameter, show the decrypted value) into `/etc/asat/mongodb-backup.env`. Do not put an admin access key on this host.

### 4. Create AWS resources (Terraform only)

In **ASAT-V2-DEPLOYMENT-BACKEND** (not on the database host):

```bash
cd D:/office-workspace/aspire/git/github/ASAT-V2-DEPLOYMENT-BACKEND
terraform plan
terraform apply
```

See [AWS_SETUP.md](AWS_SETUP.md). Copy Parameter Store values into `/etc/asat/mongodb-backup.env` on **`15.204.246.10`**:

- `/asat/prod/mongodb-backup/aws.accessKeyId` → `AWS_ACCESS_KEY_ID`
- `/asat/prod/mongodb-backup/aws.secretAccessKey` → `AWS_SECRET_ACCESS_KEY`
- `/asat/prod/mongodb-backup/s3.bucket` → `S3_BUCKET`
- `/asat/prod/mongodb-backup/s3.kmsKeyId` → `S3_KMS_KEY_ID`

Failures: `journalctl -u asat-mongo-backup.service`. No SNS.

### 5. Install scripts on the database host

```bash
# From mongodb-management-service repo root on 15.204.246.10
sudo ./install-on-host.sh
sudo nano /etc/asat/mongodb-backup.env
```

Put secrets in single quotes (`MONGO_BACKUP_PASSWORD='...'`). An unquoted `$` is expanded by the shell. `asatBackup` is read-only. Before the first restore test, also set `MONGO_RESTORE_USER` and `MONGO_RESTORE_PASSWORD` (or `MONGO_ROOT_USER` and `MONGO_ROOT_PASSWORD`) in that same file.

### 6. Create the MongoDB backup reader

```bash
export MONGO_ADMIN_USER=admin
export MONGO_ADMIN_PASSWORD='...'
sudo -E /opt/asat/mongodb-backup/create-mongo-backup-user.sh
```

### 7. Dry-run and first full upload

```bash
sudo /opt/asat/mongodb-backup/validate-host.sh
sudo /opt/asat/mongodb-backup/validate-host.sh --dry-run
sudo /opt/asat/mongodb-backup/validate-host.sh --full
```

Confirm the manifest under `daily/manifests/` lists all seven databases and `host` `15.204.246.10:28395`.

### 8. Enable the timer (database host)

```bash
sudo systemctl enable --now asat-mongo-backup.timer
systemctl list-timers | grep asat-mongo
```

Confirm the timer clock:

```bash
grep '^Timezone=' /etc/systemd/system/asat-mongo-backup.timer
```

The line must be `Timezone=UTC`. The three runs are 02:00, 10:00, and 18:00 UTC (08:00, 16:00, and 00:00 Bangladesh). Watch one run at each of those hours. Only then treat the policy as in force.

If the host was off at a slot, `Persistent=true` runs the job once at the next boot. That catch-up object uses the actual UTC time in its name (for example `2026-09-29T0317Z`), still under `daily/manifests/`.

### 9. Firewall

Restrict inbound `28395` on `15.204.246.10` to `15.204.211.185` and localhost.

### 10. Book the restore practice

Once a month, restore one database from the latest daily manifest into a scratch port. See [Restore practice](#restore-practice).

---

## Disaster recovery

Choose the newest **complete** manifest under `daily/manifests/`. The `--timestamp` value is the file name without `.json`, exactly `YYYY-MM-DDTHHMMZ` (for example `2026-09-29T0200Z`, `2026-09-29T1000Z`, or `2026-09-29T1800Z`).

The restore user must be able to write. `asatBackup` is read-only. Set `MONGO_RESTORE_USER` and `MONGO_RESTORE_PASSWORD` (or `MONGO_ROOT_USER` and `MONGO_ROOT_PASSWORD`) in `/etc/asat/mongodb-backup.env`.

**Never** restore onto production `127.0.0.1:28395` as the first step.

### Scenario A — one database dropped or corrupted

1. `aws s3 ls s3://$S3_BUCKET/daily/manifests/`
2. Pick the latest timestamp from before the incident. Use the file name without `.json`.
3. Restore that database into a scratch port and verify the data. The script checks SHA-256 before `mongorestore`.

```bash
sudo /opt/asat/mongodb-backup/mongodb-restore.sh \
  --timestamp 2026-09-29T0200Z \
  --host 127.0.0.1 --port 27018 \
  --databases paymentModule
```

4. Stop only the writer service on `15.204.211.185` (for billing: `asat-billing-service`).
5. After the incident owner confirms the database name:

```bash
sudo /opt/asat/mongodb-backup/mongodb-restore.sh \
  --timestamp 2026-09-29T0200Z \
  --host 127.0.0.1 --port 28395 \
  --databases paymentModule \
  --drop
```

6. Start the stopped service. Leave the other six databases untouched.

### Scenario B — database host or data destroyed

1. Stop Mongo-backed services on `15.204.211.185`.
2. Rebuild MongoDB on `15.204.246.10` listening on `28395`.
3. Restore all seven databases from one daily manifest. Omit `--databases` so every database in that manifest is loaded.

```bash
sudo /opt/asat/mongodb-backup/mongodb-restore.sh \
  --timestamp 2026-09-29T0200Z \
  --host 127.0.0.1 --port 28395 \
  --drop
```

4. Recreate `asatBackup` and the application user.
5. Point app host `MONGODB_URI` at `15.204.246.10:28395`, recreate Compose, verify login / invoice / license.
6. Data written after that backup slot is gone.

### Scenario C — application host lost

MongoDB and S3 backups are unaffected. Redeploy Compose on a new app host and set `MONGODB_URI` to `15.204.246.10:28395`.

### Scenario D — backup objects deleted or overwritten

Governance retention (30 days) blocks delete unless governance is bypassed. The backup IAM user is denied `s3:DeleteObject` and `s3:BypassGovernanceRetention`. Versioning keeps replaced objects; restore the version listed in the manifest.

---

## Restore practice

Once a month, on `15.204.246.10`, restore **one** production database from the latest good daily manifest into a scratch target, verify, then remove the scratch target. Rotate so `paymentModule` and `registration` are each tested at least quarterly. This is a restore test, not a second backup copy.

```bash
sudo /opt/asat/mongodb-backup/mongodb-restore.sh \
  --timestamp 2026-09-29T1000Z \
  --host 127.0.0.1 --port 27018 \
  --databases registration
```

| Date (UTC) | Manifest timestamp | Database | Minutes | Operator | Notes |
|---|---|---|---|---|---|
| | | | | | |

---

## Operations reference

```bash
# On 15.204.246.10
sudo systemctl start asat-mongo-backup.service
journalctl -u asat-mongo-backup.service -n 200 --no-pager
systemctl list-timers asat-mongo-backup.timer
aws s3 ls "s3://${S3_BUCKET}/daily/manifests/"
```

Do not copy live data files while MongoDB is running. Do not use the ECR deploy AWS key for backups. Do not run this timer on `15.204.211.185`.
