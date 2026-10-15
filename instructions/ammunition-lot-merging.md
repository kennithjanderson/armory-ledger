# Armory Ledger v0.1.3 — Ammunition Lot Merging

## Objective

Implement controlled merging of compatible ammunition inventory lots while preserving inventory accuracy, acquisition history, shooting activity associations, and audit records.

This feature is intended primarily for ammunition without a known manufacturer lot number, where multiple purchases of the same ammunition should be managed as one logical inventory lot.

Do not merge ammunition with different known manufacturer lot numbers.

## 1. Environment and preparation

Work only in:

`/opt/armory-ledger-dev`

Before implementation:

1. Read `AGENTS.md` and applicable repository instructions.
2. Read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/IMPLEMENTATION_STATUS.md`, and `docs/ROADMAP.md`.
3. Inspect ammunition models, inventory transactions, acquisition records, API routes, templates, and migrations.
4. Inspect how Shooting Log references ammunition inventory lots.
5. Inspect how ammunition balances are calculated and updated.
6. Inspect ownership enforcement and concurrency handling.
7. Check Git status and preserve unrelated changes.

Do not modify production, commit, push, tag, or deploy.

### Architecture review

Before making changes, determine:

- Whether lot quantities are stored directly or derived from transactions.
- How purchases and manual adjustments are represented.
- Whether historical shooting records reference a lot ID.
- Whether lots can currently be archived or marked inactive.
- Whether the existing transaction model supports internal transfers.
- Whether migrations or additional audit fields are necessary.

If the design requires destructive changes, substantial restructuring, or breaking existing records, stop and report the findings before implementing.

Otherwise, implement the feature using the existing architecture wherever practical.

## 2. Merge eligibility

A user may merge two ammunition inventory lots only when both belong to that user and represent the same ammunition specification.

At minimum, verify compatibility of:

- Caliber
- Manufacturer
- Product or ammunition designation
- Bullet weight
- Bullet type
- Any additional attributes that materially distinguish the ammunition in the existing data model

Normalize harmless formatting differences only where the existing application already has a reliable normalization rule.

Do not silently treat missing specification values as equivalent to known values.

### Manufacturer lot numbers

Apply the following rules:

| Source lot | Destination lot | Merge allowed |
|---|---|---|
| No manufacturer lot number | No manufacturer lot number | Yes, if specifications match |
| Known lot number A | Known lot number A | Potentially, if specifications match |
| Known lot number A | Known lot number B | No |
| Known lot number | Missing lot number | No |
| Missing lot number | Known lot number | No |

The same known manufacturer lot number may be merged only when all other compatibility and ownership requirements are satisfied.

Treat missing lot numbers as unknown, not as evidence of a common manufacturer batch.

Preserve the distinction between the internal Armory Ledger lot identifier and the manufacturer lot number.

## 3. Merge operation

Provide an explicit action to merge an eligible source ammunition lot into a destination ammunition lot.

Example:

Before:

- Lot A: Winchester 5.56 NATO 55gr FMJ — 200 rounds
- Lot B: Winchester 5.56 NATO 55gr FMJ — 200 rounds

Merge Lot B into Lot A.

After:

- Lot A: 400 rounds, active
- Lot B: 0 rounds, status Merged

The merge must preserve total inventory quantity.

### Transaction behavior

The merge must:

1. Validate authenticated ownership of both lots.
2. Reject source and destination being the same record.
3. Reject incompatible specifications or manufacturer lot numbers.
4. Reject previously merged or otherwise ineligible lots.
5. Lock relevant inventory records to prevent concurrent balance changes.
6. Determine the source's available balance inside the transaction.
7. Transfer the entire available source balance to the destination.
8. Record paired audit entries for the source and destination.
9. Mark the source lot as merged.
10. Commit the operation atomically.

If any part fails, roll back the entire operation.

Do not allow partial merges in v0.1.3.

Use the project's existing database transaction conventions.

### Duplicate submission protection

Prevent a repeated submission from transferring ammunition twice.

Use appropriate transaction validation, source status checks, and concurrency protection.

If an operation is repeated after a successful merge, it must not change inventory balances again.

## 4. Audit history

The source and destination must each retain a visible record of the merge.

Example:

**Source lot history**

`−200 rounds — Merged into Lot A`

**Destination lot history**

`+200 rounds — Merged from Lot B`

Requirements:

- Both records reference the same merge operation.
- Preserve source and destination lot identifiers.
- Record the transferred quantity.
- Record the authenticated user and timestamp.
- Preserve original acquisition dates and purchase records.
- Preserve pre-existing inventory adjustments and shooting deductions.
- Do not rewrite or delete historical transactions.

Use an explicit internal-transfer or merge classification so future reporting can distinguish merges from purchases, consumption, and manual corrections.

Merges must not count as newly purchased or expended ammunition in future annual reporting.

## 5. Source lot lifecycle

After a successful merge:

- Source quantity is zero.
- Source status is Merged.
- Source remains accessible through historical records and an archive/filter.
- Source is excluded from active inventory totals and selection lists.
- Source cannot receive new Shooting Log deductions.
- Source cannot be merged again.
- Source cannot be restored to active inventory without a separately designed, audited reversal workflow.

The destination remains active.

Do not hard-delete source records.

If the existing schema already has a suitable lifecycle mechanism, extend it rather than introducing redundant status fields.

## 6. Shooting Log compatibility

Historical Shooting Log entries must retain their original lot associations.

For example, if a range session previously deducted 40 rounds from Lot B, that historical record must continue pointing to Lot B even after Lot B is merged into Lot A.

Do not reassign historical shooting entries to the destination.

Existing Shooting Log records must remain readable.

Active ammunition selection must exclude merged source lots.

Investigate existing edit/delete behavior for historical shooting records referencing merged lots.

Do not allow historical edits or reversals to silently restore ammunition to a merged source lot or corrupt inventory balances.

If a safe solution requires a larger accounting redesign, stop and report that issue before implementing.

## 7. User interface

Add a **Merge Lot** action to the ammunition inventory interface, preferably on the ammunition lot detail page.

The action should be available only when the lot is eligible to be merged.

### Merge workflow

The user should be able to:

1. Select the source lot.
2. Select an eligible destination lot.
3. Review the proposed transfer.
4. Confirm the merge.
5. See a success message and the updated destination balance.

Only show compatible destination lots.

However, the backend must independently validate eligibility and must not trust UI filtering.

### Confirmation

Display a clear confirmation before executing:

**Merge ammunition lots?**

Source: Lot B — 200 rounds
Destination: Lot A — 200 rounds

After merging:

- Destination: 400 rounds
- Source: 0 rounds, archived as Merged

Explain that the operation preserves historical records and cannot be undone through the current interface.

Do not perform a merge from a single unconfirmed click.

### Merged lot display

Merged lots should remain discoverable through an appropriate archive or status filter.

Their detail pages should clearly display:

- Merged status
- Original lot information
- Destination lot link
- Merge date
- Transferred quantity
- Historical transactions

Avoid displaying merged lots as available inventory.

## 8. Inventory reporting

Ensure that internal lot merges do not artificially inflate:

- Ammunition purchased
- Ammunition expended
- Ammunition adjustments
- Total ammunition owned

Inventory totals before and after a merge must be identical.

Preserve acquisition provenance for future reports.

If current reports or dashboard summaries aggregate transaction types, update their classification rules as needed.

## 9. Tests

Add automated tests using the project's existing testing framework.

### Eligibility

- Compatible unknown-numbered lots can merge.
- Same known manufacturer lot numbers can merge when otherwise compatible.
- Different known manufacturer lot numbers cannot merge.
- Known and unknown lot numbers cannot merge.
- Different calibers cannot merge.
- Different manufacturers cannot merge.
- Different bullet weights or types cannot merge.
- Missing specification values cannot bypass validation.
- Cross-user merging is rejected.
- Source and destination cannot be identical.

### Inventory integrity

- Merging 200 rounds into 200 results in 400 active rounds.
- Source balance becomes zero.
- Total owned ammunition remains unchanged.
- Paired audit entries are created.
- Failed operations roll back completely.
- Repeated submissions do not duplicate inventory.
- Concurrent operations cannot overdraw the source.
- Previously merged lots cannot merge again.

### Historical integrity

- Original acquisitions remain intact.
- Original shooting activity associations remain intact.
- Existing inventory corrections remain intact.
- Historical merged lot details remain accessible.
- Merged source lots cannot be selected for new shooting activities.
- Historical shooting activity edits cannot corrupt merged balances.

### UI

- Merge Lot action is available appropriately.
- Only compatible destination lots are offered.
- Confirmation displays correct balances.
- Successful merges display the correct result.
- Merged lots are discoverable in history.
- Invalid merges display clear errors.

## 10. Documentation

Update:

- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`

Document:

- Merge eligibility rules.
- Manufacturer lot number handling.
- Atomic transfer behavior.
- Audit trail design.
- Merged lot lifecycle.
- Historical Shooting Log compatibility.
- Reporting treatment of internal transfers.
- Any limitations or deferred reversal functionality.

Do not mark v0.1.3 complete.

## 11. Acceptance criteria

The feature is complete when:

- Eligible ammunition lots can be merged through the UI.
- Inventory balances remain correct.
- Both lots retain auditable merge history.
- Merged source lots remain accessible but inactive.
- Historical shooting activity remains accurate.
- New shooting activity cannot consume merged lots.
- Invalid, duplicate, and concurrent merge operations are safely rejected.
- Existing ammunition accounting remains functional.
- Relevant tests pass.
- Documentation is updated.

## 12. Completion report

Report:

1. Architecture findings and design decisions.
2. Files modified.
3. Database migration details.
4. Merge transaction and locking approach.
5. Historical Shooting Log handling.
6. Automated test results.
7. Any unresolved risks.
8. Manual development testing instructions.

Do not commit, push, deploy, tag, or create a release without explicit approval.
