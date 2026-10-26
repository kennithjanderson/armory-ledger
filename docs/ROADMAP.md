# Armory Ledger Roadmap

Originally reviewed 2026-10-12 against `1fc2edd`; v0.1.3 was subsequently published
from commit `614d469` on **October 15, 2026** (America/Chicago). This roadmap was
reconciled with that release on 2026-10-17. Development checkpoint ordering was
reviewed again on 2026-10-23 at `7bef059`.
Other roadmap items have no assigned release dates or version commitments. Existing behavior is documented in [architecture](ARCHITECTURE.md)
and [implementation status](IMPLEMENTATION_STATUS.md); open choices are in
[decisions](DECISIONS.md).

## Status labels

- **Requested task:** an existing project instruction specifies the work; it is
  still pending and requires its own implementation task.
- **Established boundary:** preserve a previously specified product constraint.
- **Proposed improvement:** requested for roadmap consideration, not approval
  of an implementation design or database change.
- **Deferred:** explicitly outside the current implemented scope.

## 1. Range ammunition filtering — implemented, development review pending

Source: [instructions/range-ammo-filter.md](../instructions/range-ammo-filter.md).
Implemented in the development working tree on 2026-10-12. UI and backend use
exact caliber-ID checks. No schema changes or migrations are needed.

Scope:

- Match `Firearm.caliber_id` to `AmmoProduct.caliber_id` using exact identifiers.
  Do not infer interchangeability from similar strings or aliases.
- Filter inventory independently within each firearm card and all its ammo rows.
- Refilter on firearm changes; preserve compatible selections and clear stale ones.
- Show an explanatory state for no selected firearm, unknown caliber, or no
  matching inventory. Do not fall back to the entire inventory list.
- Preserve owner isolation, displayed lot descriptions/numbers/balances,
  other/borrowed ammunition, and existing quantity validation.
- Enforce the same relationship rule server-side so manipulated requests fail.
- Preserve historical sessions. Unchanged historical firearm/source/lot/quantity
  entries remain valid; new or changed entries must match. Review this assumption
  during development testing.

Changed application files: `app/services/range_service.py`,
`app/templates/range/new.html`, and `app/static/js/range-form.js`. Existing
owner-scoped page queries suffice; the API router and database models are unchanged.

Completion evidence: ten service tests and six DOM tests pass, covering the nine
requested scenarios, backend rejection, ledger balances, and historical edits.
See [test setup](../tests/README.md). Manual browser and PostgreSQL verification
remain pending. No lot merging or compatibility database is part of this task.

## 2. Compatible ammunition lot merging — original proposal (superseded below)

Source: the documentation-establishment request explicitly asks for this roadmap
item. No merge implementation or approved schema design exists.

The current acquisition workflow creates a new logical lot every time. Product
identity, logical lot UUID, and manufacturer lot-number text must remain distinct.

Before coding, confirm:

- Same-owner requirement and exact product-compatibility criteria.
- Treatment of different, identical, and unknown manufacturer lot numbers.
- Which metadata survives: notes, acquisition dates, labels, destination identity.
- Whether source identities remain visible for provenance and historical links.
- How range usage and inventory transaction foreign keys remain valid.
- Atomicity, concurrency controls, audit attribution, and failure recovery.

Acceptance goals: conserve total balance; preserve transaction types, quantities,
dates, history and range references; prevent cross-user merges; make the operation
explicit and traceable. Never replace detailed history with only an opening
balance. A migration may be needed depending on the approved design; none is
specified or authorized here.

## 3. Firearm/ammunition compatibility review — proposed follow-up

The initial requested rule is exact caliber-ID equality. It is not a physical
safety certification and may not express every legitimate compatibility case.
Any broader mapping requires separate product/domain review and a defined source
of truth. Do not add automatic equivalences or a new compatibility database as
part of the range filter. Review the implemented historical-edit policy before
expanding compatibility semantics.

## 4. Reconciliation and auditing — proposed improvements

Prioritize evidence-driven fixes over a wholesale inventory redesign:

- Reproduce and address concurrent withdrawals exceeding an available balance.
- Verify edit corrections for removed rows, changed quantities, changed lots,
  and inventory/other transitions within one transaction.
- Review linkage between range usage, original expenditure and later adjustments.
- Clarify whether acquisition timestamps are editable and what audit guarantees
  users should expect.
- Review creation-event gaps and private-data retention before adding audit UI.
- Define quarantine/release and physical-versus-available inventory only if those
  workflows are requested; enum presence is not implementation.

Acceptance should include balance conservation, failure rollback, provenance,
and owner-isolation tests. Do not expose private audit JSON through admin pages.

## Supporting maintenance — proposed, separately scoped

- Expand the focused range regression tests and consider a CI test job separate from publishing.
- Fix the source-identified range edit heading, missing Settings destination,
  stale model export, and accessory constraint metadata mismatch.
- Reconcile README/schema-plan status with committed migrations.
- Review dependency pinning and query/pagination costs when needed.
- Review local release-script directory/environment targeting before using it;
  it combines testing, deployment-like operations and publishing.

## Deferred work and preserved boundaries

- No manufacturer ownership redesign. Manufacturers/calibers remain global;
  admin reference views stay read-only without an explicit future scope change.
- No purge implementation currently. Future inventory purge must remove private
  inventory audit history too, retain accounts/shared references, and record only
  a privacy-limited admin event. Self-purge is initially excluded.
- No admin inventory browsing, counts or valuation summaries.
- No announcement scheduler, polling or dismissal tracking.
- No currency conversion, valuation, depreciation or accounting features.
- Backup/restore tooling is mentioned as future work in README, not a completed
  or scheduled delivery. Maintenance/documents are not implemented workflows.

## Updating the roadmap

When work is approved, link the specification and record outstanding decisions.
Move an item to implemented status only with source and verification evidence;
update IMPLEMENTATION_STATUS and ARCHITECTURE together. A completed source change
does not by itself mean it is deployed or its database migration is applied.

## Backup schema tracking and timezone selection — v0.1.5-dev.7 verified

The v0.1.5 development source derives backup/restore compatibility from the
Alembic migration heads shipped with the application. Administrators choose the
automatic backup timezone from a North America and UTC list, with an all-zones
option; local daily time remains stable across DST, with a documented gap/fold
policy. Focused tests cover migration-head matching and both DST transitions; all
33 focused operations tests passed in an isolated test container. The development
rebuild is healthy on schema head `d2c87ab9415e`, and browser acceptance including
a successful backup was confirmed on 2026-10-21. No database migration is
introduced. Caliber alias management moves from dev.7 to dev.8; completed
checkpoint numbering is preserved.

## Caliber alias management — v0.1.5-dev.8 verified

The existing shared `CaliberAlias` model and resolver now have Armory Admin-only
add/remove management, conflict validation and actor-attributed history. Explicit
alias options resolve to the existing canonical caliber ID in firearm and
ammunition forms. Do not infer equivalence between distinct calibers, combine
records or rewrite inventory references. Revision `e8a1f3c0d64b` follows
`d2c87ab9415e` and is applied in the development database as its current head.
The development app is healthy, all 49 focused regression tests pass, and browser
acceptance was confirmed by the owner on 2026-10-23. This item was initially dev.7;
backup/timezone work completed as dev.7, so caliber aliases became dev.8 without
renumbering completed checkpoints.

## Canonical manufacturer and caliber renames — v0.1.5-dev.9 verified

Dev.9 adds an Armory Admin-only workflow to correct a canonical manufacturer or
caliber name without changing its UUID. A successful rename adds the previous
canonical name as an alias in the same transaction, so existing spellings
continue to resolve while forms and records show the corrected primary name.
This supports corrections such as `S&W` → `Smith & Wesson`, `223` → `.223`, and
`556` → `5.56` when an administrator has confirmed the designation is truly
equivalent.

Reject a new canonical name that conflicts with another canonical record or an
alias belonging to another record. If the proposed name is already an alias of
the same record, promote it by removing that alias while preserving the prior
canonical name as the new alias. Keep the operation atomic, admin-authorized,
CSRF-protected and actor-audited. Do not merge records, alter UUIDs, or infer
caliber equivalence from similar strings, shared dimensions, or firearm
compatibility. The implementation uses separate actor-attributed canonical-name
history and alias history, with catalog advisory locks for conflict checks.
Migration `480378f66895` follows `e8a1f3c0d64b` and is applied in the
development database. Service, route, UI, and synthetic migration tests pass;
the owner confirmed browser acceptance on 2026-10-26. This checkpoint is
complete.

Implementation status and automated verification are tracked in
[IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md).

## Admin mobile layout review — future proposal

The current narrow-screen admin tables remain usable through horizontal
scrolling, but this is an interim layout. Review the admin pages together and
consider responsive card/list presentations that avoid wide tables on phones.
The request currently applies to the admin area only. A separate mobile site is
an option to evaluate, not an approved architectural direction. Keep desktop
presentation and data access behavior unchanged unless a later task defines a
broader scope.

## Shooting Log and recorded firearm rounds — implemented, review pending

The [shooting-log task](../instructions/shooting-log-activity-types.md) is
implemented in the development working tree as of 2026-10-12. Five activity types
reuse existing range sessions; firearm history and totals include all types and
external ammunition. Caliber filtering and accounting are preserved.

Before accepting for development runtime use, review migration `82c1f947ad30`,
apply it through the separately authorized development workflow, and browser-test
new/old records, multiple firearms, borrowed ammunition, type-only edits and totals.
The current application version was not changed; v0.1.3 is not declared complete.

Future hunting/training/incident modules remain proposals. They may reference
existing shooting record UUIDs rather than re-recording ammunition expenditure;
access control, retention and specialized fields need separate design approval.
No lot merger, estimated historical count, cached count or new deletion workflow
is included in this task.

## Lot merging — implemented, development and PostgreSQL review pending

The [lot-merging task](../instructions/ammunition-lot-merging.md) now has source,
migration, service/ASGI/DOM tests and documentation. The implemented policy and
accounting design are recorded in ARCHITECTURE and DECISIONS; these supersede
section 2's original proposed design questions.

Before deployment, review the migration and run it through the separately
approved development workflow, exercise the browser confirmation/archive/history,
and run the opt-in concurrency suite against explicitly authorized disposable
PostgreSQL. Reversal/restoration and historical usage correction after a merge
remain deferred. No automatic acquisition grouping, partial merge, or rewrite of
old Shooting Log records is introduced. This does not complete v0.1.3.

## Merge polish — implemented, browser review pending

The [merge polish task](../instructions/ammunition-merge-polish.md) adds compact
confirmation and destination navigation, safe uncertain-outcome handling, and
activity-aware expenditure descriptions using direct historical relationships.
Accounting and audits are preserved; no additional migration is required.

Development browser checks should confirm review quantities, Cancel behavior,
Proceed with Merger redirect, destination history/source link, and activity-type
edits reflected in ledger descriptions without another deduction. Use browser
console/network evidence if the originally reported success-warning recurs; its
exact runtime trigger has not been reproduced from available evidence. This does
not complete the release or supersede pending PostgreSQL concurrency verification.

## v0.1.3 final polish — included in the October 15, 2026 release

The final planned feature work now includes styled merge-history record links
and IANA-zone announcement scheduling with UTC previews and explicit DST handling.
No new schema migration was needed. These changes are included in published v0.1.3.

The [v0.1.3 release-testing checklist](V0.1.3-RELEASE-TESTING.md) is retained as a
record of the release acceptance process. This reconciliation adds no new test
evidence.

## Final date/time and Changelog polish — included in published v0.1.3

The [date/time task](../instructions/date-time-standardization-changelog.md) adds
shared historical-date calendars, explicit 24-hour entry/display, conditional DST
occurrence controls and public repository-managed release notes. This supersedes
reliance on native date/time pickers. No new migration or dependency is introduced.

The changelog records v0.1.3 as published on October 15, 2026. The checklist remains
available for historical reference; this update does not claim additional browser
testing.

## v0.1.3 release — October 15, 2026

The owner approved October 15, 2026 as the target date, and v0.1.3 was published
from commit `614d4694bc4a2dec02630c5d50d02fd4d77ea877`. Its release tag remains
reachable; this does not imply that production was deployed.

## Release workflow — implemented; v0.1.3 published

The approved [release workflow task](../instructions/release-workflow.md) now has
manual/scheduled wrappers, shared validation/notes/publication/recovery, immutable
candidate retention, systemd user units and guarded container alias promotion were
used for the published v0.1.3 release. Host setup, credentials and authorized
end-to-end validation remain release-specific checks for future versions. Follow
[RELEASE-WORKFLOW.md](RELEASE-WORKFLOW.md); publication and deployment remain
separate milestones.

## Upstream image update notices — implemented, development acceptance pending

The in-process worker checks the public upstream GHCR `latest` tag daily and
compares the image's OCI version label with the running app version. Newer tags
create deduplicated informational notices for administrators; notification email
uses the existing mail outbox when enabled. No image is pulled automatically and
no new migration or service is added. Verify daily scheduling, GHCR availability,
notification deduplication/resolution and admin-only visibility in development.

## v0.1.4 implementation — 2026-10-16

v0.1.4 implements Backup & Recovery, health, system email and live notifications.
v0.1.5 development has completed dev.1, the scheduled-release status command;
dev.2, duplicate ammunition lot suggestions; and dev.3, manufacturer grouping
and depleted-lot presentation. Dev.4 adds the installation experience and
`get-started.sh`, plus README/configuration documentation. The pending
ammunition-notification and admin-preference work is renumbered to dev.5; its
existing implementation and acceptance criteria are preserved. The owner
confirmed in-app and email notification browser acceptance on 2026-10-20, so
dev.5 is verified. The proposed enhanced-merge checkpoint was reviewed on
2026-10-20 and is unnecessary: zero-round lots retain their existing records and
history, and can be merged after ammunition is added. Existing merge behavior and
schema remain unchanged. Manufacturer alias management is implemented in the
development working tree as dev.6: admins can add/remove lookup aliases,
which resolve to the unchanged canonical manufacturer. Its migration and
focused tests are applied/verified in development.
The owner confirmed browser acceptance on 2026-10-20. Caliber alias management
was initially planned as dev.7 and is now dev.8 after backup/timezone work took
the next completed checkpoint; it must also be admin-only.
These assignments do not alter completed commits or their numbering.
v0.1.6 transfers and v0.1.7 sharing remain unimplemented. Firearm maintenance
notifications have no assigned release. Live identity-provider revocation
integration and multi-host operational coordination are not implemented.
