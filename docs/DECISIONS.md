# Armory Ledger Decisions

Reviewed 2026-10-12 against `1fc2edd`. This is a decision register, not a claim
that every implementation detail was previously approved in a formal ADR.
Evidence is identified for each entry. See [architecture](ARCHITECTURE.md),
[status](IMPLEMENTATION_STATUS.md), and [roadmap](ROADMAP.md).

## Established product boundaries

These boundaries are supported by the current README, SECURITY policy, retained
schema plan, and the project owner's v0.1.2 requirements in the development
discussion. Code was checked for implementation, rather than treating plans as
proof of completion.

| Decision | Evidence | Rationale and consequence |
| --- | --- | --- |
| Self-hosted application with external OIDC | [README](../README.md), `app/core/auth.py`, `app/api/auth.py` | No local passwords; the instance operator controls hosting and identity-provider configuration. Upstream software identity is separate from instance ownership. |
| Armory User required; Armory Admin is additional login-time privilege | [SECURITY](../SECURITY.md), auth callback, admin middleware/dependency | Server-side admin enforcement without live group refresh in v0.1.2. Revoking a provider group does not immediately revoke an existing session. |
| Administrators cannot browse other users' private inventory | Admin router, owner-filtered inventory routers, SECURITY | Admin account identity fields are permitted, but counts, prices, records, usage summaries and private audit data are excluded. Infrastructure operator access is a separate boundary. |
| Manufacturers and calibers remain shared | Models, reference services, README | Avoids manufacturer ownership migration. Multiple users share identifiers; new reference names are discoverable by other users. Admin views remain read-only. |
| Optional serial and purchase price | Firearm model/API and migration `f57a288ed6ed` | Unknown is represented by NULL, not fabricated serials or zero prices. Decimal/Numeric avoids binary floating-point storage. |
| Store currency separately; current UI writes USD | Firearm model/API/templates and schema plan | Existing USD amounts retain their meaning if more currencies are added. No valuation, conversion, tax, or accounting features are implied. |
| Request-time scheduled announcements | Announcement model/schema/service and README | No worker, cron, dismissal tracking or browser polling. Timezone-aware input normalizes to UTC; start inclusive/end exclusive. |
| Configurable operator identity on About / Privacy | Config, About router/template, README | Publicly distributed software must not assume the upstream developer operates every instance. Missing optional contact fields render no placeholders. |
| Purge deferred | [schema plan](v0.1.2-schema-plan.md), absence of purge routes/services | No self-purge or admin purge currently. Any future inventory purge must also remove private inventory audit JSON while retaining account, shared references and a privacy-limited administrative event. |

## Observed implementation: ammunition lots

The following semantics are verified in
[ammunition_service.py](../app/services/ammunition_service.py),
[ammo_lot.py](../app/models/ammo_lot.py), and
[ammo_inventory_service.py](../app/services/ammo_inventory_service.py).
They are documented as current behavior, not an inferred historical policy.

### Product, logical lot, and manufacturer lot number are different concepts

1. An `AmmoProduct` describes a shared brand/caliber/grain/projectile/product/SKU
   combination. The acquisition service attempts to reuse a matching product.
2. An `AmmoLot` is a user-owned inventory record identified by its UUID. It
   references a product and owns its transaction stream.
3. `AmmoLot.lot_number` is an optional manufacturer label. It is indexed but not
   unique and does not identify a lot independently of the UUID.

Every acquisition creates a new logical lot plus an initial acquired transaction.
For example, two acquisitions of the same product labeled `ABC123` produce two
owned lot UUIDs with independent histories. Blank lot numbers likewise do not
cause automatic grouping. Manual acquisition activity can instead add rounds to
an existing logical lot. These are distinct available workflows.

The service normalizes optional manufacturer lot-number text but does not look
up an existing lot by that text before creation. Consequently:

- Matching manufacturer numbers do not prove two inventory records should merge.
- Missing numbers do not prove rounds came from the same manufacturing batch.
- Different users may hold the same product/lot label without sharing inventory.
- A future merge cannot safely operate on display name or lot-number text alone.

The code does not explain whether always creating a logical lot was an intentional
long-term acquisition policy or simply the initial workflow. Confirmation is
required before changing it.

### Ledger and edits

Balances are calculated from signed transaction categories. There is no mutable
`quantity_on_hand` column on lots. Range edits compensate with adjustment
transactions, preserving original expenditure records. The observed benefit is
traceable corrections; the repository does not contain a formal historical ADR
for this choice.

The ledger is not entirely immutable: ammunition edits can change the initial
acquisition timestamp. Product edits repoint the owned lot to a matching/new
shared product rather than editing a shared product in place. These behaviors
must be considered when designing reconciliation, history views, or lot merging.

## Implemented task direction: exact caliber filtering

[instructions/range-ammo-filter.md](../instructions/range-ammo-filter.md) supplies
an explicit implementation brief: match existing caliber identifiers exactly,
filter independently for each firearm row, clear stale incompatible selections,
handle unknown/no-match states without showing all inventory, retain other/borrowed
ammunition, and validate compatibility server-side while preserving ownership
and history. It forbids a compatibility database redesign or lot merging within
that task. Implemented in the development working tree on 2026-10-12 after the
owner requested running that instruction.

Historical-edit handling is an implementation assumption for review: unchanged
stored firearm/association, inventory source, lot and quantity may be retained,
even if the firearm's current caliber differs or is absent. Changes to any of
those selections require an exact match; unrelated notes/date edits remain usable.
This preserves historical records without accepting new mismatched inventory use.
Ownership checks still apply to historical entries.

Focused tests use standard-library unittest plus SQLAlchemy with SQLite in memory,
and Node's test runner plus test-only jsdom. No application dependency or frontend
build system was added. See [tests](../tests/README.md) for setup and limitations.

Exact identifier matching is an application selection rule. It must not be
presented as a comprehensive physical ammunition/firearm safety determination.

## Decisions Requiring Confirmation

| Question | Why it matters / proposed direction, not an approved decision |
| --- | --- |
| Should repeated acquisitions remain separate by default? | Current behavior always creates lots. Preserve it until the owner decides whether explicit reuse or grouping is desired. |
| Lot merge compatibility | Resolved by the 2026-10-13 implementation decisions below; broader matching remains outside scope. |
| Lot merge history | Implemented with preserved identities and paired transfers; see the 2026-10-13 decisions below. |
| Is the implemented historical-edit policy acceptable? | The working tree preserves unchanged legacy entries while requiring matches for new/changed entries, as described above. Review this assumption in development testing. |
| Will explicit cross-caliber compatibility ever be supported? | Initial brief requires exact IDs. Any exception mapping needs separately reviewed semantics; do not infer interchangeability from names or aliases. |
| What are required ledger/audit guarantees? | Clarify acquisition-date mutability, correction linkage, creation coverage, quarantine semantics, and concurrency expectations before treating the ledger as an immutable audit record. |
| Should future admin reference editing or purge be added? | Both remain outside current scope. Any purge requires transaction ordering, concurrency controls, multiple confirmations and private-audit removal; self-purge is initially excluded. |

## Maintaining this register

Assign new decisions a clear status (confirmed, observed, proposed, superseded),
link their source and affected components, and record rationale only when known.
When a proposal is approved, record the approval context and update the roadmap
and status together. Preserve the reasoning for superseded decisions rather than
silently rewriting history.

## Shooting Log decisions — implemented 2026-10-12

Source: [shooting-log task](../instructions/shooting-log-activity-types.md).

- Retain range-session backend and URLs to preserve history/bookmarks and avoid
  parallel activity/accounting systems. Only presentation terminology changes.
- Use stable string activity values with enum validation and a VARCHAR database
  check, following the existing string/check pattern used for announcements.
  No native PostgreSQL enum lifecycle or type-specific tables are needed.
- Backfill via a NOT NULL server-default column: every existing record is range.
  No instance-specific records or seed users are assumed.
- Count authoritative current usage quantities rather than ledger expenditures:
  external ammunition must count, while compensating adjustments must not.
  The label is Recorded Rounds Fired, never an estimated lifetime count.
- Classification edits do not create inventory transactions. Omitted activity
  fields on older update payloads preserve classification; creates default to range.
- Future dedicated modules should reference original session IDs and preserve
  owner isolation. No hunting/training/incident-specific information is required.
- Version remains unchanged. This implements a v0.1.3 task, not a completed release.

## Ammunition lot merge decisions — implemented 2026-10-13

Source: [lot-merging requirements](../instructions/ammunition-lot-merging.md).
These decisions supersede the earlier open merge-design questions above.

- Retain source identities and history; transfer only the complete current balance
  with explicit merge categories, a common operation ID and paired private audits.
- Treat a populated destination pointer as the source lifecycle marker instead of
  maintaining a redundant status field. No restoration endpoint is provided.
- Require identical specifications, including brand identity and product notes.
  Whitespace/case normalization follows existing product matching; manufacturer
  batch identifiers remain case-sensitive. Unknown only matches unknown.
- Reject empty/negative sources and negative destinations. Stale confirmed
  balances require a fresh review rather than silently changing the transfer.
- Serialize all existing balance-changing paths on ordered lot row locks, not
  just the merge endpoint. Session edits additionally lock their session row.
- Freeze historical merged-source usage's firearm/lot/source/quantity and removal.
  Preserve note/activity edits. Automatically crediting a destination on historical
  correction would require a separately designed reversal/provenance policy.
- Preserve source and destination notes and acquisition dates independently.
  Merge movements are not purchases, consumption or manual adjustments.
- Allow active destinations to become later sources; retain the original links
  so history records the actual sequence, not a rewritten final destination.
- Block downgrade once merge records exist to prevent loss of transfer provenance.
  Keep added PostgreSQL enum labels on an otherwise empty downgrade.
- No version bump, release completion, deployment or live migration is implied.

## Merge polish decisions — 2026-10-13

Source: [merge polish task](../instructions/ammunition-merge-polish.md).

- Separate confirmed operation success from navigation success. The former catch
  combined fetch, JSON parsing and redirect exceptions, making failures ambiguous.
- Use a server-generated destination URL, validated against the reviewed
  destination and current origin. Do not add another notification framework.
- Uncertain requests cannot be retried from the same form. Offer read-only record
  checks because a network error/timeout may occur after the commit.
- Use compact confirmation with live quantities, explicit irreversible/archive
  language, a non-mutating Cancel action and accessible identifier details.
- Derive expenditure display text only from a unique direct Shooting Log link.
  Keep original notes/audits untouched. Newly created expenditures store the
  corresponding activity-aware note; unrelated transaction categories are unchanged.

## v0.1.3 final-polish decisions — 2026-10-13

- Keep UTC/TIMESTAMPTZ and request-time announcement visibility. Convert local
  wall-clock inputs with Python `zoneinfo`; no scheduler, data migration or fixed
  Central offset. Add the small `tzdata` runtime fallback for portable IANA data.
- Use one server conversion implementation for form previews and actual saves.
  The stateless preview route has server admin authorization and CSRF protection.
  Continue accepting the existing explicit-offset API format.
- Reject DST gaps. Require earlier/later selection for repeated times on new or
  edited wall-clock values. Existing instants already identify their occurrence;
  preselect it on edit. Preserve exact microseconds on unchanged saves even though
  native datetime-local inputs only display millisecond precision.
- A timezone change preserves a resolved instant, rather than silently changing
  publication time; edit the date/time to reschedule. Default each form to browser
  IANA timezone, falling back to UTC; do not persist preferences this release.
  Management list columns remain UTC-labeled. Unsupported zones produce an error.
- Reuse record-link styles for merge history, including visited/focus states;
  show UUIDs as secondary metadata. No merge/accounting policy changes.

These choices are implemented in the development working tree, not evidence of
migration application, container deployment or release acceptance.

## Date/time and Changelog decisions — 2026-10-14

- Use a shared vanilla-JavaScript calendar instead of Safari/native date/time UI.
  Date text input remains available, with direct month/year navigation and native
  accessible select controls for 24-hour hours/minutes. No new dependency.
- Keep date-only values unchanged. Distinguish ordinary local timestamps (HH:mm),
  audit/clock seconds and UTC-labeled admin metadata. No database/schema change.
- Preserve exact unchanged announcement instants; an explicit calendar/time edit
  records minute precision. Keep repeated-time controls hidden unless ambiguous.
- Use structured JSON release notes, which the task permits as an alternative to
  Markdown. Plain strings rendered with Jinja escaping eliminate a Markdown HTML
  sanitization dependency. Support Added, Improvements, Bug fixes, Breaking changes
  and Important upgrade notes; unknown dates remain visibly unrecorded.
- Historical release dates derive from local annotated tags: v0.1.0 (2026-09-24),
  v0.1.1 (2026-09-25), v0.1.2 (2026-09-26). Notes are conservative summaries of
  tagged source; v0.1.3 is an undated unreleased draft, not a release announcement.

## Release management decisions — 2026-10-14

Stage A approved by the owner, with explicit requirements for tag reachability,
monotonic latest images, opt-in timer setup, failed-validation blocking and separate
GitHub/container milestones. Implemented common Python engine and thin Bash wrappers,
private-index candidate preparation, pinned retention refs, saved notes/runner and
locked recovery. Manual mode attempts a non-force remote main update; scheduled mode
publishes a dedicated candidate ref/tag without moving main. Local work/index/main
are preserved; operators must integrate candidate-only features through reviewed merges.

Keep structured Changelog JSON as the single maintained release-note source. Manual
and edited notes are preserved; Codex assistance is optional interactive editing,
never an approval or unattended dependency. User systemd timers require separately
enabled lingering and persistent credentials. No automatic host setup during this task.

Guard image aliases with serialized publication, semantic-version comparisons against
published releases and existing registry aliases, and fail-closed identity checks.
Retain exact SHA/digest verification before full success. No real release/deployment
is authorized by implementation approval. See RELEASE-WORKFLOW.md for residual risks.

## Validation-only release checks — 2026-10-14

Provide --validate-only as an independent manual CLI mode. Keep Git refs and the real index unchanged, allow selected untracked files, and never create release state. Cleanup failures must fail validation rather than be silently ignored.

## Bulk validation selection — 2026-10-14

--include-all-changes is restricted to manual --validate-only. Include changed tracked files and nonignored untracked files, using working-tree contents. Reject unsafe file types and sensitive filenames before selection approval.

## Reviewed bulk release preparation — 2026-10-14

The owner approved extending bulk selection beyond validation-only. This supersedes the initial restriction above. Bulk selection retains all exclusions and explicit approval; expected-tree mismatches stop preparation instead of substituting another source tree.
