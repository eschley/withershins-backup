#!/bin/bash
set -e

# Configuration
DB_HOST=${DB_HOST:-withershins-db-cluster}
DB_PORT=${DB_PORT:-5432}
DB_USER=${DB_USER:-postgres}
DB_NAME=${DB_NAME:-withershins}
GCS_BUCKET=${GCS_BUCKET:-"gs://your-project-id-withershins-backups"}
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/tmp/withershins_db_${DATE}.sql.gz"

echo "Starting database backup at $(date)"

# Use pg_dump to create a compressed backup
export PGPASSWORD=${DB_PASSWORD}
pg_dump -h $DB_HOST -p $DB_PORT -U $DB_USER -F p $DB_NAME | gzip > $BACKUP_FILE

echo "Backup created successfully at $BACKUP_FILE. Size: $(du -sh $BACKUP_FILE | cut -f1)"

# Authenticate with GCP if using a service account JSON key (optional depending on Workload Identity setup)
if [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS
fi

# Upload to GCS
echo "Uploading backup to $GCS_BUCKET..."
gsutil cp $BACKUP_FILE $GCS_BUCKET/

# Clean up local file
rm $BACKUP_FILE

echo "Backup and upload completed successfully at $(date)!"
