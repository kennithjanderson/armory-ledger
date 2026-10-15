# Armory Ledger v0.1.3 — Date/Time Standardization and Changelog

## Objective

Standardize all user-facing times throughout Armory Ledger to **24-hour format**, improve date/time selection across browsers, and introduce a public Changelog page.

This is final-release polish for v0.1.3, not a major feature expansion.

Work exclusively in `/opt/armory-ledger-dev`.

Read `AGENTS.md` and the relevant architecture, decisions, implementation status, and roadmap documents before making changes. Inspect the current implementation before selecting a technical approach.

## Part 1 — Standardize 24-hour time

Use 24-hour time throughout the application.

Examples:
- 08:30 instead of 8:30 AM
- 13:45 instead of 1:45 PM
- 00:00 for midnight
- 23:59 for the final minute of the day

Requirements:

1. Audit all user-facing time displays and time-entry fields, including:
   - Announcements and administration pages
   - Shooting activities and their history
   - Ammunition transactions and merge history
   - Firearm records and history
   - Dashboard and other timestamp displays
   - Footer clock
   - Any additional date/time fields discovered during inspection

2. Use a consistent `HH:mm` format for ordinary displayed times and time inputs. Where seconds are useful for audit records, use `HH:mm:ss`.

3. Eliminate AM/PM controls and 12-hour formatted times from the application interface.

4. Preserve the distinction between display timezone and storage timezone. Do not change UTC-based timestamp storage.

5. Do not alter date-only values or their semantics.

6. Preserve all existing timestamps and historical data.

7. Use shared formatting utilities where practical rather than repeating formatting logic across templates.

## Part 2 — Improve date and time pickers

Safari's native HTML date and date/time inputs currently make selecting years and times unnecessarily difficult.

Implement a consistent date-picker experience across the application.

### Date-only fields

- Calendar-based day selection.
- Direct month selection.
- Direct year selection.
- Easy navigation to historical years.
- Keyboard input where practical.
- Responsive desktop and mobile layouts.

### Date/time fields

Include all date-only features plus:

- Hour selection from `00` through `23`.
- Minute selection from `00` through `59`.
- No AM/PM controls.
- Clearly labeled 24-hour time.
- Ability to edit the time without reselecting the date.

Prefer a shared, accessible component or lightweight library compatible with the existing frontend architecture.

Do not introduce a major frontend framework solely to implement these controls.

The picker must match Armory Ledger's existing visual design.

## Part 3 — Preserve announcement timezone behavior

The announcement scheduler already supports IANA timezones and UTC conversion. Preserve that functionality.

Requirements:

1. Allow users to enter announcement start/end dates and times in the selected IANA timezone using 24-hour time.

2. Continue storing resolved timestamps in UTC.

3. Continue displaying UTC equivalents for verification.

4. Preserve daylight-saving handling:
   - Normal local times require no special selection.
   - Ambiguous fall-back times must allow the user to choose the earlier or later occurrence.
   - Nonexistent spring-forward times must produce a clear validation error.

5. Show repeated-time occurrence controls only when a selected local time is ambiguous.

6. Do not silently change an already resolved instant when the selected timezone changes.

7. Preserve correct values when creating, editing, saving, and reopening announcements.

8. Do not rely on ambiguous local datetime parsing.

## Part 4 — Add a Changelog page

Create a public, read-only Changelog page for Armory Ledger.

### Purpose

Users should be able to see what changed between releases without needing to visit GitHub.

### Requirements

1. Add a `/changelog` page, following the application's existing routing conventions.

2. Use the existing Armory Ledger visual design.

3. Display releases newest first.

4. Each release should support:
   - Version number
   - Release date
   - Added features
   - Improvements
   - Bug fixes
   - Breaking changes or important upgrade notes, when applicable

5. Add a Changelog link in the existing footer, preferably near About / Privacy or the application version.

6. Keep changelog content in a version-controlled Markdown file or similarly simple repository-managed source.

7. Avoid introducing a database table or administrative CRUD interface for changelog management.

8. Escape or safely render any Markdown content. Do not introduce unsafe HTML rendering.

9. Do not fabricate historical release notes. Use existing Git history and project documentation where available, and identify any uncertain details.

10. Prepare a **v0.1.3 draft entry**, clearly marked as unreleased until the actual release.

11. Ensure the Changelog page does not expose secrets, internal infrastructure, private hostnames, user data, or sensitive implementation details.

## Part 5 — Testing

Test the following:

### Date and time

- Historical firearm acquisition dates.
- Selecting years without navigating month by month.
- 24-hour time selection at 00:00, 08:30, 12:00, and 23:59.
- Editing existing date/time values.
- Date-only values near midnight.
- Announcement timezone conversion.
- America/Chicago DST fall-back ambiguity.
- America/Chicago DST spring-forward nonexistent times.
- Correct UTC persistence after save/reload.
- No unexpected timezone shifts.
- No remaining user-facing AM/PM displays.

### Changelog

- Public access without authentication.
- Correct release ordering.
- Safe Markdown rendering.
- Footer navigation.
- Responsive layout.
- Appropriate handling of missing or incomplete release metadata.

### Browser compatibility

Test Safari, Chrome, Firefox, and mobile browsers where environments are available.

Report any browser tests that could not be performed.

Run the existing automated test suite and add focused regression tests where appropriate.

## Constraints

- Development environment only.
- No production modifications.
- No destructive migrations.
- Preserve existing records and history.
- Avoid unnecessary dependencies.
- Do not commit, push, tag, publish, or deploy without explicit approval.
- Update relevant project documentation.
- Keep scope limited to release polish.

## Completion report

When finished, report:

1. Files changed.
2. Date/time inputs and displays updated.
3. Picker implementation and any new dependencies.
4. Changelog implementation and draft release notes.
5. Automated tests and results.
6. Browser testing performed or unavailable.
7. Outstanding issues or release risks.

Stop after implementation and testing for review before v0.1.3 is released.
