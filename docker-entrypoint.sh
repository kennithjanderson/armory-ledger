#!/usr/bin/env bash
set -Eeuo pipefail

echo "Armory Ledger: applying database migrations..."

alembic upgrade head

echo "Armory Ledger: database migrations complete."
echo "Armory Ledger: starting application..."

exec "$@"