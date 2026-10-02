# ASAT V2 MongoDB backup tooling

Shell workers for the standalone MongoDB on the **database host**. This directory lives in the **mongodb-management-service** repository. The FastAPI control plane in the same repo calls these scripts.

| Host | Role |
|---|---|
| `15.204.211.185` | Application Compose stack (`MONGODB_URI` → DB host) |
| `15.204.246.10:28395` | MongoDB + backup job + systemd timer + management API |

Dump uses host `mongodump` against `127.0.0.1:28395`. Three full dumps per day (02:00, 10:00, 18:00 UTC) under `daily/`, retained 30 days. Redis is out of scope.

Install scripts and API together from the repo root:

```bash
sudo ./install-on-host.sh
```

AWS bucket / IAM / KMS / Parameter Store: Terraform in **ASAT-V2-DEPLOYMENT-BACKEND** (`5-s3-bucket.tf`). See [AWS_SETUP.md](AWS_SETUP.md).

| File | Purpose |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | Install order, disaster recovery, restore practice |
| [AWS_SETUP.md](AWS_SETUP.md) | Terraform apply + Parameter Store → env file |
| [mongodb-backup.sh](mongodb-backup.sh) | Full dump + S3 upload to `daily/` |
| [mongodb-restore.sh](mongodb-restore.sh) | Restore from one daily manifest timestamp |
| [create-mongo-backup-user.sh](create-mongo-backup-user.sh) | Create `asatBackup` read user |
| [install-on-host.sh](install-on-host.sh) | Delegates to repo-root installer |
| [validate-host.sh](validate-host.sh) | Host checks, `--dry-run`, `--full` go-live |
| [backup.env.example](backup.env.example) | Env template → `/etc/asat/mongodb-backup.env` |
| [asat-mongo-backup.timer](asat-mongo-backup.timer) | 02:00, 10:00, 18:00 UTC |

Policy: keep the production policy document in **ASAT-V2-BACKEND** (`docs/MONGODB_BACKUP_POLICY.md`).
