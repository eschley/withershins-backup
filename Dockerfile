FROM python:3.12-slim

# Install postgresql-client for pg_dump
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the backup script
COPY scripts/db_backup.py /app/db_backup.py

# Set the entrypoint to run the script
ENTRYPOINT ["python", "/app/db_backup.py"]