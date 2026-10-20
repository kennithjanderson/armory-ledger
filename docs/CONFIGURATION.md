# Configuration Reference

This reference describes configuration in the current v0.1.4 application.
Keep `.env` private. The setup script creates it with mode `0600`; do not
commit it or share it with logs, tickets, or source archives.

## Installation files and storage

- `compose.yaml` is created from `compose.example.yaml` only when absent.
  Existing Compose files are never overwritten.
- The example publishes the application on `127.0.0.1:8000` and does not publish
  PostgreSQL. PostgreSQL is reachable only on the private Compose backend network.
- PostgreSQL data is stored in the `postgres_data` named volume.
- Encrypted archives and the backup operations catalogue are stored in
  `./data/backups`, mounted in the app at `/var/lib/armory/backups`.
  Container recreation preserves both.
- The current application container runs as root. It creates the backup directory
  with mode `0700`, and catalogue, lock, and archive files with mode `0600`.
  Keep the host backup path accessible only to trusted operators. The application
  also needs a local filesystem that supports reliable SQLite and POSIX file locks.

## Environment variables

The application reads `.env` through Compose's `env_file`. Compose also reads
that file for the PostgreSQL substitutions below.

| Variable | Classification | Purpose and behavior |
| --- | --- | --- |
| `POSTGRES_DB` | Defaulted | Database name; example default is `armory_ledger`. |
| `POSTGRES_USER` | Defaulted | Database role; example default is `armory_ledger`. |
| `POSTGRES_PASSWORD` | Generated on fresh setup | PostgreSQL role password. The installer creates a URL-safe random value only for a fresh installation. Never reset it for a database that already contains data. |
| `POSTGRES_HOST` | Defaulted | Compose service name `db`. |
| `POSTGRES_PORT` | Defaulted | PostgreSQL port `5432`. |
| `OIDC_CLIENT_ID` | Operator supplied | Client identifier created by the identity provider. |
| `OIDC_CLIENT_SECRET` | Operator supplied | Client secret issued by the identity provider. Do not generate a substitute. |
| `OIDC_ISSUER` | Operator supplied | OIDC issuer URL for the configured provider/application. |
| `OIDC_REDIRECT_URI` | Operator supplied | Public callback URL registered with the provider, normally `https://your-host/auth/callback`. |
| `SESSION_SECRET` | Generated on fresh setup | Starlette session-cookie signing secret. Changing it invalidates current signed sessions. |
| `ARMORY_BACKUP_ENCRYPTION_KEY` | Generated on fresh setup | Required for backup, import, and restore. Canonical URL-safe base64 of exactly 32 random bytes for AES-256-GCM. Keep a protected off-host copy; changing or losing it makes dependent archives unrecoverable. |
| `ARMORY_SECRET_KEY` | Generated on fresh setup; otherwise preserve | Separate Fernet key used to encrypt the SMTP password stored in the application database. It is not the backup key. Losing/changing it prevents decryption of stored SMTP credentials. |
| `ARMORY_BACKUP_DIR` | Defaulted | Container path for backup storage; default `/var/lib/armory/backups`. |
| `ARMORY_TIMEZONE` | Defaulted | IANA timezone used by backup scheduling; default `UTC`. |
| `ARMORY_WORKER_ENABLED` | Defaulted | Enables the in-process durable-operation, email, backup, and daily update-check worker; default `true`. |
| `ARMORY_BACKUP_MAX_BYTES` | Defaulted | Maximum uncompressed backup payload size; default `2147483648` (2 GiB). |
| `ARMORY_OPERATOR_NAME` | Optional | Operator identity shown on the public About / Privacy page. |
| `ARMORY_SUPPORT_EMAIL` | Optional | Plain contact email shown on the About / Privacy page. |
| `ARMORY_SUPPORT_URL` | Optional | HTTP(S) support URL shown on the About / Privacy page. |
| `APP_NAME` | Optional | Display name; default `Armory Ledger`. |
| `APP_VERSION` | Image managed | The application image supplies the running version. Do not override it during normal deployment. |

The installer generates secrets when configuration is absent, or fills an
unmodified copy of `.env.example`, only when `compose.yaml`, a matching local
PostgreSQL volume, and backup data are absent. If a customized `.env` lacks a
database, session, or backup key, setup stops rather than guessing whether another
database or archive depends on it. Restore the original value from a protected
copy. It never rotates populated values. Existing
`ARMORY_SECRET_KEY` values are validated and preserved; if absent, the installer
does not invent one for a possibly existing database.

`ARMORY_SECRET_KEY` is optional to run the application, but required before
saving SMTP authentication credentials. Generate keys only for a new installation
or when you have established that no existing database records or backup archives
depend on their previous values. The setup script never prints generated values.

## OIDC sign-in

Armory Ledger delegates passwords and authentication to an OIDC provider. Configure
the client ID, secret, issuer, and redirect URI from that provider. The callback
URL must match exactly in both `.env` and the provider client settings. Users need
the `Armory User` group; `Armory Admin` is an additional administrative group.
No local password is created by this application.

## Backups and recovery

Manual and scheduled backups, import, and restore all require a valid
`ARMORY_BACKUP_ENCRYPTION_KEY`. The application uses authenticated AES-256-GCM;
downloads remain encrypted, and restores authenticate the archive before changing
application data. Keep the key separately from the application host and backup
archives. There is no key history or automatic key rotation.

Automatic backups are disabled initially. When enabled in **Admin → Backup &
Recovery**, the default schedule is daily at 03:00 UTC with seven automatic
archives retained. Retention removes only older automatic archives after a
successful automatic backup. Manual, imported, and pre-restore archives remain
until an administrator explicitly deletes them. Operation history is retained for
90 days. Read [v0.1.4 operations](V0.1.4-OPERATIONS.md) before restoring or
changing encryption keys.

## SMTP and notifications

Email is optional and starts disabled. SMTP server settings are configured in
**Admin → Email**, not as SMTP environment variables. The application stores the
SMTP password encrypted in its PostgreSQL settings record using
`ARMORY_SECRET_KEY`. The settings include SMTP host/port, explicit STARTTLS,
implicit TLS, or trusted-relay plaintext mode, optional username/password, sender,
reply-to, public base URL, and a bounded timeout. Do not store SMTP credentials in
Compose files or the `.env` template.

In-app notifications work without SMTP. Administrators manage system-level
notification delivery from their personal preferences; users cannot subscribe to
administrator-only system events. Successful-backup notices are optional per-admin
preferences. The email worker sends queued notices from inside the application;
there is no separate mail container.

The optional `ARMORY_OPERATOR_NAME`, `ARMORY_SUPPORT_EMAIL`, and
`ARMORY_SUPPORT_URL` values may remain blank. Unset values are omitted from the
About / Privacy page.

## Validation

After editing `.env`, validate without printing interpolated secrets:

```bash
docker compose config -q
```

For source-build mode:

```bash
docker compose -f compose.yaml -f compose.build.yaml config -q
```

A successful Compose validation checks the Compose structure and required
database interpolation. It does not authenticate with the OIDC provider or test
SMTP delivery. Configure OIDC before starting the application; configure SMTP
through Admin only if email delivery is desired.
