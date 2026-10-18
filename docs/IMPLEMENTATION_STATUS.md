# Armory Ledger Implementation Status

## Current release and branch state — 2026-10-17

Local `main` is fast-forwarded to the published v0.1.3 commit
`614d4694bc4a2dec02630c5d50d02fd4d77ea877`. The v0.1.3 release date is
2026-10-15. Historical status entries below retain the state recorded on their
original dates and are superseded by this section. v0.1.4 remains development
work with a planned release date of 2026-10-22; it has not been committed or
published.

## Baseline and evidence

Reviewed 2026-10-12 at commit `1fc2edd` (README logo update), following `7c260aa`
(`Release Armory Ledger v0.1.2`). Local tag `v0.1.2` points to `7c260aa` and
`app/core/config.py` reports `0.1.2`. Git history is evidence of source release
intent, not proof that a particular image or live deployment is running it.

Evidence reviewed: [README](../README.md), [SECURITY](../SECURITY.md),
[schema plan](v0.1.2-schema-plan.md), models, services, routers, Jinja/JavaScript,
migration files, Docker configuration, release workflow, local helper scripts,
and [range filtering instructions](../instructions/range-ammo-filter.md).
The requested SAO reference directory was inaccessible; no SAO technical details
were imported. No existing root/nested AGENTS.md was found in this checkout.

This review used static source inspection and local Git history. No application,
container, migration, or database commands were run. The owner previously
reported successful initial v0.1.2 development browser testing; this is reported
manual evidence, not an independently reproduced regression suite.

## Implemented in source

“Implemented” below means code exists for the behavior, not that every edge case
has passed automated or runtime testing.

| Area | Verified functionality | Evidence |
| --- | --- | --- |
| Authentication | OIDC login, local identity synchronization, required Armory User group, signed session, local logout | `app/api/auth.py`, `app/core/dependencies.py` |
| Authorization | Server-side admin prefix guard and dependency; login-time admin group evaluation | `app/core/admin_access.py`, `app/api/admin.py` |
| User isolation | Owner-scoped inventory queries and related-record validation, no admin inventory bypass | Inventory routers and services |
| Firearms | Create/list/detail/edit, statuses and date precision, optional serial, nullable Decimal/USD purchase price, update audit | `app/api/firearms.py`, model, templates and form JS |
| Ammunition | Product reuse, owned lots, caliber summaries, acquisition, metadata edits, inventory activity and computed balances | Ammunition and inventory services/router |
| Accessories | Quantity, manufacturer, purchase fields, firearm/storage placement, audited edits | Accessory model/service/router |
| Range sessions | Multiple firearms and ammo rows, inventory or other sources, balance deductions, transactional edits/corrections, history pages | Range service/router/templates/JS |
| References | Shared manufacturers/calibers, canonical/alias resolution, manufacturer suggestions and authenticated creation | Reference services and routes |
| Admin pages | Account-only user projection, read-only manufacturer/caliber views, consistent navigation | `app/api/admin.py`, admin templates |
| Announcements | Create/edit/enable/schedule, UTC validation, escaped text, request-time authenticated display, CSRF for writes | Announcement model/schema/service and shared context |
| About / Privacy | Software/operator separation, optional instance contacts, footer link | About route/template, Settings |
| Deployment source | Docker image, PostgreSQL Compose, startup migrations, release-triggered GHCR publishing | Dockerfile, entrypoint, Compose example, GitHub workflow |
| Migrations | Nine revisions, ending at `4d9a9a64bd4f`; firearm and announcement revisions exist | `migrations/versions/` |

## Partial implementation and known limitations

- **Audit coverage is selective.** Updates and inventory activity are recorded;
  firearm/accessory creation and initial acquisition do not create generic audit
  events. Initial acquisition does create a ledger transaction. Range audit JSON
  is not a complete child-row snapshot. There is no audit UI or immutable-log
  enforcement. Announcement creator/updater metadata is not full change history.
- **Caliber aliases and organization relationships are modeled, but lack
  administration workflows.** Manufacturer alias service code exists without a
  corresponding management route. Read-only admin reference pages are not a
  rename/merge/alias-management feature.
- **Inventory concurrency:** balance validation and transaction insertion have no
  explicit locking, so competing requests may overspend a balance. This is a
  source-identified risk; no concurrency reproduction was run.
- **Range correction linkage:** compensating transactions and audit references
  preserve corrections, but `inventory_transaction_id` is not consistently
  repointed when an existing usage changes source/lot. Consumers must not assume
  it identifies the complete/current expenditure history. Reconciliation design
  and tests remain needed.
- **Quarantine/release:** enum values exist, but no usable quarantine workflow or
  available-versus-physical balance model exists.
- **Scalability:** inventory summaries issue per-lot balance queries; several
  views are unpaginated. Synchronous database operations appear in async handlers.
- **Security lifecycle:** admin group changes take effect on a subsequent login;
  no live group checks. Ownership is application-enforced, not database RLS.
  CSRF protection added for announcements is not universal across mutation routes.
- **Response conventions:** some business errors return success HTTP status with
  a failure JSON envelope. The declared `PUBLIC_PATHS` set is unused; default
  FastAPI docs remain enabled.
- **Deployment repeatability:** Python requirements are unpinned; no dependency
  lockfile or automated test job is present.
- **Deferred functionality:** no purge, reference merges/renames, lot merge,
  backup/restore UI, maintenance model, or document-upload workflow. The storage
  directory is a placeholder. No announcement polling or dismissal tracking.

## Outstanding source-identified defects

| Finding | Evidence and impact |
| --- | --- |
| Settings scope is currently limited | `/settings` now manages each signed-in user's successful-backup notification preferences; broader account and application settings remain unimplemented. |
| Stale model export | `app/models/__init__.py` lists `ManufactureDateConfidence` in `__all__` although the replacement type is `DatePrecision`; wildcard exports can fail. |
| Model/migration constraint mismatch | Migration `ba5b6e5573c8` adds `ck_accessories_quantity_positive`; the Accessory ORM metadata does not declare that check. |

## Documentation and repository inconsistencies

Existing documents were preserved during this documentation task. Interpret
their historical claims using the current code/migration baseline above.

1. README “Pending schema work” and `docs/v0.1.2-schema-plan.md` state that the
   firearm/announcement migration files do not exist and IDs are unassigned.
   Both files now exist: `f57a288ed6ed` then `4d9a9a64bd4f`. Neither this review
   nor Git history alone proves a database has applied them.
2. README still describes development migrations as pending review even though
   Git contains a v0.1.2 release commit/tag. Release documentation needs a later
   status refresh without erasing the historical schema plan.
3. README's migration-generation Compose example uses the normal image
   entrypoint, which runs `alembic upgrade head` first. It is not a read-only
   schema-inspection command and must not be executed casually.
4. `instructions/range-ammo-filter.md` asked for an existing testing framework;
   none existed at the baseline. The working-tree update below adds focused tests.
5. The login page mentions maintenance/documents, but corresponding workflows
   are not implemented.
6. Root-level tracked files named `f57a288ed6ed` and `4d9a9a64bd4f` are empty;
   actual Alembic revisions are Python files under `migrations/versions/`.
   Purpose/cleanup of those empty files requires confirmation; they were left intact.
7. Current ignored `release.sh` now targets a development URL; `rebuild.sh` now
   changes into the development directory. Earlier review findings describing
   production targets are stale. Compose/Git commands in `release.sh` still rely
   on the invocation environment, and the script stages/publishes changes.

## Testing coverage and confidence

At the original baseline, no tracked test files, pytest configuration, test dependency manifest, lint
configuration, frontend test runner, or CI test job were found. The GitHub workflow
builds/publishes an image when a release is published; it is not a regression suite.
The ignored local release script performs HTTP health/login/redirect checks, but
also builds/starts containers and stages/commits/pushes/releases. Do not use it as
an isolated verification command.

Prior development work reported syntax checks and the owner reported initial
browser success. Those do not establish database, security, concurrent-inventory,
or migration-downgrade coverage. No runtime tests were executed for this baseline.

### Range filter working-tree update — 2026-10-12

Implemented exact caliber-ID filtering in the shared new/edit form and service
validation on both create/update. Missing caliber or stock never exposes all
inventory. Other / Borrowed and owner isolation remain intact. Unchanged historical
entries are preserved; new/changed entries must match. No migration is required.

Verification: ten unittest service tests passed using isolated SQLite memory data,
and six Node/jsdom DOM tests passed using the actual rendered form and script.
Coverage includes the nine requested scenarios plus historical mismatches,
exhausted historical lots, ownership rejection, aggregate quantity limits,
corrections and rollback. See [tests/README.md](../tests/README.md).
Live browser, HTTP authorization, PostgreSQL-specific and concurrent-request
testing were not run. No application database, migration, container, or deployment
was touched. The historical-edit policy remains an implementation assumption for
owner review; see DECISIONS.

## Pending work

1. Review and browser-test the implemented range-ammunition filter in development,
   including historical-edit behavior. Source changes are not a deployment.
2. Establish regression coverage and review the defects/risks above.
3. Refresh stale existing release/schema documentation in a separately scoped
   documentation change if desired.
4. Design compatible-lot merging and broader reconciliation improvements before
   making data-model or transaction-history changes.

See [ROADMAP.md](ROADMAP.md) for requested work versus proposals, and
[DECISIONS.md](DECISIONS.md) for questions requiring confirmation.

## Shooting Log working-tree update — 2026-10-12

Implemented activity types (Range Session, Hunting, Training, Defensive Action,
Other), new/edit form selection, list/detail labels, Shooting Log navigation,
Shooting History and Recorded Rounds Fired on firearm details. Existing URLs,
caliber filters, owner checks, inventory deductions and correction workflows are
preserved. The previously noted creation-only range edit heading is fixed as part
of updating the shared form terminology.

Migration `82c1f947ad30` follows `4d9a9a64bd4f`; it adds NOT NULL activity_type,
server default range, and a supported-values check. It has not been applied to an
application database. Tests exercise its upgrade/backfill/check/downgrade on
synthetic SQLite memory data and compile PostgreSQL SQL offline.

Verification now includes service totals/accounting/classification, API schema
validation, actual Jinja page rendering, URL-contract checks and jsdom form tests.
See tests/README.md for commands and limits. No full HTTP/OIDC suite, live browser,
PostgreSQL runtime/concurrency, deployment or application database test was run.
No lot merging or session deletion endpoint is added. Inventory concurrency and
other unrelated pre-existing risks remain. The overall v0.1.3 release is not complete.

## Lot-merging working-tree update — 2026-10-13

Implemented compatible destination selection, review/confirmation with CSRF,
atomic paired transfers and audits, merged-source lifecycle, archive/history,
active-list exclusion, and server-side historical usage protection. Existing
acquisitions, inventory corrections, Shooting Log references and recorded-round
calculations remain intact. The locking changes cover manual activity, lot edits,
Shooting Log create/update and merges, superseding the earlier absence-of-locks
finding for these paths.

Migration `c7d2a960e148` follows `82c1f947ad30`. Source/schema migration tests run
on synthetic SQLite memory tables, with PostgreSQL upgrade SQL compiled offline.
No development or production database migration was applied. Downgrade blocks
populated merge history; reversal remains deferred.

Tests cover compatibility/missing values/batch-number rules, ownership, 200+200
balance conservation, audits, rollback, repeated/stale submissions, historical
corrections, merge chains, source write rejection, actual ASGI routes and Jinja
views with injected identity, and browser DOM confirmation/read-only controls.
Existing range-filter and Shooting Log tests remain in the suite. Live PostgreSQL
concurrency tests are opt-in and remain pending explicit disposable-database
permission; compiled locking SQL and SQLite tests do not prove runtime locking.
OIDC/live browser testing remains pending. See tests/README.md for setup.

No production files, app databases, Docker services, version, commits, tags,
releases or deployments were changed. Overall v0.1.3 is not marked complete.

Final lot-merge verification: 38 Python tests passed, 2 opt-in PostgreSQL concurrency
tests skipped pending authorization, and 10 Node/jsdom tests passed. Python/Jinja/JS
syntax and tracked/new-file whitespace checks passed. No live database was used.

## Development version update — 2026-10-13

At the owner's request, `Settings.app_version` now defaults to `0.1.3`; README's
current version references match. This supersedes the preceding unchanged-version
notes. It does not mark the release complete or establish a deployed version.
Migration application and PostgreSQL concurrency validation remain pending.

## Merge polish verification — 2026-10-13

Implemented compact confirmation, Proceed with Merger/Cancel, validated
server-provided destination redirects, separate navigation error handling,
uncertain-result record links and retry lockout, plus activity-aware expenditure
display and new-transaction descriptions. No migration/accounting redesign.

Investigation: executing the original script/template against the endpoint's
expected HTTP 200 JSON redirected correctly without a warning. Source tracing
showed its broad catch also captured JSON/navigation exceptions, and previous
DOM coverage tested rejection but not success. A navigation exception can therefore
misreport a confirmed commit as uncertain; this defect is now covered and fixed.
The precise exception in the reported browser incident was not available, so its
runtime trigger remains unconfirmed. A console error/response body was requested;
no unsupported claim about that incident's exact cause is made.

Verification: 42 Python tests passed, 2 pre-existing opt-in PostgreSQL concurrency
tests skipped, and 18 JavaScript/DOM tests passed. Coverage includes success,
redirect exceptions, malformed/untrusted responses, timeout/network errors,
explicit 409, no retry, cancellation/focus, all five activity descriptions,
classification-only edits with unchanged inventory/audit notes, multi-row and
multi-firearm usage, and untouched merge/manual/unlinked historical descriptions.
No live browser, deployment, application DB migration or PostgreSQL concurrency
run was performed. The v0.1.3 release is not marked complete.

## v0.1.3 final polish verification — 2026-10-13

Source reviewed at baseline `1fc2edd` plus existing development changes. Implemented
styled merge-history links (including visited/focus states and secondary UUIDs),
removed duplicate history from the title block, and added server-validated IANA
announcement scheduling. Both start/end use UTC previews, gap rejection and explicit
fold choices. Existing UTC/TIMESTAMPTZ storage, request-time visibility, admin/CSRF
authorization, inventory accounting and audit behavior are preserved. No migration
is required for this task, and no existing announcement data was modified.

Added `tzdata` runtime fallback and stateless admin schedule-preview route. Existing
offset-bearing API timestamps remain accepted. Form timezone changes preserve
resolved instants. Exact microseconds survive unchanged edits despite native input
precision limits; stale asynchronous responses cannot overwrite newer conversions,
including timezone changes during initial edit loading. The list remains UTC-labeled;
form timezone preference is not persisted. Previews require JavaScript/network access.

Automated verification: **50 Python tests passed, 2 PostgreSQL concurrency tests
skipped; 24 JavaScript tests passed** (full 23-test run followed by the updated
6-test announcement suite, including the added initial-load race regression).
Python tests include actual schema conversion, synthetic SQLite create/update,
fixed-clock visibility and real admin/CSRF dependency enforcement. DOM tests use
the real form/script and Python converter. Existing inventory, migration-on-synthetic
DB, merge and Shooting Log regressions pass. Python AST, Jinja parsing, JavaScript
syntax and whitespace checks passed, including newly added files.

No live browser, Docker build/start, Alembic command, application DB operation,
production access, commit, push, tag or release was performed. The two existing
v0.1.3 migrations were not changed or applied here. Deployment dependency presence
and actual dev migration head still need operational verification. PostgreSQL
concurrency remains skipped without explicit disposable-database authorization;
SQLite is not proof of PostgreSQL locking or timestamp behavior. The precise cause
of the previously reported merge-success warning remains unconfirmed in a live
browser, although known failure paths have regression coverage.

[V0.1.3-RELEASE-TESTING.md](V0.1.3-RELEASE-TESTING.md) now covers multi-day manual
acceptance, schema checks, ownership, inventory conservation, DST behavior and
production migration/rollback planning. Development source is ready for that testing
once its running build/schema are verified through an authorized workflow.
**v0.1.3 remains pending, not released.**

## Date/time standardization and Changelog — 2026-10-14

Implemented the final [date/time task](../instructions/date-time-standardization-changelog.md)
in the development working tree based on `1fc2edd`. Shared ISO calendar entry now
covers ordinary date inputs and dynamically configured firearm day/month fields;
date/time entry uses separate 24-hour selects. System timestamp display and footer
share a numeric 24-hour formatter. Date-only values, existing UTC storage and
unchanged announcement precision are preserved. Actual date/time edits use minute
precision. Ambiguous-time selectors are hidden for normal/nonexistent times.

Public `/changelog` renders escaped structured repository content, sorted by version,
with fallbacks for missing metadata/content. Historical summaries are based on tags;
v0.1.3 is an undated unreleased draft. No new dependencies or migrations were added.

Verification: **52 Python tests passed, 2 opt-in PostgreSQL tests skipped; 29 Node/DOM
tests passed.** The four shared date/time tests also passed separately in
`Pacific/Kiritimati` and `America/Los_Angeles`. Coverage includes historical years,
leap days, keyboard navigation, all requested 24-hour boundaries, precision
reconfiguration, integrated picker/announcement DST conversion and unchanged saves,
public ASGI access, real base/footer rendering, ordering and escaped content.
All application Python ASTs and Jinja templates parsed, changed JS syntax checks
passed, and `git diff --check` was clean. Source audit found no locale time/AM-PM
formatters or native time-only fields. Existing day-only activity records remain
intentionally date-only.

Safari/Chrome/Firefox/mobile rendering and screen-reader checks were not performed;
no Chrome/Chromium/Firefox/Playwright executable was available on PATH. These remain
explicit release-checklist gates. jsdom tests do not establish visual/accessibility
acceptance. Disposable PostgreSQL concurrency, running dev migration-state checks
and the original reported merge-warning runtime trigger remain pending from earlier
work. No application DB, Docker, Alembic command, production checkout, deployment,
commit, push, tag or release was touched. Version remains 0.1.3, unreleased.

Files added in this task:

- `app/api/changelog.py`
- `app/content/changelog.json`
- `app/services/changelog_service.py`
- `app/static/js/date-time.js`
- `app/templates/changelog.html`
- `tests/date-time.test.cjs`
- `tests/test_changelog.py`

Existing working-tree files updated in this task (earlier work preserved):

- `README.md`
- `app/main.py`
- `app/schemas/announcement_schedule.py`
- `app/static/css/armory.css`
- `app/static/js/admin-announcements.js`
- `app/static/js/armory.js`
- `app/static/js/firearm-form.js`
- `app/templates/admin/announcements/form.html`
- `app/templates/ammunition/detail.html`
- `app/templates/base.html`
- `app/templates/login.html`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`
- `docs/V0.1.3-RELEASE-TESTING.md`
- `tests/README.md`
- `tests/admin-announcements.test.cjs`

### Changelog footer correction — 2026-10-14

Signed-out Changelog visitors now receive the same shared `login_footer.html`
partial as the login page. Signed-in visitors retain the existing application
footer, clock, status and links. A base footer block allows this page-specific
selection; a public footer container aligns the login-style footer with content.
Changed templates: base, login, changelog and new partial; shared CSS and existing
Changelog tests updated. Both Changelog tests pass, including exact anonymous/login
footer equivalence and authenticated footer checks. `git diff --check` passed.
No runtime/database/deployment operations were performed.

### Changelog navigation identity correction — 2026-10-14

The public route previously passed the signed session directly to the base template:
OIDC stores `name`, while the shared navigation reads `display_name`. The route now
maps that presentation field without changing authentication or querying inventory.
Signed-in visitors retain the shared application navigation and conditional admin
link. Anonymous visitors see a Sign in button pointing directly to `/auth/login`.
The session-dependent footer selection remains intact.

Updated `app/api/changelog.py`, `app/templates/base.html` and
`tests/test_changelog.py`. The two Changelog tests pass using the actual OIDC session
field names, checking escaped display names, navigation links, admin visibility,
anonymous login destination and both footers. `git diff --check` passed. No runtime,
database, commit or deployment operation was performed.

### Public About / Privacy and sign-in button correction — 2026-10-14

Fixed conflicting `.app-nav > a` padding/color rules on the anonymous Sign in
button by using a dedicated public navigation container with the existing primary
button classes. It also avoids the mobile rule that hides desktop navigation.
About / Privacy now permits anonymous access and uses the same shared public layout
as Changelog, including session-dependent names, navigation and footers. Added an
About / Privacy link to the shared login footer. Configured operator/support fields
are now public; absent settings still produce no empty installation section.

Updated `app/api/about.py`, `app/main.py`, base/about/changelog templates, new
`app/templates/public_base.html`, login footer partial, shared CSS, README,
architecture/status and `tests/test_changelog.py`. Both focused tests passed,
covering public and signed-in pages, identical authenticated navigation, both
footers, configured/absent contact data and escaping. `git diff --check` passed.
Real-browser visual verification remains pending. No database, commit or deployment
operation was performed.

### v0.1.3 planned release — recorded 2026-10-14

The owner selected **October 15, 2026 (America/Chicago)** as the target release
date. Roadmap and release-testing checklist updated. v0.1.3 remains unreleased;
its actual release date is unset in the Changelog. Existing verification gaps
and final acceptance gates still apply. No release time, automation, commit, push,
tag, publication or deployment was created or executed. Documentation-only change;
`git diff --check` passed.

### Development Changelog release label — 2026-10-14

At the owner's explicit request, the development Changelog now marks v0.1.3 as
released with date **2026-10-15**, and its draft disclaimer has been removed.
This supersedes the earlier instructions to leave this entry undated/unreleased.
It prepares the displayed release notes for the owner's intended October 15 push;
it does not establish that a GitHub release, push, tag or deployment has occurred.
Changed `app/content/changelog.json` and its date/status assertions in
`tests/test_changelog.py`. Both focused tests and `git diff --check` passed.

## Shared manual/scheduled release engine — 2026-10-14

Implemented approved Stages B–E of `instructions/release-workflow.md` in development.
Thin release/schedule wrappers share immutable candidate preparation, explicit file
selection through a private index, version/remote/tag checks, isolated validation,
Changelog/manual/edited notes, approval, user timers and idempotent publication.
Candidate refs keep pending commits reachable; annotated release tags retain the
published candidate. Scheduled mode never pushes a later main tip. Normal development
history integration and manual main fast-forward limits are documented.

User timer definitions include UTC OnCalendar, persistence, boot/inactive recovery
checks and unattended retry. No lingering or installed jobs are changed implicitly;
scheduling requires separately configured lingering and exact interactive approval.
Saved runner/notes hashes reject accidental replacement. Failed candidate validation
stops publication without substituting commits or regenerating approved notes.
Cancellation tombstones pending jobs; publication-in-progress/partial publication
requires explicit recovery rather than a misleading cancellation claim.

GitHub release publication and container verification are distinct milestones.
The Actions workflow pins checkout to the release tag, serializes publication,
verifies existing version image identity, guards latest/major-minor promotion against
newer published/current versions, and emits a digest/SHA/version receipt. The engine
requires a matching successful release workflow and registry image digest/OCI labels
before full success. Queued/running verification remains pending, not successful.

Verification: full Python suite **73 passed, 2 existing PostgreSQL integration tests
skipped** (75 total); all **29 JavaScript tests passed**. The 21 new release tests
cover temporary candidate Git history, private-index preservation, notes modes,
validation failure, tag/network rejection, DST, systemd generation, cancel/reschedule,
restart due checks, locks, partial-failure retry, main drift, runner/note tampering,
container identity and monotonic alias policy. Docker/GitHub/systemd publication
operations are mocked. Focused release tests were rerun after recovery refinements.
Temporary systemd units passed `systemd-analyze --user verify`; workflow YAML,
Python ASTs, shell syntax and tracked/new-file whitespace checks passed.

Read-only `./release.sh --dry-run --version 0.1.3` generated the current Changelog
Markdown sections without Git writes, state, Docker, remote access or jobs. It is a
notes/preparation preview, not evidence of a validated immutable release candidate.
Two exact scanner exceptions document detector source and randomly generated test
credential construction; no general private-reference exceptions were added.

Not performed: real candidate Docker/PostgreSQL validation, real GitHub/registry
publication, active timer installation, lingering changes, actual reboot recovery,
application checkout commits/tags/pushes, production access or deployment. Temporary
Git commits were created only inside disposable test directories. Host credentials,
Docker permissions, persistent test dependencies and selected-file scanner findings
must be reviewed before actual use. Old pre-guard workflow re-runs remain outside the
new latest protection and must not publish aliases. Build dependencies remain unpinned;
SHA/digest verification establishes identity, not bit-for-bit reproducibility.

Required operator setup and all recovery commands are in
[RELEASE-WORKFLOW.md](RELEASE-WORKFLOW.md). No October 15 publication job exists.

Files changed/added for this task (earlier application changes preserved):

- `release.sh` (replaced ignored instance helper with trackable generic wrapper)
- `schedule-release.sh`
- `tools/release/common.py`
- `tools/release/engine.py`
- `tools/release/validation.py`
- `tools/release/image_policy.py`
- `.github/workflows/docker-publish.yml`
- `.gitignore`
- `.release-config.example.json`
- `release-scan-allowlist.json`
- `tests/test_release_workflow.py`
- `tests/README.md`
- `AGENTS.md`
- `README.md`
- `docs/RELEASE-WORKFLOW.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`

Host compatibility check: installed gh 2.45 lacks `api --slurp`; release enumeration
uses explicit pages instead, with a regression test for pagination/network failure.
No GitHub API requests were made during this check. Application HEAD remains `1fc2edd`.

## Validation-only release checks — 2026-10-14

Added validation-only CLI, exact archive/tree verification, per-check results, disposable migration-head verification and cleanup failure reporting. Automated tests mock Docker/network operations and use temporary Git repositories; live disposable Docker validation has not been run for this change.

Verification: full Python suite ran 78 tests (76 passed, 2 PostgreSQL-only skips); after adding interruption/migration-failure coverage, all 25 release-specific tests passed. Wrapper help, shell syntax, Python AST parsing and tracked/new-file whitespace checks passed. No live Docker, application/database changes, publication or scheduling occurred.

## Bulk validation selection — 2026-10-14

Implemented --include-all-changes with explicit selection approval, rename handling, ignored-file exclusion and unsafe-file rejection. Existing individual selection and publication behavior remain available. No live Docker validation or publication was initiated.

Bulk-selection verification: 29 release-specific tests passed; full Python suite ran 83 tests (81 passed, 2 PostgreSQL-only skips). CLI help, Python AST parsing, changed/new-file whitespace and git diff --check passed. No Docker operations, commits, pushes, tags, scheduling or publication were performed.

## Review-patch scan correction — 2026-10-14

Removed the redundant generic review.patch scan from validate_only. The complete
candidate source-tree scan and exact source-path/rule/line-hash exceptions remain
unchanged. The exact Git diff is still displayed and VALIDATE approval remains
mandatory before disposable validation. No scanner rules or exceptions changed.

All 30 release-workflow tests passed, including the actual approved detector,
unapproved sensitive content rejection, approval cancellation, index/working-tree
preservation and absence of release state/ref/publication/timer side effects.
Tests used temporary repositories and mocked disposable validation; no live Docker
validation or application database operations were performed.

## Disposable PostgreSQL bridge correction — 2026-10-14

Validation now creates a uniquely named non-internal bridge instead of an internal
network, retaining random credentials and 127.0.0.1-only dynamic port publication
for PostgreSQL and the candidate application. It never joins application networks.
All 30 release-workflow tests passed, including bridge/port configuration and
container/network/image/environment-file cleanup on success and failure.

A disposable PostgreSQL 17 smoke test on Docker 29.3.0 passed network inspection,
pg_isready, dynamic localhost port discovery and a host PostgreSQL protocol
connection. Removal of its container, network and temporary credential file was
verified. The existing PostgreSQL base image was reused and retained. No candidate
application build/start or full release validation was run in this task. No real
application database, Compose configuration, release or publication was modified.
Python AST, changed-file whitespace and git diff --check passed.

## Reviewed bulk release preparation — 2026-10-14

Implemented reviewed bulk selection for manual/scheduled preparation and optional full expected-tree SHA validation. No real candidate, timer, publication, Docker operation or application database change was performed for this task.

All 35 release-workflow tests passed using temporary Git repositories and mocks. Coverage includes manual/scheduled bulk selection, matching/mismatching tree guards, source changes during review, approval gates, future scheduling, lingering rejection and no unintended publication/timer operations. Python AST, Bash wrapper syntax, changed/new-file whitespace and git diff --check passed. The previously user-validated tree is not evidence that these new edits have passed live release validation.

## v0.1.4 implementation and verification — 2026-10-17

Implemented Backup & Recovery, scheduler/retention, administrator health, encrypted
system mail, persistent recipient-owned notifications and live polling bell.
Application version is 0.1.4; the changelog entry remains unreleased, with a planned
date of 2026-10-22. Added migration `d914b7ce203a` after `c7d2a960e148`; applied only
to disposable PostgreSQL test data,
not the normal development/production database. Existing users must reauthenticate
to synchronize the new local admin membership field. Backup downloads are an
explicit whole-instance operator privilege; privacy/security documentation updated.

GitHub Latest promotion now occurs after image verification in the serialized
publication workflow and only for the newest stable version. No existing release,
saved scheduled runner, Git tag or active timer was changed.

Verification evidence:

- Full synthetic Python regression suite: prior baseline 107 tests, 105 passed, 2
  existing opt-in PostgreSQL concurrency tests skipped. New encryption/date checks
  are recorded below.
- Node/jsdom suite: 30 passed; new bell test checks polling, escaping, unread state,
  explicit read action and Escape/focus behavior.
- A freshly built PostgreSQL-client-equipped image and two newly named disposable
  Docker containers exercised actual migrations through the new head on PostgreSQL
  17. Runtime app/tests were mounted read-only from this checkout; all data were
  synthetic and separate from the normal development database.
- `tests/recovery_exercise.py` passed archive round trip, inventory/account/settings
  and Shooting Log relationship comparisons, retained pre-restore archives, injected
  post-mutation failure with verified rollback, clean-install offline CLI recovery,
  historical pending-mail cancellation, catalogue/connection reopening, health,
  authenticated admin pages, non-admin rejection and CSRF rejection across the new
  privileged mutation routes. No persistent uploads exist to restore in this version.
- Temporary test containers/network/image removed. Base images/build cache were
  not pruned. No real SMTP delivery occurred; SMTP tests used mocks.
- Python ASTs, Jinja parsing, JavaScript syntax and whitespace checks passed.

The final rerun used the existing temporary Python and jsdom test environments;
no dependencies were installed into this checkout. The latest-release regression
test verifies that image promotion invokes GitHub's `--latest` edit only when the
target is the newest stable release. The scheduled release uses this same
serialized publication workflow after image identity verification; no GitHub
publication was performed.

Remaining acceptance: manual browser/layout screenshots, real identity-provider
role-change acceptance and operator-configured SMTP/TLS end-to-end delivery. These
are not claimed by mocked SMTP/DOM tests. Restore supports exact v0.1.4/schema only,
requires the external SMTP key to decrypt saved credentials, and requires a shared
local backup volume with flock/SQLite support. Remote multi-host deployments are
not supported by this coordination design. See V0.1.4-OPERATIONS.md.

Files touched for this task (earlier uncommitted changes preserved):

- `.dockerignore`, `.env.example`, `.github/workflows/docker-publish.yml`, `Dockerfile`,
  `compose.example.yaml`, `requirements.txt`, `README.md`, `SECURITY.md`
- `app/api/auth.py`, `app/api/operations.py`, `app/core/config.py`,
  `app/core/dependencies.py`, `app/core/maintenance.py`, `app/main.py`, `app/recovery.py`
- `app/models/__init__.py`, `app/models/user.py`, `app/models/notification.py`
- `app/services/user_service.py`, `app/services/backup_service.py`,
  `app/services/notification_service.py`, `app/services/worker.py`
- `app/content/changelog.json`, `app/static/css/armory.css`,
  `app/static/js/admin-operations.js`, `app/static/js/notifications.js`
- `app/templates/base.html`, `app/templates/about.html`,
  `app/templates/partials/admin_navigation.html`, `app/templates/admin/backups.html`,
  `app/templates/admin/email.html`, `app/templates/notifications.html`
- `migrations/versions/d914b7ce203a_notifications.py`, `tools/release/image_policy.py`
- `tests/test_operations.py`, `tests/recovery_exercise.py`, `tests/notifications.test.cjs`,
  `tests/test_announcement_schedule.py`, `tests/test_changelog.py`,
  `tests/test_release_workflow.py`, `tests/README.md`
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/IMPLEMENTATION_STATUS.md`,
  `docs/ROADMAP.md`, `docs/RELEASE-WORKFLOW.md`, `docs/V0.1.4-OPERATIONS.md`

### Backup encryption, persistent development storage and planned release date — 2026-10-17

Inspection found that v0.1.4 archives were plaintext tar files; only stored SMTP
passwords used encryption. Backup archives now use a streaming AES-256-GCM envelope
with a URL-safe base64 32-byte key from `ARMORY_BACKUP_ENCRYPTION_KEY`. Missing or
malformed keys stop creation before database dumping. Authentication and version
validation happen before restore creates a pre-restore snapshot or mutates the DB.
Downloads stream ciphertext unchanged. Plaintext dump/tar staging is restricted to
private temporary directories and removed after operations. Added tests for
encryption/decryption, raw downloads, wrong-key no-mutation, and malformed/missing
key failure. No key history/rotation support was introduced.

Both Compose files now bind `./data/backups` to `/var/lib/armory/backups`, and that
host path is ignored by Git. The existing development Compose file was updated and
the directory is private mode 0700. The development `.env` was inspected without
printing values. Its original `ARMORY_BACKUP_ENCRYPTION_KEY` was malformed. After
explicit administrator authorization on 2026-10-17, it was replaced with a newly
generated, format-verified 32-byte key; the file is now mode 0600. Compose resolution
was checked privately and the application receives the matching value. No old
backup archives were present in the former ephemeral container store; its catalogue
held only worker heartbeat and notification status. The rebuild preserved the
PostgreSQL development volume.

Changelog v0.1.4 now has planned date `2026-10-22` and remains marked unreleased. Its
public page labels the date as planned. A uniqueness/date regression test was added.
No release/tag was created.

Verification for this update: the full Python suite passed **109 tests with 2
existing opt-in PostgreSQL tests skipped**; all **30 JavaScript tests passed**.
Both Compose configurations resolve the bind mount to `/var/lib/armory/backups`,
and the host directory is mode 0700. The existing development rebuild completed;
the application and PostgreSQL containers are running, `/health` reports healthy,
and the app mount points to `/opt/armory-ledger-dev/data/backups`. The PostgreSQL
volume was preserved. Backup health reports schema ready, storage writable and
encryption ready. The operator must keep a protected copy of the key off-host.

A separate disposable PostgreSQL 17 test passed encrypted backup creation, raw
ciphertext download, correct-key decryption/restore, incorrect-key rejection before
database mutation, recovery safeguards and recovery after application-container
recreation. Five encrypted archives remained byte-for-byte unchanged and readable
after recreation against the temporary bind mount. Disposable containers, network
and files were removed. Neither development nor production application data was
restored or used as test data. `git diff --check` passed. No release, tag, commit,
push or production deployment was performed.

### v0.1.4 interface polish — implemented 2026-10-17

The desktop notification control is now an icon-only bell after Shooting Log and
before the user menu; unread state changes its color. Mobile navigation has a
Notifications link after Shooting Log. The notification panel now uses the site
surface, border and navy link treatments and closes on outside click. Admins get an admin-only footer popover summarizing database,
backup/recovery and email status; the backup page no longer displays a raw health
JSON block. Backup and email settings use compact responsive sections. Heritage
rules now render red, ivory and blue in that order.

The authenticated `/settings` page now hosts each user's notification preferences;
`/notifications` remains the separate notification history page. Preference writes
are scoped to the signed-in user's own account record.

Verification: the full Python suite passed **110 tests with 2 opt-in PostgreSQL
tests skipped**; the full JavaScript suite passed **33 tests**. New coverage checks
desktop/mobile notification placement, unread styling, outside-click dismissal,
admin status popover loading, non-admin omission of the admin-status request, and
sanitized status API output. Python AST, edited Jinja templates, changelog JSON,
JavaScript syntax and `git diff --check` passed. The existing development
`rebuild.sh` completed with exit status 0. The development database reported
healthy, the application `/health` endpoint returned HTTP 200 with database
connected on v0.1.4, and the backup service reported healthy. The app's persistent
backup bind mount and development PostgreSQL named volume were present after
recreation. The app container has no Docker healthcheck configured; startup logs
contained no ERROR or Traceback markers. Manual browser acceptance remains with
the owner.

Follow-up Settings verification on 2026-10-17: all **21 operations tests** and
all **4 notification UI tests** passed, including authenticated Settings rendering,
per-user preference updates, separate history navigation and CSRF-bearing browser
submissions. Python AST, affected Jinja templates and `git diff --check` passed.
The development image was rebuilt successfully; the database was healthy, the
application health endpoint reported v0.1.4 with database connected, and an
unauthenticated `/settings` request followed the normal sign-in redirect.

Email appearance follow-up on 2026-10-17: notification messages now include an
inline-styled, responsive Armory Ledger HTML layout, severity accent, heritage
colors, clear timestamp, and a branded action link, with an accessible plain-text
alternative. User-provided title/message content is HTML-escaped. The focused
message-construction test passed without sending mail. All **22 operations tests**

Notification inbox/retention follow-up on 2026-10-17: the bell API now returns
unread recipient notices only, so marking a notice read removes it from the
dropdown while `/notifications` keeps it in history. Cleanup applies 90 days for
errors, 30 days for warnings, and 7 days for info/success, measured from the last
event update. Unresolved errors/warnings remain; successful backups resolve prior
backup-failure notices, and successful cleanup resolves cleanup warnings. Pending
or retrying email deliveries are retained. Focused tests cover unread/history
separation, severity retention, and backup-failure resolution; runtime verification
is pending.

Restore-notice follow-up on 2026-10-17: administrators can opt in separately to
in-app and email warnings when a whole-instance restore starts. The recipient
selection is persisted in the external backup catalogue before PostgreSQL restore;
the notice is written after restore or successful rollback for recipients who
remain administrators. New preferences default off. Migration `a47c91e2d563`
follows `d914b7ce203a`. Focused service, API and UI tests were added; migration
application, runtime testing and development rebuild have not been performed.

### GHCR latest-image update notices — 2026-10-17

The existing application worker now checks the upstream public GHCR `latest` image
once per day. It reads the OCI version label from the linux/amd64 manifest and
compares it with the running version. When the image tag points to a newer version,
the service creates one informational admin-only notification and queues email to
administrators if SMTP is enabled. Notices are resolved when the running version
catches up or the latest tag is no longer newer. Poll time is persisted in the
existing `system_settings` table; there is no migration, new service/container,
automatic pull or automatic update. Registry failures are recorded without exposing
details to users and retried on the next daily interval. The registry request sends
no account or inventory data.

Added mocked tests for token/manifest/config lookup, linux/amd64 selection, daily
throttling, admin-only recipients, deduplication, resolution, failures and equal
versions. Python AST parsing and `git diff --check` passed. The focused tests could
not run because the available host Python lacks SQLAlchemy; dependencies were not
installed. Live GHCR polling, runtime notification delivery and browser acceptance
have not been performed.

## Git reconciliation and v0.1.4 review — 2026-10-17

Before reconciliation, a mode-0700 snapshot under
`/tmp/armory-ledger-reconcile.ChkWIs` captured 319 working-tree paths, including
ignored local configuration, and its archive was independently extracted and
verified against per-file SHA-256 hashes and symlink targets. A Git bundle also
passed `git bundle verify`. Persistent `data/` was excluded because its
root-owned backup archive could not be read by `homeadmin`; no secret values were
printed. The published v0.1.3 commit was verified as the descendant of the former
local `main`, and `main` was advanced with a fast-forward only. The snapshot overlay
was then restored and verified byte-for-byte across all 319 captured paths.

**Operational incident:** the first cleanup attempt removed the ignored `data/`
directory after restoring the older `.gitignore`. The still-running development
container retained the old bind mount, but its backup directory was empty when
checked for recovery. The host `data/backups` path has been recreated and is empty;
the deleted backup archive(s) were not recovered. The development and production
databases were not accessed or modified, and no container was restarted. Treat
the missing local backup archive as an outstanding data-loss incident; do not
claim backup preservation for this reconciliation.

The changelog now marks v0.1.4 as unreleased, retains its planned date
`2026-10-22`, and includes the daily administrator-only GHCR `latest` image
availability notice. README and roadmap current-state references now identify
v0.1.3 as published. `.dockerignore` excludes `data/`, backup files and common
local build/test artifacts. The release procedure below recommends verifying a
published tag and advancing `main` with a fast-forward; automatic branch updates
remain unimplemented.

Verification after reconciliation used test-only Python and jsdom dependencies
installed under `/tmp`. The full Python suite passed **120 tests**, with the two
explicit disposable-PostgreSQL concurrency tests skipped; the full JavaScript suite
passed **38 tests**. The restore-notice test now simulates PostgreSQL replacement
inside the restore operation, and the jsdom notification fixtures use a visible
document. The update-available notice links to the matching upstream GitHub release.
Static checks passed: 96 Python files parsed, 38 Jinja templates parsed with
application-specific filters stubbed, 200 candidate-source files passed the
existing release scanner, JavaScript and release-wrapper syntax passed, and
`git diff --check` passed. No Docker, Alembic or application database operation
was run.

The source changes are ready for a **reviewed development commit**, subject to
excluding host-specific edits in `AGENTS.md`, reviewing the task-only
`instructions/Armory_Ledger_v0.1.4_Codex_Instructions.md` separately, and keeping
ignored local config out of the commit. This does not make the development
environment ready: the deleted development backup archive remains an unresolved
operational data-loss incident, and the container still has its pre-reconciliation
bind mount until a separately reviewed rebuild/restart.

### Recommended post-release `main` advancement

After a release is published, fetch its tag and candidate ref, verify the peeled
tag commit and publication identity against the approved release record, and
confirm that commit is a descendant of the current local `main`. Preserve any
working-tree changes in a separately verified snapshot first. Advance `main`
with `git merge --ff-only <verified-release-commit>`; if Git refuses, stop and
resolve overlaps from the snapshot rather than resetting or forcing. Restore
normal development changes on top of the new release commit, verify the source
and tests, and keep release candidate refs/tags reachable. Do not automatically
advance branches as part of publication until separately designed and approved.
passed; the dev app image was rebuilt, returned healthy on v0.1.4 and generated
multipart HTML/plain-text output in a local formatting smoke check without delivery.
