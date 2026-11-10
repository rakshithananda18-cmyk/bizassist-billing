# ops/db-backup - the nightly database backup job (backup.py, deploy_backup.ps1).
FROM python:3.12-slim-bookworm

# pg_dump from PostgreSQL's own apt repository: a pg_dump dumps servers of its
# own major version and older, and Debian's client is older than Supabase's
# server. 18 covers every Supabase release so far.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir google-cloud-storage==2.18.2

WORKDIR /app
COPY backup.py .
USER nobody
CMD ["python", "backup.py"]
