# Armory Ledger — Development Task: Filter Range Session Ammunition by Firearm Caliber

## Objective

Update the **Add Range Session** workflow in the Armory Ledger development environment so that ammunition selections are filtered based on the caliber of the firearm selected.

Currently, when a user selects a firearm and adds ammunition fired, the ammunition dropdown displays all available inventory lots, regardless of caliber.

For example, selecting a **Canik Mete SFT chambered in 9mm Luger** currently displays both 9mm Luger and 5.56×45mm NATO ammunition.

The ammunition dropdown should display only compatible ammunition inventory records.

## Scope

This task is limited to the development environment.

Do not deploy to production, modify production data, or make unrelated changes.

Before implementation, inspect the existing application architecture, firearm and ammunition models, range-session form, API endpoints, validation logic, and existing tests.

Follow established project conventions and instructions in AGENTS.md or other applicable repository documentation.

## Functional Requirements

### 1. Filter ammunition by firearm caliber

When a firearm is selected in the Add Range Session form:

- Determine the selected firearm's recorded caliber.
- Filter the ammunition inventory dropdown to show only ammunition compatible with that caliber.
- Preserve the existing ammunition descriptions, quantities, and manufacturer lot information.
- Display only inventory records belonging to the current user or authorized inventory scope.
- Preserve existing behavior for selecting an ammunition source, including ammunition not drawn from inventory.

Examples:

- Canik Mete SFT (9mm Luger) → Show 9mm Luger ammunition.
- Bushmaster M4 (5.56×45mm NATO) → Show 5.56×45mm NATO ammunition.

Use existing caliber identifiers and relationships where available. Do not implement fragile substring matching against display labels.

### 2. Handle firearm selection changes

When a user changes the selected firearm:

- Immediately update the available ammunition options.
- Clear any ammunition selection that is no longer compatible.
- Preserve a previously selected ammunition lot if it remains compatible.
- Do not allow a stale or incompatible ammunition selection to be submitted.

### 3. Support multiple firearms

The range-session form supports adding multiple firearms.

Each firearm entry must maintain its own independently filtered ammunition selections.

Adding, removing, or changing one firearm must not incorrectly modify another firearm's ammunition selections.

Each firearm must continue to support multiple ammunition entries.

### 4. Handle missing or unmatched calibers

If no firearm is selected, do not display the entire ammunition inventory by default.

If a firearm has no recorded caliber or no matching ammunition inventory:

- Display an appropriate explanatory message.
- Do not silently fall back to displaying incompatible ammunition.
- Preserve the ability to record a valid range session using existing non-inventory ammunition workflows, where supported.

### 5. Validate on the backend

Client-side filtering alone is insufficient.

Review the existing range-session submission logic and ensure that an incompatible ammunition inventory record cannot be associated with a firearm through a manipulated request.

Preserve existing authentication, authorization, ownership, and inventory quantity checks.

Do not introduce changes that permit cross-user inventory access.

### 6. Caliber compatibility

For this initial implementation, use exact caliber relationships already defined in the application.

If the application already supports explicit firearm/ammunition compatibility mappings, reuse them.

Do not automatically assume that similarly named calibers are interchangeable.

Do not introduce a new caliber compatibility database or a broad ammunition model redesign as part of this task.

Document any limitations or recommendations for future caliber compatibility support.

## Testing Requirements

Add or update automated tests using the project's existing testing framework.

At minimum, verify:

1. A 9mm firearm displays 9mm ammunition and excludes 5.56 ammunition.
2. A 5.56 firearm displays 5.56 ammunition and excludes 9mm ammunition.
3. Changing firearms clears incompatible ammunition selections.
4. Multiple firearms maintain independent ammunition selections.
5. Multiple ammunition entries under the same firearm filter correctly.
6. A firearm with no matching ammunition is handled gracefully.
7. Existing non-inventory ammunition workflows continue functioning.
8. Backend validation rejects incompatible firearm/ammunition combinations.
9. Existing inventory deductions and range-session recording remain correct.

Run the relevant tests, linting, and build checks supported by the repository.

## Implementation Constraints

- Development environment only.
- No production deployment.
- No production database modifications.
- No destructive database operations.
- No unrelated UI redesign.
- No ammunition lot merging in this task.
- Preserve existing historical range-session records.
- Follow existing UI styling and application architecture.
- Prefer the smallest maintainable implementation consistent with current project conventions.

## Deliverables

After implementation, provide:

1. Summary of changes.
2. List of modified files.
3. Explanation of how caliber matching works.
4. Test results, including any failures or tests that could not run.
5. Any database migration requirements.
6. Known limitations and recommended follow-up improvements.

Do not commit, push, or deploy changes without explicit approval.

Once implementation and local testing are complete, stop and report the results so we can review and test the development environment before proceeding.
