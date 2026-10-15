# Armory Ledger v0.1.3 — Ammunition Merger Polish and Activity-Aware Transactions

## Objective

Improve three existing features before the v0.1.3 release:

1. Fix the ammunition merger's frontend success-confirmation behavior.
2. Simplify the merge confirmation interface.
3. Make ammunition expenditure transaction descriptions reflect the actual Shooting Log activity type.

This is a targeted bug-fix and UI-polish task. Preserve the existing inventory accounting, audit history, lot compatibility validation, and merge safeguards.

## 1. Environment and preparation

Work only in:

`/opt/armory-ledger-dev`

Before modifying code:

- Read `AGENTS.md` and applicable project documentation.
- Inspect the existing ammunition merge frontend, backend endpoint, and service.
- Inspect the current merge confirmation template and JavaScript.
- Inspect how Shooting Log activity types are stored and how ammunition expenditure descriptions are generated.
- Review existing tests and Git status.

Do not modify production.

Do not commit, push, tag, deploy, or create a release without explicit approval.

## 2. Fix successful merge confirmation

### Observed problem

During development testing, the first merge request returned HTTP 200 OK, and the inventory transfer completed successfully.

However, the browser displayed:

"Unable to confirm the result. Reload and check lot history before retrying."

A second request returned HTTP 409 Conflict because the source lot had already been merged.

The resulting inventory was correct:

- Source: 200 → 0 rounds
- Destination: 170 → 370 rounds
- Total inventory: unchanged at 370 rounds
- Merge audit history: present

### Requirements

Investigate the actual cause of the frontend failure.

Inspect:

- `app/static/js/ammunition-merge.js`
- The ammunition merge POST endpoint
- The response format and HTTP status
- JSON parsing and response validation
- Frontend navigation and error handling
- Existing merge tests

Do not assume the cause without reproducing or tracing it.

After a successful merge:

1. The backend completes the atomic merge.
2. The frontend recognizes the successful response.
3. The browser automatically navigates to the destination ammunition lot detail page.
4. The destination page displays the updated balance and merge history.

Use the existing destination detail route.

Prefer a server-provided, validated redirect URL or destination identifier over constructing an untrusted URL in JavaScript.

### Failure handling

If the server explicitly rejects the merge, display the appropriate error and do not redirect.

If the request's outcome is uncertain because of a network failure, timeout, or malformed response, do not blindly retry the merge.

Instead, explain that the result could not be verified and provide a safe way to check the source and destination records.

Preserve duplicate-submit protection.

Disable the submit button while the merge request is pending, but do not rely on frontend controls for transaction safety.

## 3. Simplify the merge confirmation interface

The current confirmation page uses a large heading, long UUIDs, and multiple paragraphs explaining the merge.

Replace this with a shorter, clearer confirmation workflow.

Keep the existing destination selection and eligibility filtering.

### Desired interaction

The user:

1. Opens Merge Lot from the source ammunition record.
2. Selects a compatible destination lot.
3. Clicks Review Merge.
4. Sees a compact confirmation panel.
5. Clicks Proceed with Merger.
6. Is automatically redirected to the destination ammunition record after success.

### Proposed confirmation panel

**Merge ammunition lots?**

You're about to move **200 rounds** from this lot into the selected destination lot.

**This cannot be undone.**

The source lot will be set to **0 rounds** and archived as Merged.

The destination lot will increase from **170 to 370 rounds**.

All historical acquisitions, shooting records, and inventory transactions will be preserved.

**Proceed with Merger** | Cancel

All quantities must be calculated from the selected lots, not hardcoded.

### Design requirements

- Match the existing Armory Ledger visual style.
- Use a compact confirmation panel rather than a full-page warning.
- Avoid displaying raw UUIDs prominently.
- Identify source and destination using ammunition specifications, available quantities, and useful distinguishing information such as acquisition date.
- Keep identifiers accessible where necessary for auditing.
- Display the exact number of rounds being transferred.
- Display the resulting destination balance.
- Clearly explain that the source will be archived as Merged.
- State that the merge cannot be undone through the current interface.
- Do not imply that historical records will be deleted.
- Provide a Cancel action that safely returns to the source record or closes the confirmation without modifying inventory.
- Label the final action **Proceed with Merger**.

Do not add unnecessary confirmation dialogs after the user has already reviewed and confirmed the merge.

### Example compact layout

Merge ammunition lots?

Source lot: 200 rounds
Destination lot: 170 rounds

Transfer: 200 rounds
New destination balance: 370 rounds

Warning: This cannot be undone. The source lot will become 0 rounds and be archived as Merged.

[Proceed with Merger] [Cancel]

This is a conceptual layout. Adapt it to existing templates and styling conventions.

## 4. Redirect after successful merger

Upon successful confirmation, navigate directly to the destination ammunition detail page.

The destination should display:

- Its new inventory balance.
- The existing Merge In transaction.
- The Merge History section.
- The link to the historical source lot.

Do not redirect back to the merge form or source lot after success.

A success notification may be shown if the application already supports flash messages or an equivalent pattern.

Do not create a new notification framework solely for this change.

## 5. Activity-aware ammunition transaction descriptions

### Existing behavior

The Shooting Log supports these activity types:

| Stored value | Display label |
|---|---|
| `range` | Range Session |
| `hunting` | Hunting |
| `training` | Training |
| `defensive` | Defensive Action |
| `other` | Other |

However, the ammunition inventory ledger still displays generic descriptions such as:

"Range session expenditure."

This is misleading when ammunition was expended during a Hunting, Training, Defensive Action, or Other activity.

### Desired behavior

For Shooting Log ammunition expenditure transactions, display descriptions based on the associated activity type.

Examples:

- Range Session → "Range session expenditure."
- Hunting → "Hunting expenditure."
- Training → "Training expenditure."
- Defensive Action → "Defensive action expenditure."
- Other → "Other shooting activity expenditure."

Use the existing activity classification and centralized display-label conventions where practical.

### Historical transactions

Inspect how expenditure transaction descriptions are currently stored.

Determine whether descriptions are:

- Generated dynamically from linked Shooting Log records.
- Stored as immutable transaction text.
- Generated at transaction creation without a direct activity relationship.

Choose an approach that preserves accounting integrity.

If a transaction has a reliable link to its Shooting Log record, prefer deriving the user-facing activity description from that record where appropriate.

This should allow an activity classification change, such as Range Session → Hunting, to display the correct activity description without creating another ammunition transaction.

Do not rewrite historical ledger transactions unnecessarily.

Do not infer activity types from dates, quantities, or free-text notes.

If existing historical transactions cannot be reliably associated with a Shooting Log record, preserve their original descriptions rather than guessing.

### Important accounting requirements

Changing a Shooting Log activity type must not:

- Deduct ammunition again.
- Restore previously deducted ammunition.
- Create duplicate expenditure transactions.
- Change the recorded rounds fired.
- Modify inventory balances.
- Alter original acquisition records.

Merge In and Merge Out transactions must retain their own descriptions and classifications.

Manual adjustments, purchases, and other inventory transactions must not be mislabeled as Shooting Log expenditures.

## 6. Tests

Add or update automated tests using the project's existing testing framework.

### Merge frontend

Verify:

- Successful HTTP 200 merge responses are recognized.
- The frontend redirects to the correct destination lot.
- A successful response does not show the uncertain-result warning.
- The final button cannot trigger duplicate submissions while pending.
- Explicit HTTP 409 responses show an appropriate error.
- Network failures produce a safe uncertain-result message.
- Malformed responses are handled safely.
- The merge form does not automatically retry uncertain operations.
- Cancel performs no inventory mutation.

### Merge confirmation UI

Verify:

- Source quantity is correct.
- Destination quantity is correct.
- Transfer quantity is correct.
- Resulting destination quantity is correct.
- The warning explains that the source will become zero and be archived.
- The final action is labeled Proceed with Merger.
- Raw UUIDs are not the primary identifiers displayed to the user.
- The confirmation is accessible using keyboard navigation.

### Activity-aware descriptions

Verify:

- Each of the five activity types displays the correct expenditure description.
- Editing an activity type updates the displayed classification where a reliable relationship exists.
- Editing only the activity type does not alter inventory balances.
- Merge transactions retain their own classifications.
- Manual adjustments and acquisitions are unaffected.
- Unlinked historical transactions retain their original descriptions.
- Multi-firearm and multi-ammunition activities continue to work.

Run the relevant Python and JavaScript tests.

Report any failures or regressions.

## 7. Documentation

Update applicable documentation:

- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`

Document the successful-merge redirect behavior and how Shooting Log activity types affect displayed expenditure descriptions.

Do not mark the v0.1.3 release complete.

## 8. Completion report

When finished, report:

1. Root cause of the successful-merge confirmation error.
2. Files modified.
3. New confirmation workflow.
4. Successful-merge redirect behavior.
5. Activity-aware transaction description implementation.
6. Handling of existing historical transactions.
7. Tests executed and results.
8. Any remaining limitations or concerns.
9. Manual development testing steps.

Do not commit, push, tag, or deploy.

Stop and ask for clarification if the changes require a destructive migration or significant inventory accounting redesign.
