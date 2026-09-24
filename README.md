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
- Accessory inventory management
- Range session logging
- Firearm and ammunition usage tracking for range sessions
- Multi-user ownership isolation
- Manufacturer and organization records
- Normalized caliber records and aliases
- OpenID Connect (OIDC) authentication
- Group-based user and administrator authorization
- PostgreSQL database with Alembic migrations
- Responsive desktop and mobile interface
- Docker Compose deployment
- Reverse-proxy and Cloudflare Tunnel compatible
- Application and database health monitoring

Armory Ledger does not maintain local user passwords. Authentication is handled
through an external OpenID Connect identity provider.

## Quick Start

Clone the repository:

```bash
git clone https://github.com/kennithjanderson/armory-ledger.git
cd armory-ledger
```

Create the local configuration files:

```bash
cp .env.example .env
cp compose.example.yaml compose.yaml
```

Generate an application session signing secret:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Edit `.env` and configure the PostgreSQL password and your OpenID Connect
provider.

Build and start Armory Ledger:

```bash
docker compose up -d --build
```

Apply the database migrations:

```bash
docker compose exec armory-ledger alembic upgrade head
```

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
  "version": "0.1.0"
}
```

The example Compose configuration makes Armory Ledger available on
`127.0.0.1:8000`.

A configured OIDC identity provider is required to sign in.

## Deployment Architecture

Armory Ledger is designed primarily for private, self-hosted deployment.

The application itself requires:

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
uses Authentik, but authentication is designed around OIDC rather than local
passwords.

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

## Database Migrations

Armory Ledger uses Alembic for database schema migrations.

Apply all available migrations:

```bash
docker compose exec armory-ledger alembic upgrade head
```

Check the currently applied migration:

```bash
docker compose exec armory-ledger alembic current
```

When developing through Docker, a new migration can be generated directly into
the host source tree with:

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
- User-uploaded documents

Uploaded documents are stored under `storage/documents/` and are excluded from
Git except for the directory placeholder.

Private inventory records are associated with an internal Armory Ledger user
identity. Ownership restrictions are enforced server-side by the application
rather than relying solely on frontend visibility.

Operators are responsible for securing the host, database, identity provider,
backups, reverse proxy, and any other infrastructure used to deploy their
instance.

Do not expose PostgreSQL directly to untrusted networks.

## Project Status

Armory Ledger is under active development.

Version `0.1.0` is the first functional release and includes firearm,
ammunition, and accessory inventory management; ammunition transaction history;
range session logging; multi-user ownership isolation; OIDC authentication; and
containerized deployment.

Additional functionality and improvements will be developed as the application
continues to mature.

Bugs and feature requests can be submitted through GitHub Issues.

## Contributing

Suggestions, bug reports, and contributions are welcome.

If you find Armory Ledger useful, you are welcome to self-host it, modify it for
your own needs, or contribute improvements that may benefit the broader
project.

Armory Ledger was created by Kennith Anderson.

## License

Armory Ledger is available under the [MIT License](LICENSE).