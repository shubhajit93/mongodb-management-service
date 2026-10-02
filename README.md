# ASAT MongoDB Management API

Private FastAPI control plane for ASAT V2 MongoDB backups. It runs on the **database host** (`15.204.246.10`) and calls the shell workers in [ops/mongodb-backup/](ops/mongodb-backup/).

It does **not** replace `mongodump`, `mongorestore`, S3 Object Lock, or the systemd timer (`asat-mongo-backup.timer`). The three daily slots (02:00, 10:00, 18:00 UTC) stay on that timer. The API and the scripts ship in this repository together.

## Architecture

- HTTP API (FastAPI) authenticates with a bearer token
- Backup and restore requests enqueue a single-flight background job
- The job execs `/opt/asat/mongodb-backup/mongodb-backup.sh` or `mongodb-restore.sh` with `--env-file /etc/asat/mongodb-backup.env`
- Job history is stored in local SQLite (`/var/lib/asat-mongodb-management/jobs.db`)
- Backup copies remain in S3 under `daily/`

## Install (database host only)

One installer places both the scripts and the API:

```bash
sudo ./install-on-host.sh
sudo nano /etc/asat/mongodb-backup.env        # Parameter Store + asatBackup password
sudo nano /etc/asat/mongodb-management.env   # set API_TOKEN (16+ chars)
# validate scripts, then enable timer after first successful --full
sudo systemctl enable --now asat-mongodb-management.service
curl -s -H "Authorization: Bearer $API_TOKEN" http://127.0.0.1:8091/api/v1/health
```

Do not overwrite existing env files; the installer keeps them if present.

Default API bind address is `127.0.0.1:8091`. Keep it private. Do not publish this port on the public internet or through the application gateway on `15.204.211.185`.

## Auth

Every `/api/v1/*` route requires:

```http
Authorization: Bearer <API_TOKEN>
```

## Main routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Script/env/timer/Mongo port checks |
| POST | `/api/v1/backups` | Start backup (`slot`, `databases`, `dryRun`) |
| GET | `/api/v1/backups` | List backup jobs |
| GET | `/api/v1/backups/{jobId}` | Backup job detail |
| POST | `/api/v1/restores` | Start restore |
| GET | `/api/v1/restores` | List restore jobs |
| GET | `/api/v1/restores/{jobId}` | Restore job detail |
| GET | `/api/v1/manifests` | List `daily/manifests/` |
| GET | `/api/v1/manifests/{timestamp}` | Fetch one manifest |
| GET | `/api/v1/config` | Redacted backup env view |
| PUT | `/api/v1/config` | Update backup env (secrets write-only) |
| GET | `/api/v1/schedule` | Read timer state |

OpenAPI UI: `http://127.0.0.1:8091/docs`

## Restore safety

- Default restore port is `27018` (scratch)
- Production port `28395` requires `"confirmProduction": "RESTORE_PRODUCTION"`
- `--drop` on production requires the same confirmation phrase
- Only one backup or restore job runs at a time

## Response envelope

```json
{ "success": true, "message": "Backup job accepted", "data": {} }
```

```json
{ "success": false, "message": "A backup or restore job is already running", "data": null }
```

## Local tests

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pytest
```

On Linux use `.venv/bin/pip` and `.venv/bin/pytest`.

## Related

- Operator steps: [RUNBOOK.md](RUNBOOK.md)
- Shell workers: [ops/mongodb-backup/](ops/mongodb-backup/)
- Production policy: **ASAT-V2-BACKEND** `docs/MONGODB_BACKUP_POLICY.md`
- AWS Terraform: **ASAT-V2-DEPLOYMENT-BACKEND** `5-s3-bucket.tf`