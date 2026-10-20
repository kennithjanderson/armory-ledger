#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

MODE=published
case "${1:-}" in
    "") ;;
    --build) MODE=build ;;
    --help|-h)
        printf 'Usage: %s [--build]\n' "${0##*/}"
        printf 'Prepare a published-image installation; --build selects the local source-build Compose override.\n'
        exit 0
        ;;
    *)
        printf 'ERROR: Unknown option: %s\nUsage: %s [--build]\n' "$1" "${0##*/}" >&2
        exit 2
        ;;
esac

SCRIPT_PATH="${BASH_SOURCE[0]}"
[[ "$SCRIPT_PATH" == */* ]] || SCRIPT_PATH="./$SCRIPT_PATH"
ROOT_DIR="$(cd -- "${SCRIPT_PATH%/*}" && pwd -P)"
cd -- "$ROOT_DIR"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

[[ -d "$ROOT_DIR" && -w "$ROOT_DIR" ]] || fail "Installation directory is not writable: $ROOT_DIR"
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required to generate and validate local secrets. Install python3 and rerun.'
command -v docker >/dev/null 2>&1 || fail 'Docker CLI was not found. Install Docker Engine and Docker Compose v2, then rerun.'
[[ -f compose.example.yaml ]] || fail 'Missing compose.example.yaml. Restore the tracked installation template before continuing.'
[[ -f .env.example ]] || fail 'Missing .env.example. Restore the tracked environment template before continuing.'
[[ -f tools/setup/prepare_install.py ]] || fail 'Missing tools/setup/prepare_install.py. Restore the tracked setup helper before continuing.'

docker --version >/dev/null 2>&1 || fail 'The Docker CLI could not run. Check the Docker installation.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is unavailable. Install the Docker Compose plugin and rerun.'
docker info >/dev/null 2>&1 || fail 'Docker is installed, but the daemon is unavailable or this account lacks access. Start Docker or configure access, then rerun.'

if [[ "$MODE" == build ]]; then
    [[ -f Dockerfile ]] || fail 'Source-build mode requires the tracked Dockerfile.'
    [[ -f compose.build.yaml ]] || fail 'Source-build mode requires compose.build.yaml.'
fi

PROJECT_NAME="$(python3 tools/setup/prepare_install.py project-name --root "$ROOT_DIR")" || fail 'Could not determine the Compose project name.'
HAS_DATABASE_VOLUME=false
VOLUME_NAMES="$(docker volume ls --format '{{.Name}}')" || fail 'Could not inspect Docker volumes. Setup stopped rather than assuming this is a new installation.'
while IFS= read -r volume_name; do
    if [[ "$volume_name" == "${PROJECT_NAME}_postgres_data" ]]; then
        HAS_DATABASE_VOLUME=true
        break
    fi
done <<< "$VOLUME_NAMES"

python3 tools/setup/prepare_install.py prepare \
    --root "$ROOT_DIR" \
    --database-volume "$HAS_DATABASE_VOLUME" \
    --mode "$MODE"

if [[ "$MODE" == build ]]; then
    if ! docker compose -f compose.yaml -f compose.build.yaml config -q >/dev/null 2>&1; then
        fail 'Docker Compose rejected the source-build configuration. Review compose.yaml and .env; no containers were started.'
    fi
else
    if ! docker compose -f compose.yaml config -q >/dev/null 2>&1; then
        fail 'Docker Compose rejected the published-image configuration. Review compose.yaml and .env; no containers were started.'
    fi
fi

printf '\nConfiguration prepared and Compose validation passed. No containers were started.\n'
printf 'Review and edit .env to provide the OIDC values listed above.\n'
if [[ "$MODE" == build ]]; then
    printf '\nSource-build startup command:\n  docker compose -f compose.yaml -f compose.build.yaml up --build -d\n'
else
    printf '\nPublished-image startup commands:\n  docker compose pull\n  docker compose up -d\n'
fi
printf '\nTo validate settings without starting services: docker compose config -q\n'
