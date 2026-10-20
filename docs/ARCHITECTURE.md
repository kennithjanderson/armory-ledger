# Armory Ledger Architecture

Baseline reviewed: 2026-10-12, commit `1fc2edd` (after release commit `7c260aa`,
tag `v0.1.2`). This describes source code, not the verified state of any running
database or deployment. See [implementation status](IMPLEMENTATION_STATUS.md),
[decisions](DECISIONS.md), and [roadmap](ROADMAP.md) for limitations and plans.

## System overview

Armory Ledger is a self-hosted FastAPI monolith. It serves Jinja HTML pages and
JSON mutation endpoints, uses synchronous SQLAlchemy sessions with PostgreSQL,
and delegates authentication to an external OpenID Connect provider. It has no
separate frontend application, task queue, or scheduler service; a small worker
thread runs inside the application process for durable operations and daily checks.

```text
Browser ── operator-provided HTTPS ingress ── FastAPI/Uvicorn
                                               ├── Authlib ── OIDC provider
                                               ├── Jinja templates / static assets
                                               └── routes / services ── SQLAlchemy ── PostgreSQL
Container entrypoint ── Alembic schema upgrade ────────────────────────────────────┘
```

## Stack and component boundaries

| Component | Implementation and source |
| --- | --- |
| Runtime | Python 3.13 slim container; Uvicorn on port 8000; [Dockerfile](../Dockerfile) |
| Web backend | FastAPI and Starlette middleware; [app/main.py](../app/main.py) |
| Configuration | Pydantic Settings, environment variables and `.env`; [config.py](../app/core/config.py) |
| Persistence | SQLAlchemy declarative models, psycopg driver, PostgreSQL 17 in Compose |
| Schema evolution | Alembic, [migrations/env.py](../migrations/env.py), model metadata |
| Identity | Authlib OIDC client registered as `authentik`; signed Starlette sessions |
| Frontend | Jinja2, vanilla JavaScript, one main stylesheet, static icons |
| Distribution | GitHub release-triggered GHCR container publication |

[requirements.txt](../requirements.txt) lists dependencies without pinned versions.
There is no JavaScript package/build toolchain in the repository.

- `app/api/`: domain routers, page queries, JSON request schemas and handlers.
- `app/services/`: ammunition, inventory, range, accessory, manufacturer, caliber,
  user synchronization, and announcement logic.
- `app/models/`: persistence models, registered through `app/models/__init__.py`.
- `app/schemas/announcement.py`: separate announcement request validation. Most
  other request models are defined in their router modules.
- `app/core/`: configuration, authentication dependencies, admin guard, CSRF.
- `app/db/`: declarative base, engine, and session factory.
- `app/templates/` and `app/static/`: presentation and browser behavior.

This is not a strict service-layer architecture: firearm creation/update logic
lives in `app/api/firearms.py`, and routers perform most page queries. Several
async handlers execute synchronous database operations. Sessions use
`autoflush=False`; services explicitly flush where generated IDs or accumulated
ledger entries are needed. Request dependencies close database sessions; write
paths commit explicitly, with rollback handling in many services.

## Routes and frontend

| Route family | Responsibility |
| --- | --- |
| `/`, `/dashboard`, `/health` | Login page, owner's summary, database connectivity health |
| `/auth/*` | OIDC login/callback, popup completion, session check, local logout |
| `/firearms/*` | List/create/detail/edit and manufacturer lookup/create |
| `/ammunition/*` | Caliber-grouped inventory, lot detail/edit, acquisitions and activity |
| `/accessories/*` | List/create/detail/edit and manufacturer lookup/create |
| `/range/*` | Session list/create/detail/edit |
| `/reference/calibers` | Authenticated shared caliber creation |
| `/admin*` | Admin landing, account identities, read-only references, announcement management |
| `/about` | Authenticated About / Privacy page |

GET handlers generally render HTML; POST/PUT handlers accept JSON. Business
validation errors often use `{success: false, error: ...}` rather than non-2xx
status codes. Missing owned records generally produce 404. Ordinary 401 errors
are redirected to login by the application exception handler. The admin guard
returns JSON authorization failures for mutation requests. FastAPI's default
OpenAPI/docs endpoints are not explicitly disabled or protected.

`base.html` provides global navigation, announcement banners, and footer
clock/status/version. Shared partials provide announcements and admin navigation.
Domain scripts submit JSON with `fetch`; range forms clone firearm/ammunition
row templates. New and edit range sessions share `range/new.html` and
`range-form.js`. `main_templates.py` supplies formatting filters and an
authenticated announcement context processor using a separate database session.
Static asset URLs include the application version for cache busting.

## Authentication, authorization, and isolation

[auth.py](../app/api/auth.py) exchanges the OIDC response, requires subject/email
claims and `Armory User` membership, and synchronizes a local user by immutable
OIDC subject. Membership in `Armory Admin` sets an additional signed-session
boolean; admin authority is evaluated at login, not refreshed from the provider
on each action. Logout clears the local session, not the provider's session.

The session cookie is configured Secure and SameSite=Lax. `get_current_user`
validates its user UUID and confirms the local account still exists.
`AdminAccessMiddleware` protects the `/admin*` prefix; the admin router also
requires `require_admin`. Announcement writes require a session-bound CSRF token.
There is no universal CSRF dependency across all existing inventory mutations.

Firearms, accessories, ammunition lots, and range sessions have `owner_id`.
Queries filter by current user; related-record writes validate ownership.
Inventory transactions and range children inherit isolation through their owned
parents. There is no admin bypass or administrative inventory-browsing route.
The admin Users projection contains only display name, email, local UUID,
creation timestamp, and last login timestamp. It contains no inventory joins,
counts, or private audit records.

Isolation is enforced by application code; the migrations do not establish
PostgreSQL row-level security or composite same-owner foreign keys. Host/database
operators can have infrastructure access outside these application controls.

## Database relationships

Models use UUID primary keys, foreign keys, PostgreSQL enums, timezone-aware
timestamps, and JSONB for audit changes. There are 18 application tables.

| Domain | Main relationships |
| --- | --- |
| Identity | `User` owns private inventory and is referenced as audit actor/announcement author |
| Shared manufacturers | `Organization` has an optional one-to-one `ManufacturerProfile`; aliases point to organizations; typed organization relationships connect two organizations |
| Shared calibers | `CaliberAlias` points to `Caliber`; firearms and ammunition products reference calibers |
| Firearms | `Firearm` references owner, optional manufacturer organization, optional caliber |
| Accessories | `Accessory` references owner, optional organization, optional firearm |
| Ammunition | `Organization → AmmoBrand → AmmoProduct → AmmoLot → AmmoInventoryTransaction` |
| Range | `RangeSession → RangeSessionFirearm → RangeSessionAmmoUsage`; associations reference firearms; usage may reference a lot and inventory transaction |
| Auditing | `AuditEvent` references owner and actor; entity UUID/type are generic, without an entity-table FK |
| Announcements | `Announcement` references creator/updater users and a scheduled time window |

### Firearms and accessories

Firearms record model, optional serial number, type, status, notes, manufacture
date and obtained date with explicit date precision. Purchase price is nullable
`Numeric(12,2)` with a separate nullable three-letter currency. Current forms
write USD and distinguish unknown NULL from recorded zero. Display uses currency
formatting; number inputs use plain decimal text. Status changes do not remove
ownership records or transfer database ownership to another user.

Accessories record quantity, identification/purchase metadata, and either an
assigned firearm or storage location. The service rejects simultaneous firearm
and storage placement and verifies ownership of assigned firearms. Quantity must
be at least one; a database check exists in its migration.

### Shared reference data

Manufacturers and calibers are global. Manufacturer search uses exact canonical
names/aliases and fuzzy suggestions; fuzzy results do not automatically merge
records. Authenticated users can create references. Admin reference views are
read-only. Organization relationships are modeled but have no management UI.

Ammo brands and products are also shared; owned lots reference products. Updating
a lot's product attributes finds or creates another product and repoints that
lot rather than mutating a shared product in place.

### Ammunition inventory

`AmmoLot.id` is the logical inventory identity. `lot_number` is an optional,
nonunique manufacturer label. Every `acquire_ammunition` call creates a new lot
and initial acquired transaction, even when owner, product and lot number match
an existing record. There is no automatic lot merge. See [lot decisions](DECISIONS.md).

Physical quantity is the sum of transactions, not a stored lot balance:

- Add: acquired, returned, adjustment_in.
- Subtract: expended, given, sold, disposed, adjustment_out.
- Quarantined/released enum values exist, but do not change physical balance and
  are not accepted by the manual-activity service.

Manual activity validates a positive quantity and current owned-lot balance.
Date-only activity is recorded at noon UTC. Acquisition-date edits can change
the initial transaction date, so this is not a strictly immutable event store.
Balance checks do not take an explicit row/advisory lock; concurrent removal
requests are an unresolved reconciliation risk.

### Range recording and correction

A session requires at least one firearm and ammunition entry per firearm.
Duplicate firearms are rejected; newly added firearms must have owned status.
Inventory usage creates expenditure transactions; other/borrowed usage does not
touch inventory. Session creation commits its children, transactions and audit
events together.

Edits validate session/child ownership and add compensating adjustment
transactions when quantities, source lots, or included rows change. Historical
sessions may retain firearms no longer in owned status and referenced lots with
zero balance. Initial expenditure links are not a full correction-chain model;
correction transaction IDs also appear in audit JSON.

The range filtering task is implemented in the development working tree as of
2026-10-12. Queries still load only the current user's lots. The shared create/edit
form filters each firearm card's dropdown by exact `Firearm.caliber_id` equality
with `AmmoProduct.caliber_id`, using option metadata rather than label text.
Changing firearms clears incompatible selections; missing caliber/stock states
explain why the list is empty. Other / Borrowed remains available.

Create/update services enforce the same rule after ownership validation. An
existing historical entry can remain mismatched only when its stored association,
firearm, inventory source, lot and quantity are unchanged. This permits notes/date
edits without rewriting history, including after a firearm caliber change. New or
changed entries must match. Referenced exhausted lots remain editable on their
original row. There is no new compatibility mapping, schema change, or migration.
See [test setup and limitations](../tests/README.md).

### Audit, announcements, and About

Audit events cover firearm/accessory/ammunition updates, manual ammunition
activity, and range creation/updates. They do not provide complete creation,
authentication, reference-data, or announcement change history. There is no audit
viewer or purge implementation. Private JSON may contain serials, notes, prices.

Announcements have title, plain-text message, severity, enabled flag, required
start/end instants, and creator/updater metadata. Enabled announcements display
when `starts_at <= now < ends_at` on authenticated page requests. API timestamps
carry an offset or an explicit IANA-zone local schedule; values normalize to UTC.
The admin form now uses the browser timezone by default; see the final-polish
architecture update below.
No polling, dismissal tracking, or scheduler exists.

About separates software identity from installation identity. Optional
`ARMORY_OPERATOR_NAME`, `ARMORY_SUPPORT_EMAIL`, and `ARMORY_SUPPORT_URL` settings
are omitted from the page when unset; no operator is assumed by default.

## Migrations and deployment

The source revision chain, read from files without executing Alembic, is:

```text
56fb742d4bdf initial schema
→ c9b7b47cd357 organization aliases
→ 02e700ff54f3 audit events
→ bb79ac38448f accessories
→ 3ca46faf814f range sessions
→ 5c0a11b43be4 firearm dates/status
→ ba5b6e5573c8 accessory quantity
→ f57a288ed6ed optional serial/purchase price
→ 4d9a9a64bd4f announcements (repository head)
```

The old [schema plan](v0.1.2-schema-plan.md) predates the last two migration files.
Its statements that no migrations exist are historical, not the current baseline.
Applied database revisions were not queried. Firearm downgrade rejects remaining
NULL serials before dropping prices; other downgrades may lose data or retain enum
values. Read each migration before authorizing execution.

[docker-entrypoint.sh](../docker-entrypoint.sh) runs `alembic upgrade head` before
Uvicorn. Starting or recreating an application container can therefore mutate
the database even if the requested container command is not itself a migration.

- Published example: [compose.example.yaml](../compose.example.yaml) uses GHCR,
  loopback port 8000, PostgreSQL 17 on an internal network, health checks, and a
  persistent database volume. HTTPS ingress and OIDC are operator-provided.
- Local development: ignored `compose.yaml` builds source, uses separate dev
  container names and a Cloudflare Tunnel service. No source bind mount or reload
  configuration is present in the reviewed file.
- Distribution: [docker-publish.yml](../.github/workflows/docker-publish.yml)
  builds/pushes version, major.minor, and latest tags on published releases.
- Actual production configuration under `/opt/armory-ledger` was not inspected.
  The public example is a deployment contract, not proof of a live installation.

Ignored local helper scripts can build/start containers, stage commits, and
publish releases. They are not test-only tools. Current script findings and
documentation drift are recorded in [implementation status](IMPLEMENTATION_STATUS.md).

## Shooting Log extension — development working tree, 2026-10-12

The user-facing Range feature is now Shooting Log. Existing `/range` routes,
`RangeSession` models, tables, firearm associations and accounting remain in use.
`range_sessions.activity_type` stores one of `range`, `hunting`, `training`,
`defensive`, or `other`, independent of display labels. A Python string enum,
Pydantic validation and a named database check enforce those values. Storage is
VARCHAR(20), NOT NULL, with both application and server defaults of `range`.
Existing rows acquire `range` through the migration's server default.

The form exposes Activity Type before date/location. It does not affect firearm
or ammunition selection. Create/update audit JSON includes classification.
Older create payloads default to range; updates omitting the field retain the
existing classification. Explicit null and unsupported API values are rejected.

Firearm detail shows Shooting History with activity labels and existing detail
links. Recorded Rounds Fired uses `get_firearm_recorded_rounds`: SUM of current
`RangeSessionAmmoUsage.quantity`, joined through session firearm associations to
the session and firearm. Both session and firearm ownership are checked. Each
usage contributes once; inventory and Other / Borrowed both count. No transaction
join, editable counter, cache, or new firearm column is involved. Usage edits and
removal of usage/firearm rows affect the next aggregate; historical adjustment
transactions do not. There is no session-delete endpoint in this work.

New migration chain tail: `4d9a9a64bd4f -> 82c1f947ad30`. The new revision adds
only activity_type and its check. Downgrade loses classification but retains
sessions, associations, usage, inventory transactions and audit records. No live
database migration has been applied by this task. Review/apply the migration
before running the changed application; normal container startup runs migrations.

Future hunting, training or private incident modules can reference a session UUID
without duplicating usage or inventory deductions. Such modules need separately
reviewed ownership/access rules. Defensive Action is only a classification here.

## Ammunition lot merging — development working tree, 2026-10-13

Architecture review found transaction-derived balances, acquisitions/manual changes
in `ammo_inventory_transactions`, and direct Shooting Log lot references. There
was no lot lifecycle or transfer category. The additive design preserves both
lot UUIDs and every pre-existing transaction/usage; it does not consolidate or
rewrite historical rows.

`AmmoLot.merged_into_lot_id` is nullable and indicates Merged when populated.
`AmmoLotMerge` records a unique source, destination, owner/actor, positive quantity,
and UTC timestamp. The two new ledger categories `merge_out` and `merge_in` share
that merge UUID through `AmmoInventoryTransaction.merge_id`. Both contribute to
physical balance, but neither belongs to manual activity, acquisitions, consumption
or adjustments. Two owner-private AuditEvents reference the same operation.
There are now 19 application tables; no firearm counter or usage reassignment.

Compatibility requires the same owner, active distinct lots, brand (and hence
manufacturer), caliber, grain weight, projectile, designation, SKU and matching
product notes. Product text uses existing whitespace/case normalization. Missing
values only match missing values. Manufacturer lot numbers use whitespace
normalization but remain case-sensitive: both unknown or the same known number
are accepted; known/unknown and different known numbers are rejected. Lot notes
and acquisition dates remain on their original records. Unknown batch numbers do
not imply common manufacturing provenance. Source balance must be positive;
destination may be empty but cannot have a negative balance.

All affected lots are locked with SELECT FOR UPDATE in UUID order before balance
or lifecycle decisions. Manual inventory activity and metadata edits share that
locking rule; Shooting Log writes prelock all submitted/existing lots, and edits
also lock the session. Locks refresh ORM state after waiting. A merge revalidates
compatibility and reviewed balances under lock, appends paired transfers/audits,
marks the source merged and commits atomically. Stale reviews are rejected.
Duplicate submissions encounter merged status; a unique source constraint is an
additional safeguard. These locks target PostgreSQL's normal READ COMMITTED use.

Merged sources remain accessible at their original URL and `/ammunition/archive`.
Active inventory/dashboard queries and new Shooting Log choices exclude them.
All inventory activity and metadata edits on a source are rejected server-side.
Historical Shooting Log usage of a merged lot retains its original association,
source and quantity. Changing/removing that usage or its firearm is rejected;
notes and activity details remain editable. The form disables corresponding
controls. Corrections are not silently redirected to another lot. Reversal is
not supported. An active destination may later be merged, preserving a visible
chain of original links.

Routes added: GET `/ammunition/archive`, GET/POST `/ammunition/{ammo_lot_id}/merge`.
All require the existing authenticated user and owned records. POST additionally
requires the existing session CSRF token, an explicit confirmation, and reviewed
source/destination balances. The UI separates destination selection, review and
confirmation and displays validated success on the destination page.

Migration tail: `82c1f947ad30 -> c7d2a960e148`. It adds the merge table, nullable
lifecycle/transaction FKs, indexes and two PostgreSQL enum labels. No existing rows
are reclassified or moved. Downgrade is allowed only without merge history; enum
labels remain because removing PostgreSQL labels would require type replacement.
No application database migration was executed by this task.

## Merge polish and expenditure descriptions — 2026-10-13

The merge API now returns a relative `redirect_url` built from the committed
operation's destination/merge UUIDs. The client validates success, destination,
same-origin detail path and merge ID before navigation. Request/JSON verification
and browser navigation have separate error handling: navigation failure after a
verified success remains a success with a destination link. A 30-second timeout,
network failure, malformed success response or server error locks the form and
provides source/destination record links; no automatic retry is performed.
Explicit rejections display the server message without redirecting.

Confirmation now uses ammunition specifications, available rounds and added dates,
with UUIDs in collapsed audit details. Review shows the transfer and resulting
balance; Proceed with Merger confirms, and Cancel closes the panel without a write.
Focus moves to the final action after review and returns to Review after Cancel.

`ShootingActivityType.expenditure_description` centralizes labels for new
expenditure notes. Ledger rendering batch-queries direct usage-to-transaction
links for owned EXPENDED transactions. A uniquely associated Shooting Log record
supplies its current activity description. Classification edits therefore change
displayed text without updating stored notes, audit JSON, quantities or balances.
Missing/ambiguous associations retain stored text; there is no inference from
notes, dates or quantities. Acquisitions, corrections and merge transfers are not
relabeled. No schema change or historical data rewrite is required.

## v0.1.3 final polish — development source, 2026-10-13

Reviewed against baseline `1fc2edd` plus the existing development working tree.
Announcement columns remain SQLAlchemy `DateTime(timezone=True)` / PostgreSQL
TIMESTAMPTZ. `active_announcements` still compares enabled windows with database
`now()` (start inclusive, end exclusive), independent of the server's local zone.
No data/schema migration or reinterpretation of existing timestamps is involved.

The create/edit form detects the browser's IANA timezone, falls back to UTC if
unavailable, and allows any server-supported IANA identifier (Chicago/UTC are
suggested). Both endpoints use `LocalSchedule` in
`app/schemas/announcement_schedule.py`: wall-clock values are tried with both
`zoneinfo` folds and round-tripped through UTC. No valid candidate means a DST
gap; two candidates require explicit earlier/later selection. Unique instants
normalize to UTC. `tzdata` supplies a portable IANA database fallback when the
host lacks timezone data; there is no frontend timezone dependency.

`POST /admin/announcements/schedule-preview` is a stateless conversion endpoint,
protected by the same server admin router dependency and CSRF check as writes.
It accepts a local value or a stored offset-bearing instant with a timezone and
returns local display values, candidate occurrences and resolved UTC. Save requests
send each start/end as `{timezone, local_time, occurrence}`; the server repeats
conversion and validates end > start. Existing offset-bearing API requests remain
supported. Extra fields, including a claimed UTC result inside a local schedule,
are rejected. There are no database writes from preview requests.

Timezone changes preserve resolved instants; unresolved wall times are validated
in the new zone. Stale preview responses cannot replace newer field values. Edit
initialization converts stored UTC on the server, including the correct fold.
Native inputs display up to milliseconds; exact original microseconds are kept
separately until a displayed value is edited. This preserves unchanged saves and
repeated timezone changes. The timezone choice is form-local, not a stored user
preference; the announcement list continues to clearly label its UTC columns.
Previews need an authenticated network connection and JavaScript; errors block
saving rather than falling back to a guessed offset.

Ammunition merge history uses `record-back` source/destination links with explicit
visited color, hover underline and visible keyboard outline. UUIDs remain in
expandable lot metadata. Duplicate history markup in the HTML title block was
removed. Record destinations, owner checks, ledger rows and audits are unchanged.

## Date/time and public Changelog polish — 2026-10-14

Source baseline remains `1fc2edd` plus development changes. Shared
`app/static/js/date-time.js` enhances every date/month/date-time input in the base
layout. Calendar disclosure provides direct month and numeric year selection,
keyboard date entry, day buttons, arrow-key movement and Escape/focus return.
It uses ISO date strings and Gregorian validation, never timezone-converts date-only
values. Firearm precision changes explicitly remove/reinitialize the component;
year/approximate-year and unknown semantics remain unchanged. No library/CDN is used.

Date-time controls use a date text/calendar and separate 00–23 hour/00–59 minute
selects. Hidden canonical inputs preserve existing form/API contracts. Unchanged
announcement seconds/microseconds remain intact; an actual date/time edit sets
minute precision. Resolved timezone changes and DST validation still use the
server converter. Only ambiguous values reveal the occurrence selector. UTC
previews use HH:mm with the exact instant retained as tooltip metadata.

Display audit: firearm/accessory created/updated and list timestamps, ammunition
created time, Shooting Log creation timestamps and merge history share the local
formatter. Ordinary system times use YYYY-MM-DD HH:mm; merge audit times and the
footer clock include seconds. UTC administration timestamps remain explicitly
UTC-labeled and use 24-hour seconds. Manufacture/acquisition/purchase dates,
Shooting Log activity dates and date-based ammunition ledger entries remain dates;
no invented time or timezone conversion is added to them. Dashboard has no separate
timestamp formatter. The formatter uses numeric local getters, never locale AM/PM.

`GET /changelog` is public without an authentication dependency. It renders
`app/content/changelog.json` through a small validating loader and Jinja autoescape.
No Markdown/raw HTML renderer, DB table or administration interface is introduced.
The JSON is included by the existing Docker COPY app step. Semantic versions sort
newest first; missing dates/content have neutral fallbacks, and malformed entries
are omitted. The base layout supports anonymous navigation; authenticated pages
retain their existing navigation/context. Main and login footers link to Changelog.

### Public About / Privacy and sign-in styling — 2026-10-14

About / Privacy is now public, like Changelog, superseding earlier references to
an authenticated-only About page. Both use `public_base.html` to select the shared
login footer for anonymous visitors and the application footer for signed-in users.
Session `name` is mapped to the shared navigation's `display_name`. Configured
operator/contact information is publicly visible; unset fields remain omitted.
No private inventory queries or authorization bypasses are introduced.

The anonymous sign-in action uses primary button styling in `public-nav`, separate
from desktop navigation-link selectors. This prevents padding/text-color overrides
and keeps the action visible at mobile widths. Its destination is `/auth/login`.

## Shared release tooling — 2026-10-14

The configuration-free tracked release/schedule wrappers call a standard-library
Python engine under `tools/release/`. Application runtime architecture is unchanged.
Explicit file selection uses a private index and immutable candidate commit/ref;
validation runs an archived candidate using disposable PostgreSQL/application
containers, never the existing Compose stack. The engine saves notes, checksums,
runner snapshot, approval and progress outside application/runtime data.

Systemd user timers persist UTC schedules and recover due interrupted work after
reboot. Lingering/setup require separate operator action. Publication is locked,
noninteractive and pinned to the approved SHA. Tags retain candidate reachability;
scheduled releases never push later main changes. See the documented main-integration
procedure to keep pending candidate features in normal development history.

GitHub release creation and verified GHCR completion are separate stages. The Actions
workflow serializes publications, checks out the release tag, verifies immutable
version identity and conditionally promotes latest/major-minor aliases without
version regression. Completion checks workflow SHA, receipt digest and OCI labels.
No workflow, host timer, live publication or disposable-container run was executed
as part of implementation. Details: [release workflow](RELEASE-WORKFLOW.md).

## Validation-only release checks — 2026-10-14

Validation-only uses the same disposable candidate validator with an explicit private-index source selection, without entering the candidate/state/publication lifecycle. It reports the tested tree and check results; migration heads are verified in the disposable application container.

## Bulk validation selection — 2026-10-14

Validation-only bulk selection uses Git porcelain v2 NUL records and a private index. It requires file-list approval before tree construction and retains the static scans and final VALIDATE gate.

## Reviewed bulk release preparation — 2026-10-14

Manual and scheduled preparation now reuse reviewed bulk selection. Optional --expected-tree gates validation and candidate creation; the private index and immediate pre-creation source/HEAD recheck remain in place.

## v0.1.4 implementation — 2026-10-16

v0.1.4 adds an in-process five-second worker with durable SQLite operational jobs/catalogue outside the restored PostgreSQL database. Shared-volume POSIX worker/maintenance locks coordinate requests and operations. PostgreSQL custom dumps and transactional restore preserve whole-instance records; no persistent user uploads exist. Notification events, recipient state, personal preferences and encrypted SMTP configuration live in PostgreSQL. A 30-second polling bell shows unread notifications only; marking an item read removes it from the bell while leaving it in `/notifications` history. History is retained for 90 days for errors, 30 days for warnings, and 7 days for informational/success notices. Unresolved errors and warnings remain until resolved; a successful backup resolves earlier backup-failure notices. `/settings` manages successful-backup preferences for all users and opt-in restore-initiated in-app/email notices for administrators. Restore notice recipients are queued in the external catalogue before database replacement and the warning is recorded afterward for admins still present. See V0.1.4-OPERATIONS.md for boundaries and recovery.

The worker also polls the public upstream GHCR `latest` manifest once per day,
reads the OCI version label from its `linux/amd64` image configuration, and
compares it with `Settings.app_version`. A newer image creates a deduplicated
informational, admin-scoped event and queues email for administrators when SMTP
is enabled. It follows the mutable registry alias rather than GitHub release
metadata, so notices wait until image promotion succeeds. The check does not send
account or inventory data and never updates the local installation. Its attempt
time is stored in `system_settings` so normal
worker ticks do not poll repeatedly; failures are silent to end users and retried
on the next daily interval.

## v0.1.5-dev.5 ammunition notifications — verified in development

User channel preferences (`ammo_notifications_in_app` and
`ammo_notifications_email`) default off. Each owned ammunition lot separately
stores an optional positive low-inventory threshold and disabled-by-default low
and depleted triggers. Inventory activity creates a private, informational
`NotificationEvent` only when a committed balance crosses from at/above the
threshold to below it, or from positive to zero. Shooting Log create/edit checks
the final balance once per lot so intermediate corrections do not emit multiple
or misleading alerts; depletion takes precedence when both triggers are enabled.
The event has one recipient: the lot owner. Existing notification history,
unread delivery, and email outbox handle the channels. Standard users can update
only their personal ammunition channels; backup/restore preferences and
administrator-scoped notices remain server-side administrator-only. The new
schema revision is `6ec8a2f145bd` after `a47c91e2d563`; it is applied to the
development database. The owner confirmed in-app and email browser acceptance
for low-inventory and reached-zero triggers on 2026-10-20.
