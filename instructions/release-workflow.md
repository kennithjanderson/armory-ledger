# Armory Ledger — Manual and Scheduled Release Workflow with Automated GitHub Release Notes

## Objective

Implement a reliable release management workflow for Armory Ledger that supports:

1. Immediate manual releases using `release.sh`.
2. Future scheduled releases using `schedule-release.sh`.
3. Automated, human-readable GitHub release notes.
4. Optional Codex-assisted release-note drafting.
5. Shared release validation and publishing logic.
6. Safe, unattended execution of previously approved scheduled releases.

The objective is to reduce repetitive release work while maintaining control over what gets published.

**Do not publish a release, push commits, create Git tags, deploy to production, or modify production data while implementing or testing this workflow.**

## 1. Existing Environment

Development repository:

`/opt/armory-ledger-dev`

Development URL:

`https://armory-dev.example.com`

GitHub repository:

`kennithjanderson/armory-ledger`

GitHub Container Registry:

`ghcr.io/kennithjanderson/armory-ledger`

Existing release script:

`release.sh`

The existing script performs Git checks, Docker builds, application health checks, basic HTTP tests, staging, private-reference scanning, committing, pushing, tagging, GitHub release creation, and GitHub Actions inspection.

Preserve its useful functionality while improving the architecture.

Inspect the repository, existing release script, Docker configuration, GitHub Actions workflows, Changelog implementation, version management, tests, and project documentation before making changes.

Do not assume that all existing release checks are sufficient or that all source files are safe to publish.

## 2. Desired Commands

### Manual release

```bash
./release.sh
```

This command should guide the user through an immediate release.

It should:

1. Request the release version.
2. Inspect pending changes.
3. Run applicable validations.
4. Prepare release notes.
5. Allow review and editing.
6. Display a final release summary.
7. Request explicit publication approval.
8. Commit, push, tag, and publish using the shared release engine.

A manual release may include changes made shortly before publication, including bug fixes.

### Scheduled release

```bash
./schedule-release.sh
```

This command should prepare a release for a future date and time.

It should:

1. Request the release version.
2. Request a local release date and time.
3. Resolve the chosen time using an IANA timezone, defaulting to the user's environment where appropriate.
4. Show the corresponding UTC time.
5. Validate the release candidate.
6. Prepare and approve release notes.
7. Pin the release to a specific Git commit.
8. Display a final schedule summary.
9. Request explicit approval to schedule publication.
10. Register a persistent, unattended release job.

The scheduled job must publish the previously approved release candidate, not whatever happens to be on `main` when the job runs.

## 3. Shared Release Engine

Avoid implementing two separate copies of the release logic.

Create reusable components for:

- Git and repository validation.
- Version validation.
- Build and application testing.
- Secret and private-reference scanning.
- Release candidate preparation.
- Release-note generation.
- Git commit and tag management.
- GitHub release publication.
- GitHub Actions verification.
- Logging and error reporting.

The manual and scheduled scripts should call the same underlying functions wherever practical.

Use Bash, Python, or a small combination of both as appropriate for the existing repository.

Do not introduce unnecessary dependencies or a large release-management framework.

## 4. Release Candidate Preparation

Before approving a release, identify exactly which source files and Git commit will be published.

### Manual releases

Allow the user to review and approve the pending changes before committing or publishing.

Do not automatically include unrelated untracked files without showing them to the user.

### Scheduled releases

Prepare a stable release candidate and pin its commit SHA.

The candidate must remain immutable after approval.

If new commits are made to `main` before the scheduled release, they must not silently become part of the approved release.

Investigate an appropriate approach using an immutable candidate commit, dedicated release reference, or equivalent Git mechanism.

The scheduled job must not run `git add --all`, create an unexpected commit, or publish a moving branch tip.

Ensure the chosen approach works with the existing GitHub Actions container publishing workflow.

## 5. Release Validation

Preserve and improve the current validation steps:

- Confirm the repository and expected remote.
- Validate the version format.
- Reject existing local or remote release tags.
- Check Git integrity.
- Review staged and untracked files.
- Run automated tests.
- Build the application.
- Verify the `/health` endpoint.
- Verify application and database health.
- Verify the reported application version.
- Check the login page.
- Check unauthenticated access protection.
- Scan for secrets and sensitive configuration.
- Confirm required GitHub authentication and permissions.

Review the existing private-reference scanning implementation. It should not be the only protection against publishing secrets.

Do not expose secret values in logs or terminal output.

Avoid modifying production databases or services during validation.

If validation requires restarting the development application, document the effect and avoid unexpected data loss.

If a required validation fails, stop before publication.

## 6. Automated GitHub Release Notes

Implement structured, human-readable release notes for both workflows.

### Preferred sources

Use the following sources, in order of preference:

1. The existing Armory Ledger Changelog entry for the target version.
2. Changes between the previous release tag and the approved release candidate.
3. Relevant Git commit messages.
4. Existing project documentation.

Do not invent features, bug fixes, compatibility claims, or test results.

Do not include changes made after the approved release candidate.

### Release-note structure

Use sections where applicable:

```markdown
# Armory Ledger v0.1.3

## New Features

## Improvements

## Bug Fixes

## Upgrade Notes
```

Omit empty sections.

Prefer descriptions that are useful to an end user rather than raw Git commit messages.

For example:

Instead of:

`Fix merge UI`

Prefer:

`Improved ammunition lot merge confirmations and destination navigation.`

### Manual release notes

Offer the following choices:

1. Enter release notes manually.
2. Generate release notes automatically.
3. Generate a draft and edit it before publication.

The user must be able to review the final Markdown before publishing.

Manual notes must not be overwritten by automatic generation.

### Scheduled release notes

During scheduling:

1. Generate release notes from the approved candidate.
2. Optionally improve their readability with Codex.
3. Display the draft.
4. Allow editing.
5. Request approval.
6. Save the approved Markdown with the scheduled release metadata.

At execution time, use the saved release notes.

Do not regenerate notes when the scheduled job runs.

### Codex assistance

Codex may be used during interactive release preparation to:

- Summarize code changes.
- Group changes by category.
- Improve wording.
- Identify possible missing release-note entries.
- Compare the draft against the Changelog.

Codex must not independently publish releases or approve release content.

Codex must not be required for unattended scheduled execution.

If Codex is unavailable, fall back to deterministic Changelog-based generation.

## 7. Changelog Integration

Armory Ledger already has a public Changelog page.

Inspect its existing implementation and identify the best way to reuse release information.

Prefer one maintained source of truth, potentially a root-level `CHANGELOG.md`, if it fits the existing application architecture.

The public Changelog and GitHub release notes should remain consistent.

Avoid requiring the user to manually maintain the same release information in multiple locations.

Preserve historical Changelog entries.

Do not automatically mark an unreleased version as published merely because a scheduled job exists.

If the current Changelog uses planned release dates, preserve the existing presentation unless a change is necessary for correctness.

## 8. Scheduling and Timezones

Scheduled releases must support local time input.

Use an IANA timezone such as:

`America/Chicago`

Store the resolved execution instant in UTC.

Display both the local time and UTC equivalent before approval.

Correctly handle daylight-saving transitions, including ambiguous or nonexistent local times.

Do not rely on fixed CST or CDT offsets.

Use 24-hour time formatting throughout the release workflow.

The scheduling mechanism must survive:

- Shell logout.
- Terminal disconnection.
- Reboots.
- Normal service restarts.

Evaluate `systemd` timers or an equivalent persistent scheduler appropriate for the development host.

Document required permissions and configuration.

## 9. Scheduled Release Execution

When the scheduled time arrives, the system should:

1. Acquire a release lock to prevent concurrent publication.
2. Load the approved release metadata.
3. Verify the repository, candidate commit, version, and release notes.
4. Confirm that the candidate has not changed.
5. Verify that the release has not already been published.
6. Recheck required GitHub connectivity and credentials.
7. Publish the approved commit and version tag using the established GitHub workflow.
8. Create the GitHub release using the saved Markdown notes.
9. Trigger or verify the existing GitHub Actions container publishing workflow.
10. Record the result.

The scheduled execution must not request interactive input.

Do not use `git push --force` or rewrite existing release tags.

If a tag or GitHub release already exists, verify whether it matches the approved candidate before deciding whether execution can safely resume.

## 10. Partial Failures and Recovery

Release publication is a multi-step process and may partially succeed.

Design for recovery from situations such as:

- Git commit created but push failed.
- Candidate pushed but tag creation failed.
- Tag pushed but GitHub release creation failed.
- GitHub release created but container build failed.
- Network connectivity lost.
- GitHub credentials expired.
- Scheduled job interrupted.
- Server reboot during execution.

A retry must not create duplicate releases or publish a different commit.

Record enough state to identify which operations succeeded.

Do not report a release as fully successful merely because `gh release create` succeeded.

Distinguish GitHub release publication from container build completion.

If a failure requires manual intervention, preserve the approved candidate and release notes and provide clear recovery instructions.

## 11. Scheduled Release Management

Provide a straightforward way to inspect scheduled releases.

At minimum, support:

- Viewing pending releases.
- Viewing the approved version and scheduled time.
- Viewing the pinned commit SHA.
- Viewing the saved release notes.
- Viewing the last execution result.
- Cancelling a pending release.

If practical, also support rescheduling a pending release.

Cancelling a pending release must prevent publication.

Rescheduling must preserve the approved candidate and notes unless the user explicitly prepares a replacement.

Do not silently modify a published release.

## 12. GitHub Actions and Container Publishing

Inspect the existing GitHub Actions workflows before implementation.

Confirm how the application container image is built and tagged.

Ensure that both release methods use the same container publishing mechanism.

The image associated with a release must be built from the approved release commit.

Avoid a situation where the GitHub release references one commit but the container image contains later changes.

Preserve the existing image naming conventions where possible:

`ghcr.io/kennithjanderson/armory-ledger:<version>`

Report the resulting release URL and container image reference.

If the GitHub Actions workflow is asynchronous, distinguish a queued or running build from a verified successful build.

## 13. Logging and Auditability

Record meaningful release events:

- Candidate preparation.
- Validation results.
- User approval.
- Approved version.
- Candidate commit SHA.
- Scheduled execution time.
- Release-note file reference.
- Publication attempts.
- GitHub tag and release results.
- Container workflow results.
- Errors and recovery actions.

Avoid logging secrets or authentication tokens.

Use a consistent, readable format.

Keep release metadata outside application runtime data where appropriate.

## 14. Testing Requirements

Do not publish an actual GitHub release while testing.

Implement tests or safe dry-run scenarios for:

### Manual workflow

- Successful preparation.
- Invalid version.
- Existing tag.
- No pending changes.
- Validation failure.
- User cancellation.
- Manual release notes.
- Automatically generated notes.
- Editing generated notes.

### Scheduled workflow

- Valid future date.
- Invalid or past date.
- Timezone conversion.
- Daylight-saving ambiguity.
- Persistent scheduling.
- Candidate commit pinning.
- New commits added after scheduling.
- Cancelled release.
- Rescheduled release.
- Server restart.
- Duplicate execution prevention.
- GitHub unavailable.
- Interrupted execution.
- Safe retry after partial failure.

### Release-note generation

- Existing Changelog entry.
- Missing Changelog entry.
- No relevant commits.
- User-edited notes.
- Codex unavailable.
- Saved notes used without regeneration.
- No post-approval changes included.

Use mocks, temporary Git repositories, or safe test doubles for publishing operations where practical.

## 15. Documentation

Update the appropriate project documentation, including:

- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`

Document:

- Manual release procedure.
- Scheduled release procedure.
- Release-note generation.
- Scheduling configuration.
- Required permissions.
- Cancellation and rescheduling.
- Failure recovery.
- Dry-run testing.
- GitHub Actions integration.

Do not add secrets, credentials, or environment-specific private values to tracked documentation.

## 16. Implementation Approach

Work in stages.

**Stage A — Inspection and design**

Inspect the existing repository and present a concise implementation plan, including the proposed scheduling mechanism, immutable candidate strategy, release-note source, and recovery design.

Identify any assumptions or risks.

**Stop after Stage A and request approval before implementing the design.**

**Stage B — Shared release engine**

Refactor common validation and publishing logic while preserving the existing manual release behavior.

**Stage C — Automated release notes**

Implement Changelog integration, automatic drafting, optional Codex assistance, editing, and approval.

**Stage D — Scheduled releases**

Implement candidate pinning, persistent scheduling, saved metadata, unattended publication, cancellation, and recovery.

**Stage E — Testing and documentation**

Run automated tests, exercise safe dry-run scenarios, update documentation, and report the results.

## 17. Safety and Authorization

All development must occur in the development repository.

Do not modify production.

Do not deploy to production.

Do not create real GitHub releases during development or testing.

Do not push commits or tags without explicit authorization.

Do not schedule an actual publication during implementation without explicit authorization.

The release scripts may perform approved publication actions when the user later runs and authorizes them.

A scheduled release may execute unattended only after the user has explicitly approved its exact version, commit, release notes, and execution time.

## Expected Final Deliverables

Provide:

1. Updated `release.sh`.
2. New `schedule-release.sh`.
3. Shared release logic.
4. Automated release-note generation.
5. Integration with the public Changelog.
6. Persistent scheduled execution.
7. Scheduled release inspection and cancellation.
8. Safe failure recovery.
9. Automated tests and dry-run support.
10. Updated documentation.

Demonstrate a dry-run preparation of Armory Ledger v0.1.3 using its existing Changelog, without creating a real GitHub release.

Report all changed files, test results, unresolved risks, and any setup steps required before the workflow can be used.

Do not commit, push, tag, publish, or deploy as part of completing this instruction.
