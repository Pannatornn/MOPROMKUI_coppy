#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
backup_dir="$project_dir/backups"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$backup_dir"
cd "$project_dir"

docker compose exec -T db sh -c \
  'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' \
  > "$backup_dir/morpromkui-$timestamp.dump"

find "$backup_dir" -type f -name 'morpromkui-*.dump' -mtime +14 -delete
echo "Backup completed: $backup_dir/morpromkui-$timestamp.dump"
