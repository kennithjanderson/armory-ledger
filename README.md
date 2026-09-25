# Armory Ledger

Armory Ledger is a self-hosted firearm, ammunition, accessory, and range activity
inventory application designed for private record keeping.

It provides ownership-aware inventory tracking, ammunition transaction history,
range session logging, and long-term firearm records while keeping application
data under the control of the person hosting it.

## Features

- Firearm inventory and detailed firearm records
- Ammunition product and lot tracking
- Ledger-based ammunition inventory history
- Accessory inventory management with quantity tracking
- Range session logging
- Firearm and ammunition usage tracking for range sessions
- Multi-user ownership isolation
- Manufacturer and organization records
- Shared caliber records and aliases
- OpenID Connect (OIDC) authentication
- Group-based user and administrator authorization
- PostgreSQL database with Alembic migrations
- Automatic database migrations during application startup
- Responsive desktop and mobile interface
- Docker Compose deployment
- GitHub Container Registry distribution
- Reverse-proxy and Cloudflare Tunnel compatible
- Application and database health monitoring

Armory Ledger does not maintain local user passwords. Authentication is handled
through an external OpenID Connect identity provider.

## Quick Start

Armory Ledger is distributed as a container image through the GitHub Container
Registry.

### Requirements

- Docker
- Docker Compose
- An OpenID Connect (OIDC) identity provider

Download the example Compose and environment files:

```bash
curl -O https://raw.githubusercontent.com/kennithjanderson/armory-ledger/main/compose.example.yaml
curl -O https://raw.githubusercontent.com/kennithjanderson/armory-ledger/main/.env.example

cp compose.example.yaml compose.yaml
cp .env.example .env
```

Generate an application session signing secret:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Edit `.env` and configure the PostgreSQL credentials, application session
secret, and OpenID Connect provider.

Start Armory Ledger:

```bash
docker compose up -d
```

Docker Compose will pull the Armory Ledger and PostgreSQL container images and
start the application.

Armory Ledger automatically applies required database migrations before the
application starts. Manual Alembic commands are not required for normal
installation.

Check the running services:

```bash
docker compose ps
```

Check application health:

```bash
curl http://127.0.0.1:8000/health
```

A healthy installation returns information similar to:

```json
{
  "status": "healthy",
  "application": "Armory Ledger",
  "database": "connected",
  "version": "0.1.1"
}
```

The example Compose configuration makes Armory Ledger available on
`127.0.0.1:8000`.

A configured OIDC identity provider is required to sign in.

## Updating

Pull the latest container images and recreate the services:

```bash
docker compose pull
docker compose up -d
```

When a new Armory Ledger container starts, required database migrations are
automatically applied before the application is started.

Application containers can be recreated without removing the PostgreSQL data
stored in the persistent `postgres_data` Docker volume.

Do not remove the PostgreSQL volume unless you intentionally want to delete the
database.

Database backup and restore tooling is planned for a future release. Operators
should maintain appropriate backups of their PostgreSQL data before performing
upgrades.

## Deployment Architecture

Armory Ledger is designed primarily for private, self-hosted deployment.

The application requires an OIDC identity provider and PostgreSQL database:

```text
                    OIDC Provider
                         ^
                         |
                         |
User ---> Reverse Proxy ---> Armory Ledger ---> PostgreSQL
```

The reverse proxy or ingress method is intentionally left to the operator.

The reference deployment used by the project author uses Cloudflare Tunnel and
Authentik:

```text
Internet
   |
   v
Cloudflare
   |
   v
cloudflared
   |
   v
Armory Ledger
   |
   +------> Authentik
   |          (OIDC)
   |
   v
PostgreSQL
```

Cloudflare Tunnel and Authentik are not required components of Armory Ledger.
They are the ingress and identity-provider solutions used by the reference
deployment.

PostgreSQL should not be exposed directly to the Internet.

## Authentication

Armory Ledger does not maintain local passwords.

Authentication is performed through OpenID Connect. The reference deployment
uses Authentik, but Armory Ledger is designed around standard OIDC rather than a
specific identity provider.

Armory Ledger maintains an internal user UUID associated with the immutable
OIDC subject (`sub`) supplied by the identity provider. Email addresses and
display names can therefore be synchronized during login without changing
inventory ownership relationships.

The current authorization model expects the following group claims:

- `Armory User` — permits access to Armory Ledger
- `Armory Admin` — grants application administration privileges

When using Authentik, these can be provided through Authentik groups.

Administrator privileges do not inherently grant access to another user's
private inventory.

## Configuration

Application configuration is supplied through `.env`.

Start with the included example:

```bash
cp .env.example .env
```

Configure the required values for:

- PostgreSQL
- OIDC client ID
- OIDC client secret
- OIDC issuer
- OIDC callback URL
- Application session signing secret

A session signing secret can be generated with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Never commit `.env` or deployment credentials to source control.

### OIDC Callback URL

The callback URL must match the URL configured with your identity provider.

For example:

```text
https://armory.example.com/auth/callback
```

If the externally accessible application URL changes, update both
`OIDC_REDIRECT_URI` and the corresponding redirect/callback URI configured with
the identity provider.

## Reverse Proxy and External Access

Armory Ledger does not require Cloudflare Tunnel.

The example Compose configuration publishes the application only on the Docker
host loopback interface:

```text
http://127.0.0.1:8000
```

This allows a reverse proxy running on the host to forward requests to Armory
Ledger without exposing port 8000 directly on every network interface.

Armory Ledger can be used behind nginx, Nginx Proxy Manager, Caddy, Traefik,
Cloudflare Tunnel, or another HTTP reverse proxy or ingress solution.

Operators using another deployment architecture may modify the Compose
configuration as needed.

Configuration of third-party reverse proxies, TLS certificates, DNS, firewall
rules, NAT, and port forwarding is outside the scope of the Armory Ledger
project.

### Cloudflare Tunnel

Cloudflare Tunnel is one supported deployment option, but it is not required.

When `cloudflared` is attached to the same Docker network as Armory Ledger, the
tunnel can forward traffic to:

```text
http://armory-ledger:8000
```

A Cloudflare-specific `cloudflared` service is intentionally not included in
the public example Compose configuration. This keeps the example deployment
independent of any particular reverse proxy or ingress provider.

## Database and Migrations

Armory Ledger uses PostgreSQL for application data and Alembic for database
schema migrations.

The example Compose deployment stores PostgreSQL data in the persistent
`postgres_data` Docker volume.

Migration files are included in the Armory Ledger container image. During
container startup, Armory Ledger automatically runs:

```bash
alembic upgrade head
```

The application starts only after database migrations complete successfully.
If a migration fails, the application container exits rather than starting new
application code against an incompatible database schema.

Manual migration commands are not required during normal installation or
upgrades.

For development and troubleshooting, the currently applied migration can be
checked with:

```bash
docker compose exec armory-ledger alembic current
```

When developing from source through Docker, a new migration can be generated
with:

```bash
docker compose run --rm -T \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/app" \
  armory-ledger \
  alembic revision --autogenerate -m "migration description"
```

Always review autogenerated migrations before applying them.

## Data and Security

Armory Ledger is intended to store information that may be sensitive, including
firearm ownership and inventory records.

The repository deliberately excludes deployment secrets and private application
data, including:

- `.env`
- Authentication credentials
- OIDC client secrets
- Session signing secrets

Private inventory records are associated with an internal Armory Ledger user
identity. Ownership restrictions are enforced server-side by the application
rather than relying solely on frontend visibility.

Operators are responsible for securing the host, database, identity provider,
backups, reverse proxy, and any other infrastructure used to deploy their
instance.

Do not expose PostgreSQL directly to untrusted networks.

## Building from Source

The published container image is the recommended deployment method.

For development or testing, Armory Ledger can also be built directly from the
repository:

```bash
git clone https://github.com/kennithjanderson/armory-ledger.git
cd armory-ledger

cp .env.example .env
cp compose.example.yaml compose.yaml
```

Because `compose.example.yaml` uses the published container image, change the
Armory Ledger service in your development `compose.yaml` from:

```yaml
image: ghcr.io/kennithjanderson/armory-ledger:latest
```

to:

```yaml
build: .
```

Then build and start the development deployment:

```bash
docker compose build --no-cache armory-ledger
docker compose up -d
```

The locally built container uses the same startup process as the published
image, including automatic database migrations.

## Project Status

Armory Ledger is under active development.

The current release is version `0.1.1`.

Armory Ledger is distributed as a container image through GitHub Container
Registry and automatically applies required database migrations during container
startup.

Armory Ledger is still an early project. Additional functionality and
improvements will be developed as the application continues to mature.

Bugs and feature requests can be submitted through GitHub Issues.

## Contributing

Suggestions, bug reports, and contributions are welcome.

If you find Armory Ledger useful, you are welcome to self-host it, modify it for
your own needs, or contribute improvements that may benefit the broader
project.

Armory Ledger was created by Kennith Anderson.

## License

Armory Ledger is available under the [MIT License](LICENSE).