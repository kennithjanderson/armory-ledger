# Armory Ledger v0.1.3 — Shooting Log and Firearm Round Count

## Objective

Extend the existing Range feature into a more general **Shooting Log** that records firearm usage across multiple activity types.

Add a **Recorded Rounds Fired** statistic to each firearm's detail page.

This is an incremental enhancement to Armory Ledger v0.1.3. Preserve the existing range-session system, firearm associations, ammunition inventory deductions, and historical records.

Do not redesign the application or introduce a separate firearm activity subsystem unless an existing architectural constraint makes it necessary.

## 1. Development environment and scope

Work only in the Armory Ledger development repository:

`/opt/armory-ledger-dev`

Before modifying code:

1. Read `AGENTS.md` if present, along with any applicable repository instructions.
2. Read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/IMPLEMENTATION_STATUS.md`, and `docs/ROADMAP.md` if present.
3. Inspect the existing range-session models, database schema, migrations, routes, templates, and tests.
4. Inspect how range sessions associate firearms with ammunition and quantities fired.
5. Inspect the firearm detail page and its existing Range History implementation.
6. Identify the current ammunition inventory deduction and correction mechanisms.
7. Check the current Git status and avoid overwriting unrelated changes.

Do not modify the production environment, production database, or production deployment.

Do not push to GitHub, create a release, or change the application version without explicit approval.

## 2. Rename Range to Shooting Log

Update the user-facing terminology:

| Existing | New |
|---|---|
| Range navigation | Shooting Log |
| Range History (on firearm detail) | Shooting History |
| Record a Range Session | Record Shooting Activity |
| View Session (on firearm history) | View Activity |

Update related page titles, headings, buttons, and explanatory text where appropriate.

Maintain the current visual design and layout.

Do not rename existing database tables, models, API routes, or URL paths solely for terminology consistency.

Existing bookmarks and routes should continue working.

## 3. Add Activity Type to shooting records

Extend the existing range-session model with an activity classification.

Supported activity types:

| Stored value | Display label |
|---|---|
| `range` | Range Session |
| `hunting` | Hunting |
| `training` | Training |
| `defensive` | Defensive Action |
| `other` | Other |

Use the project's existing database migration conventions.

Requirements:

- Add a non-null activity type field with a default of `range`.
- Existing records must be classified as `range`.
- Enforce the supported values at the appropriate application validation layer.
- Use stable stored values independent of display labels.
- Ensure that existing range-session records remain accessible and editable.
- Include the activity type in applicable create, read, and update operations.

Do not introduce hunting-specific, training-specific, or defensive-incident-specific tables in this release.

## 4. Update the Shooting Log entry form

Add an **Activity Type** dropdown immediately before the existing date and location fields.

Default selection: **Range Session**.

The remainder of the existing form should stay functionally unchanged:

- Date
- Location
- Session notes
- Multiple firearms
- Ammunition source
- Ammunition selection
- Rounds fired
- Firearm notes

All activity types must support the existing multiple-firearm workflow.

Selecting a different activity type must not reset entered firearm or ammunition information.

Preserve the caliber-based ammunition filtering already implemented in the development environment.

When changing the selected firearm, incompatible ammunition selections must continue to reset as designed.

Do not introduce new required fields based on activity type.

Location and notes must remain optional.

The existing inventory deduction behavior must work identically for every activity type.

## 5. Update Shooting History on firearm details

Rename the existing **Range History** section to **Shooting History**.

Each history entry should display:

- Activity type
- Location, or `Location unspecified`
- Activity date
- Number of rounds fired by that particular firearm
- A link labeled `View Activity`

Example:

**Range Session — Gunport**
October 11, 2026 · 32 rounds
View Activity →

**Hunting — Conecuh County**
October 12, 2026 · 3 rounds
View Activity →

**Defensive Action — Location unspecified**
October 12, 2026 · 10 rounds
View Activity →

The latter two examples are illustrative and must not be inserted as application data.

For v0.1.3, all activity entries should link to their existing session-detail pages, regardless of activity type.

Do not create placeholder hunting, training, or defensive-incident pages.

Future dedicated modules may provide their own detail pages and link back to the original Shooting Log record.

## 6. Add Recorded Rounds Fired to firearm details

Add a clearly visible statistic to each firearm's detail page:

**Recorded Rounds Fired**

This statistic represents the total rounds recorded as fired through the firearm across all Shooting Log activity types.

Example:

A firearm has the following existing records:

- Range Session: 19 rounds
- Range Session: 299 rounds

Its displayed total should be:

**318 recorded rounds fired**

If another activity records 3 rounds fired through that firearm, the displayed total should become 321.

### Calculation requirements

Calculate the total from the authoritative existing firearm-to-session ammunition usage records.

Do not maintain an independently editable or incremented firearm counter.

Do not add a cached database column unless there is a demonstrated performance requirement and a reliable consistency strategy.

The calculation must:

1. Include all supported activity types.
2. Sum rounds fired for the specific firearm, not the entire multi-firearm session.
3. Include rounds fired using ammunition supplied outside inventory.
4. Exclude ammunition purchases, inventory adjustments, corrections, and lot mergers.
5. Avoid double-counting sessions or ammunition usage records.
6. Correctly reflect any supported edits or deletions of shooting records.
7. Return zero for firearms without recorded shooting activity.

Review the existing data relationships carefully to ensure that joins do not multiply quantities.

Use an efficient aggregate query consistent with the project's ORM and database conventions.

### Historical accuracy

The statistic should be labeled **Recorded Rounds Fired**, not Lifetime Rounds Fired.

It reflects recorded application history and does not claim to represent ammunition fired before the firearm was added to Armory Ledger.

Do not implement estimated historical round counts in this release.

## 7. Shooting Log and inventory accounting

Preserve the existing separation between firearm usage and ammunition inventory.

Recording a shooting activity should:

- Record the number of rounds fired by each firearm.
- Deduct ammunition from the selected inventory lot when applicable.
- Record firearm usage even when ammunition was not sourced from inventory.
- Prevent invalid quantities and insufficient-inventory operations according to existing application rules.
- Preserve existing audit and transaction behavior.

The activity type must not change ammunition accounting rules.

Changing an activity from Range Session to Hunting must not create an additional inventory deduction.

Do not implement ammunition lot merging as part of this task.

## 8. Future module compatibility

Design the activity type implementation so future features can reference existing shooting records.

Potential future modules:

**Hunting**
- Hunting trips
- Hunting properties
- Game harvested
- Optional firearm and ammunition references

**Training**
- Training courses
- Qualifications
- Instructors
- Certificates

**Defensive Incidents**
- Optional private incident records
- Restricted access controls
- Supporting documentation
- Links to firearm usage records

These features are explicitly out of scope for v0.1.3.

For now, Defensive Action is simply an activity classification within Shooting Log.

Do not introduce mandatory incident descriptions, personal information, or additional location requirements.

Document future integration considerations without implementing them.

## 9. Automated testing

Add or update tests using the project's existing testing framework.

At minimum, verify:

### Activity types

- New shooting records default to `range`.
- Each supported activity type can be saved and retrieved.
- Unsupported activity types are rejected.
- Existing historical range records retain the `range` classification after migration.
- Editing an activity type preserves associated firearms and ammunition.
- Existing shooting records remain accessible through their current routes.

### Firearm round totals

- A firearm with no shooting records displays zero.
- A firearm with multiple sessions displays the correct aggregate.
- A firearm with multiple ammunition entries in one session is counted correctly.
- A multi-firearm session attributes the correct quantities to each firearm.
- Hunting, Training, Defensive Action, and Other contribute to the total.
- Ammunition fired from outside inventory contributes to the total.
- Inventory corrections and lot mergers do not contribute to the total.
- Supported edits or deletions correctly affect the displayed aggregate.

### Inventory integrity

- Shooting activity using inventory ammunition deducts the correct quantity.
- Shooting activity using external ammunition does not deduct inventory.
- Changing activity type does not duplicate deductions.
- Existing caliber filtering continues to work.
- Switching firearms clears incompatible ammunition selections.

### Interface

- Navigation displays Shooting Log.
- The entry form displays Activity Type.
- The firearm detail page displays Shooting History.
- Each history entry displays the correct type and location.
- View Activity links to the existing detail page.
- The Recorded Rounds Fired statistic displays correctly.

Run the relevant existing test suite and report any failures.

Do not weaken or delete existing tests simply to make the new implementation pass.

## 10. Documentation

Update the existing documentation as appropriate:

- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`

Document:

- The new activity classification.
- The decision to retain the existing range-session backend.
- How recorded firearm round totals are calculated.
- The relationship between shooting records and ammunition inventory.
- Compatibility considerations for future dedicated modules.

Preserve the existing documentation structure and conventions.

Do not mark the overall v0.1.3 release complete.

## 11. Acceptance criteria

The task is complete when:

- Shooting Log replaces Range in user-facing navigation.
- Existing range sessions continue functioning.
- The Activity Type dropdown is available and defaults to Range Session.
- All five activity types can be recorded.
- The existing firearm and ammunition workflows remain functional.
- Each firearm displays its correct Recorded Rounds Fired total.
- Shooting History displays activity type, location, date, rounds fired, and a working View Activity link.
- Inventory deductions remain correct.
- Relevant automated tests pass.
- Documentation is updated.
- Production remains untouched.

## 12. Completion report

When finished, provide:

1. Summary of implemented changes.
2. Files modified.
3. Database migration details.
4. Explanation of the round-count calculation.
5. Tests executed and results.
6. Any outstanding limitations or risks.
7. Manual browser test instructions for the development environment.

Do not commit, push, merge, tag, deploy to production, or create a release without explicit approval.

Stop and ask for clarification if implementation requires a substantial redesign or destructive migration.
