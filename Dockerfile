FROM python:3.12-slim

# Install postgresql-client for pg_dump/pg_restore, and rsync/ssh for NAS replication
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gzip \
    rsync \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy scripts
COPY scripts/db_backup.py /app/db_backup.py
COPY scripts/verify_backup.py /app/verify_backup.py

# Default entrypoint
ENTRYPOINT ["python", "/app/db_backup.py"]