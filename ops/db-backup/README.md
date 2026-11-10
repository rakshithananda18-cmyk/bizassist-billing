# Nightly cloud database backup (`ops/db-backup/`)

Billing and Field Team share **one** Supabase database. This job copies it every night at 02:00 India time into a private Cloud Storage bucket, `gs://<project>-db-backups`, and keeps 30 days of copies. It runs in the same Google Cloud project as the Field Team API.

- **What's copied:** the whole `public` schema, so every billing and Field Team table, as a `pg_dump` custom-format file (`YYYY/MM/DD/bizassist-*.dump`).
- **Checks before upload:** the dump must read back and contain `users`, `customers`, `invoices`, `invoice_payments` and `ft_tasks`. If not, nothing is uploaded and the job run shows **Failed**.
- **Who can touch the copies:** the job's own account can only *add* files. It can't read, change or delete backups, and nobody outside the project can reach the bucket.
- **Cost:** a minute of Cloud Run a night (inside the free tier), plus storage of 30 copies (a few rupees a month at today's size).

## Set up or update

```powershell
.\ops\db-backup\deploy_backup.ps1 -Project bizassist-task -RunNow
```

`-RunNow` takes a copy straight away and lists the newest files. Options: `-KeepDays 60`, `-Schedule "30 1 * * *"`.

## Check it's working

- **Cloud console:** Cloud Run → Jobs → `bizassist-db-backup` → Executions. Each night should show **Succeeded**.
- **Command line:** `gcloud storage ls -l gs://bizassist-task-db-backups/**` lists the copies.
- **Alert by email (optional):** Monitoring → Alerting → a policy on the Cloud Run Job's failed executions.

## Restore

Restore into a **new, empty** database first (for example a new Supabase project), check it, and only then point the apps at it. Never restore over the live database in place.

1. Download a copy: `gcloud storage cp gs://bizassist-task-db-backups/2026/10/24/bizassist-20261024-203001Z.dump .`
2. Restore it with PostgreSQL 18's `pg_restore`, using the new database's **session** connection string (port 5432):
   `pg_restore --no-owner --no-privileges --dbname "<new database URL>" bizassist-20261024-203001Z.dump`
3. Check the row counts. Then set `DATABASE_URL` to the new database on the billing Space and in Secret Manager (`backend-task\deploy_cloudrun.ps1 -Setup -ResetSecrets`), and redeploy both.
