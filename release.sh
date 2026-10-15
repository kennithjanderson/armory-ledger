#!/usr/bin/env bash
# --validate-only forwards to isolated validation without preparing a release.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/tools/release/engine.py" manual --repo "$ROOT" "$@"
