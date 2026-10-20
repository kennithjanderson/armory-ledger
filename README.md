# Armory Ledger

Armory Ledger is a free, open-source, self-hosted application for tracking
firearms, ammunition, accessories, and range activity. Each installation is
operated by its owner, who controls its application data, infrastructure, and
backups.

## Features

The v0.1.4 release includes:

- Firearm, ammunition, accessory, and range-session records, with ownership
  isolation between application users.
- Optional firearm serial numbers and USD purchase prices.
- Ammunition activity history, caliber-filtered range entries, and Shooting Log
  activity types.
- Ammunition lot merging that preserves transaction and range history.
- Shared manufacturer and caliber reference data, plus read-only admin views.
- OpenID Connect authentication, role-protected administration, and scheduled
  server announcements.
- Whole-instance encrypted backups, restore safeguards, backup health reporting,
  scheduling, and automatic-backup retention.
- An in-app notification center and optional system email notifications.
- Admin-only notices when the published GHCR `latest` image contains a newer
  application version.

See the [changelog](app/content/changelog.json) and
[v0.1.4 operations guide](docs/V0.1.4-OPERATIONS.md) for release details and
recovery behavior.

## Requirements

- Docker Engine and the Docker Compose v2 plugin.
- An OpenID Connect (OIDC) identity provider for user sign-in.
- Host storage for the PostgreSQL volume and encrypted backup files.
- An SMTP relay only if email notifications are wanted. In-app notifications
  do not require SMTP.

Authentik and Cloudflare Tunnel are supported examples, not requirements.
Armory Ledger can sit behind a reverse proxy or another ingress provider. Keep
PostgreSQL on a private Docker network and expose the application through a
trusted HTTPS ingress for remote use.

## Quick Start — Published Image

The published GHCR image is the default installation method.

```bash
git clone https://github.com/kennithjanderson/armory-ledger.git
cd armory-ledger
./get-started.sh
```

The setup script creates `compose.yaml` and a private `.env` when they are
absent. On a fresh installation it generates the PostgreSQL password, session
signing secret, backup encryption key, and separate SMTP password-encryption key.
It preserves existing files and never starts containers.

Edit `.env` and provide the OIDC client ID, client secret, issuer URL, and the
externally reachable callback URL ending in `/auth/callback`. Register that
same callback with your identity provider. The script lists any remaining setup
items without printing generated secrets.

Validate the Compose file and start the published image:

```bash
docker compose config -q
docker compose pull
docker compose up -d
docker compose ps
```

The application applies its database migrations during startup. Open the URL
served by your reverse proxy, or use `http://127.0.0.1:8000` for the example
host-local port. Configure SMTP later under **Admin → Email** if desired.
Automatic backups remain disabled until enabled under **Admin → Backup &
Recovery**.

## Building from Source

Use the source-build mode for development or testing; it does not change the
published-image Compose file.

```bash
./get-started.sh --build
docker compose -f compose.yaml -f compose.build.yaml config -q
docker compose -f compose.yaml -f compose.build.yaml up --build -d
```

The override builds the checkout's Dockerfile as `armory-ledger:local`. The
script still only prepares configuration and validates Compose; the final command
is the explicit service start.

## Configuration

Review the generated `.env` before starting the services. The setup script
generates internal secrets only for a fresh installation. It does not generate
OIDC credentials or SMTP account credentials, and it stops if an existing
installation is missing a database, session, or backup key that may be needed to
access existing data.

See the [configuration reference](docs/CONFIGURATION.md) for every supported
environment variable, defaults, generated secrets, OIDC setup, SMTP settings,
backup storage, and key preservation requirements.

Never commit `.env` or place secrets in Compose files. The repository ignores
local environment files and data, and the Docker build context excludes them.

## Updating

Before upgrading, create and verify an encrypted backup and keep its encryption
key available. Then pull and recreate the published services:

```bash
docker compose pull
docker compose up -d
docker compose ps
```

The application automatically applies migrations at startup. Recreating
containers preserves PostgreSQL data in the `postgres_data` volume and backup
archives in `./data/backups`. **Do not run `docker compose down -v` or remove
these volumes/directories** unless you intend to permanently delete their data.
Backups on the same host do not protect against loss of that host; keep a
protected off-host copy of important archives and the matching encryption key.

## Security and Privacy

- Inventory queries are scoped to the owning application user. An ordinary user
  cannot view another user's inventory.
- Admin pages do not provide inventory-browsing routes or inventory-derived
  counts. Administrator status alone does not bypass application ownership
  checks, including between administrators.
- Administrators can create and download whole-instance backups for recovery.
  Those archives contain all users' private records, so grant Armory Admin only
  to trusted installation operators.
- Cross-user inventory sharing is not implemented. Any future sharing feature
  must require authorization from the inventory owner and preserve owner-controlled
  permissions.
- A person controlling the host, database, Docker daemon, or backups may have
  infrastructure-level access beyond application permissions.
- Operators are responsible for protecting secrets and backups and for complying
  with applicable laws, regulations, and policies. Stored records are not a
  guarantee of legal sufficiency, accuracy, retention, or suitability.

## Documentation and Support

- [Project repository](https://github.com/kennithjanderson/armory-ledger)
- [Report a bug or request a feature](https://github.com/kennithjanderson/armory-ledger/issues)
- [Configuration reference](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security policy](SECURITY.md)
- [Backup and recovery operations](docs/V0.1.4-OPERATIONS.md)
- [Maintainer release workflow](docs/RELEASE-WORKFLOW.md)
- [MIT License](LICENSE)
