# ASAT V2 MongoDB backup — AWS resources

AWS resources for production MongoDB backups are created only from the Terraform
project **ASAT-V2-DEPLOYMENT-BACKEND**, file `5-s3-bucket.tf`.

Do **not** run any shell create script on the database host. Do **not** use SNS.

## Create / update (operators)

```bash
cd D:/office-workspace/aspire/git/github/ASAT-V2-DEPLOYMENT-BACKEND
terraform plan
terraform apply
```

That applies:

- KMS key + alias `alias/asatv2-mongodb-backups`
- S3 bucket `asatv2-mongodb-backups-prod-636494949614` (Object Lock, versioning, SSE-KMS, private)
- Lifecycle: `daily/` current and noncurrent versions expire after 30 days
- IAM user `asatv2-mongodb-backup` (put/get/list + retention; deny delete / bypass governance)
- Parameter Store SecureString parameters (see below)

Per-object Object Lock retention is set by `mongodb-backup.sh` on upload (governance 30 days). There is no `weekly/` or `monthly/` prefix and no bucket-wide default retention.

## Parameter Store (after apply)

Copy these into `/etc/asat/mongodb-backup.env` on **15.204.246.10** only (`chmod 600`):

| Parameter | Env variable |
|---|---|
| `/asat/prod/mongodb-backup/aws.accessKeyId` | `AWS_ACCESS_KEY_ID` |
| `/asat/prod/mongodb-backup/aws.secretAccessKey` | `AWS_SECRET_ACCESS_KEY` |
| `/asat/prod/mongodb-backup/s3.bucket` | `S3_BUCKET` |
| `/asat/prod/mongodb-backup/s3.kmsKeyId` | `S3_KMS_KEY_ID` |

`MONGO_BACKUP_PASSWORD` is not in Parameter Store. Set it on the database host when creating `asatBackup`.

The backup script reads the env file. It does not call SSM at runtime.

## Alerts

```bash
journalctl -u asat-mongo-backup.service -n 200 --no-pager
```

There is no SNS topic for this backup.
