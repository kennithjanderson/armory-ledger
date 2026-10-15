# Armory Ledger Roadmap

Baseline reviewed 2026-10-12 against `1fc2edd`. Release planning updated
2026-10-14: v0.1.3 is planned for **October 15, 2026** (America/Chicago).
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

## v0.1.3 final polish — implemented, release testing pending

The final planned feature work now includes styled merge-history record links
and IANA-zone announcement scheduling with UTC previews and explicit DST handling.
No new schema migration is needed. The version remains 0.1.3 and is **not released**.

Use [V0.1.3-RELEASE-TESTING.md](V0.1.3-RELEASE-TESTING.md) for multi-day development
acceptance, migration-state verification, browser coverage and release gates.
Live PostgreSQL concurrency tests and the original merge-success browser incident
remain verification concerns. No release, tag, deployment or production operation
is authorized by completion of the source work.

## Final date/time and Changelog polish — implemented, acceptance pending

The [date/time task](../instructions/date-time-standardization-changelog.md) adds
shared historical-date calendars, explicit 24-hour entry/display, conditional DST
occurrence controls and public repository-managed release notes. This supersedes
reliance on native date/time pickers. No new migration or dependency is introduced.

Complete the expanded release checklist in Safari, Chrome, Firefox and mobile,
including keyboard navigation, historical dates and unchanged announcement saves.
Source and isolated DOM/ASGI checks are not real-browser acceptance. Version 0.1.3
remains unreleased; commit/tag/publish/deploy remain separate approval boundaries.

## v0.1.3 release target — October 15, 2026

Target date approved by the owner on 2026-10-14. Release remains pending final
acceptance of the [testing checklist](V0.1.3-RELEASE-TESTING.md). No release time
or automated publishing job is set. Commit, push, tag, publication and deployment
require separate explicit authorization; the target date does not execute them.

## Release workflow — implemented, operational acceptance pending

The approved [release workflow task](../instructions/release-workflow.md) now has
manual/scheduled wrappers, shared validation/notes/publication/recovery, immutable
candidate retention, systemd user units and guarded container alias promotion.
No publication or real schedule has been created. Host setup, credential checks,
review of selected release files/scanner exceptions and authorized end-to-end
validation remain required. Follow [RELEASE-WORKFLOW.md](RELEASE-WORKFLOW.md).
The October 15 target does not create a timer or authorize a push by itself.
