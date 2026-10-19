# Range ammunition regression tests

Run from the repository root. Tests use synthetic records and never import the
application Settings/session factory, read `.env`, or connect to an application
database. No Docker or Alembic is needed.

Python uses the standard-library `unittest` runner and existing SQLAlchemy/Jinja2
dependencies. Node uses its built-in test runner (Node 18+) and test-only jsdom 24.
Install test dependencies in temporary locations, for example:

```bash
python3 -m venv /tmp/armory-range-tests
/tmp/armory-range-tests/bin/pip install sqlalchemy jinja2 alembic pydantic fastapi httpx
npm install --prefix /tmp/armory-range-js-tests --no-package-lock --no-audit --no-fund jsdom@24
PYTHONDONTWRITEBYTECODE=1 /tmp/armory-range-tests/bin/python -m unittest discover -s tests -p 'test_*.py' -v
PYTHON=/tmp/armory-range-tests/bin/python NODE_PATH=/tmp/armory-range-js-tests/node_modules node --test tests/range-form.test.cjs tests/ammunition-merge.test.cjs
```

`test_range_service.py` calls the actual create/update and inventory services
using SQLite in memory with foreign keys enabled. A copied test schema uses JSON
instead of JSONB and SQLite REGEXP instead of PostgreSQL's regex operator.
Application metadata is unchanged. This checks owner isolation, caliber rejection,
historical edits, quantity limits, actual ledger deductions/corrections and rollback.
It does not verify PostgreSQL-specific types, migrations, concurrency, or HTTP auth.

`range-form.test.cjs` runs the actual browser script against the actual Jinja form,
rendered by `render_range_form.py` with synthetic fixtures and a minimal base
template. It covers selection filtering, unchanged compatible selections, clearing,
multiple cards/rows, missing caliber/stock, borrowed ammunition, stale submission,
historical mismatch preservation and exhausted historical lots. jsdom does not
replace manual browser verification of layout/native dropdown behavior.

No lint/build configuration or CI test job is introduced by this task.

## Shooting Log coverage

The same commands run activity-type and recorded-round tests. Service cases cover
all five types, default/invalid values, unchanged deductions on type-only edits,
owner isolation, multiple firearm/ammo rows, external ammunition, quantity edits
and removed usage. `test_shooting_schema.py` executes the new migration only on
synthetic SQLite memory tables, compiles PostgreSQL SQL without connecting, and
executes actual request-schema declarations independently of app Settings.
`test_shooting_pages.py` renders the real templates with synthetic data and checks
existing URL declarations. These are not full HTTP/authentication tests.

Migration downgrade removes classification; tests confirm session rows survive.
PostgreSQL-specific execution/locking remains untested. Lot merging and whole
session deletion are not implemented, so tests do not fabricate such workflows.
Current totals deliberately have no inventory-transaction joins and reflect
supported usage removals/edits. New jsdom tests cover all activity values,
selection preservation on type changes and restoring edit classification.

## Lot merging coverage and PostgreSQL opt-in

Merge tests add eligibility, paired transfer/audit conservation, rollback, stale
and duplicate rejection, merge chains, preserved acquisitions/corrections, source
write guards and historical Shooting Log restrictions. Actual ASGI router tests
inject test identity/database dependencies without importing Settings or app.main;
they cover authentication dependency rejection, ownership, CSRF, confirmation,
archive, success, and merged source exclusion. They do not test OIDC itself.
DOM tests exercise the actual merge template/script and historical disabled rows.
Migration tests use synthetic SQLite and offline PostgreSQL SQL compilation.

`test_merge_concurrency.py` skips unless BOTH `ARMORY_DISPOSABLE_POSTGRES=1` and
`ARMORY_TEST_POSTGRES_URL` are supplied. Use only an explicitly authorized disposable
PostgreSQL database, with the psycopg driver installed in the test environment.
Never set these to a development/production application database. The tests create
and drop their own randomly named schema, use independent sessions/threads, and
exercise duplicate merges and merge-versus-expenditure races with timeouts.
They do not read `.env` or reuse the application's connection settings.

Run after disposable-database authorization and configuration:

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/armory-range-tests/bin/python -m unittest discover -s tests -p 'test_merge_concurrency.py' -v
```

PostgreSQL tests are pending permission in the current review. Ordinary SQLite
results and generated FOR UPDATE SQL are not runtime concurrency verification.
No application migration has been applied by these tests.

## Merge polish regression coverage

Merge DOM tests use the actual template/script with a captured navigation boundary.
They cover HTTP 200 success, navigation throwing after confirmed success, 409,
network/timeout, malformed JSON/success payloads, external redirects, server errors,
no uncertain retry, pending duplicate submissions, Cancel, focus and live quantities.
They do not simulate actual browser loading or establish the original incident's
specific console exception. ASGI tests validate the server-provided redirect URL.

`test_expenditure_descriptions.py` checks all activity labels, classification-only
edits without ledger/note/audit changes, new-row edits, multi-firearm/multi-ammo
activities and unlinked/manual historical fallbacks. Merge tests also ensure
transfer descriptions remain separate. No historical data rewrite is performed.

## Final-polish scheduling and record-link tests

Also run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON=/tmp/armory-range-tests/bin/python NODE_PATH=/tmp/armory-range-js-tests/node_modules node --test tests/*.test.cjs
```

`test_announcement_schedule.py` exercises real schema/zoneinfo conversion,
Chicago winter/summer, gaps/folds, other zones, invalid/offset-free input,
full-precision unchanged edits, actual admin/CSRF dependencies and create/update
routes, and synthetic SQLite visibility tests with a fixed SQL clock expression.
No app settings or live database is loaded. The visibility query and timezone-aware
column declarations are unchanged; SQLite is not a PostgreSQL timezone test.

`admin-announcements.test.cjs` renders the real Jinja form and runs its real script.
Its preview fetch uses the actual Python converter through a stateless subprocess;
no HTTP service is started. It checks browser defaults, timezone switching, UTC
previews, explicit repeated-time selection, validation errors and microsecond
preservation despite native input precision limits. These tests need the test
Python interpreter selected with `PYTHON`. Runtime dependencies now include
`tzdata` as fallback where system IANA data is absent; tests can use system data.
Merge route tests verify source/destination links; CSS checks verify explicit
visited and keyboard-focus rules. Visual layout/contrast still need browser review.

## Shared date/time and Changelog coverage

`date-time.test.cjs` tests calendar year/month selection, Gregorian validation,
keyboard navigation, month precision/reconfiguration, required fields, 24-hour
boundaries and untouched timestamp precision. Announcement DOM tests now load the
actual shared picker and converter together, checking conditional DST controls.
`test_changelog.py` exercises the anonymous ASGI route with the real base template,
footer, release ordering, absent/malformed metadata and HTML/unsafe-link escaping.
Structured JSON is deliberately plain text, not executable Markdown or HTML.

Run the full existing Python and Node commands above. For date-only boundary checks,
repeat `node --test tests/date-time.test.cjs` with `TZ=Pacific/Kiritimati` and
`TZ=America/Los_Angeles`. jsdom is not Safari/Chrome/Firefox or a screen reader;
real browser and mobile accessibility/layout testing remains manual.

## Release workflow tests

`test_release_workflow.py` uses temporary Git repositories (synthetic local commits)
and mocked GitHub, registry, Docker and systemd operations. No application checkout
commit/tag/push, actual job installation, container start or GitHub publication is
performed. It covers explicit file selection/private index, candidate retention and
main drift, cancellation/reschedule/reboot checks, DST, notes modes and integrity,
partial publication retry, failed validation, exact image verification and monotonic
alias policy. Validation cleanup is tested with command doubles. These tests are not
proof of live host permissions, GitHub credentials, registry behavior or reboot timing.
See docs/RELEASE-WORKFLOW.md for operator setup and read-only dry-run commands.

Release validation-only tests cover selected tracked/untracked source, real-index/ref preservation, success/failure cleanup, no publication/state effects and cleanup failure reporting. Docker calls are mocked; these tests do not establish live Docker/PostgreSQL acceptance.

Bulk release-selection tests cover modified, staged, deleted, renamed and untracked files, ignored exclusions, index preservation, cancellation, unsafe-file rejection and validation-only CLI enforcement. They use temporary Git repositories and do not start Docker.

## v0.1.4 operations

`test_operations.py` uses synthetic SQLite and private temporary archive stores,
mocking PostgreSQL utilities and SMTP. It exercises AES-256-GCM backup creation,
raw encrypted downloads, valid-key decryption, invalid/missing/wrong key failure,
and verifies wrong-key restore rejection before any database restore or snapshot.
Install the application requirements
(including cryptography) in the test environment. `notifications.test.cjs` uses the
existing jsdom setup; `admin-status.test.cjs` checks the administrator footer
popover and confirms non-admin pages do not request its protected endpoint.
Notification UI tests also cover unread bell state, mobile-link placement, Escape,
and closing the popup by clicking outside. They verify that `/settings` hosts the
signed-in user's backup notification preferences separately from notification
history and that preference submissions carry the selected values.
`recovery_exercise.py` is opt-in and must run only in newly created disposable
PostgreSQL/application containers; it checks explicit database
name/host/flag guards before running destructive clean-install recovery tests.
Never point it at normal development or production databases.

## Duplicate ammunition lot suggestions

`test_ammunition_suggestions.py` checks exact owner-scoped matching, caliber,
grain and projectile distinctions, manufacturer identity, depleted candidates,
and exclusions for numbered or merged lots using synthetic SQLite. The route
cases in `test_merge_routes.py` verify that a suggestion does not create a lot or
ledger transaction, canonical/alias manufacturer lookup works, explicit
Create New Lot and known lot-number submissions retain acquisition behavior, and
the existing activity route remains owner-scoped. These tests do not exercise
PostgreSQL query plans or a live browser.

`ammunition-suggestions.test.cjs` uses jsdom with the actual form and scripts. It
covers cancel-with-values-retained, explicit separate-lot submission, the
session-storage handoff to Acquired activity without putting quantity in the
URL, one-time prefill consumption, and escaped suggestion labels. Manual browser
acceptance remains necessary for visual and native interaction review.

Caliber inventory route coverage checks manufacturer ordering, active versus
zero-round grouping, collapsed depleted-lot markup, preserved detail links and
ledger balances. A subsequent acquisition is checked to move a depleted lot back
to active inventory without changing prior transaction history. Changelog route
coverage verifies that entries with a planned date are labeled Scheduled while
undated unreleased entries remain drafts and published entries retain their date.

Notification email formatting is tested with constructed synthetic events; the
test verifies the branded HTML/plain-text alternatives and escaping without SMTP.
