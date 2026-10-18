# Manual and scheduled releases

Implemented in development on 2026-10-14. No host jobs, lingering changes, GitHub
publications or application database operations were performed during implementation.
This guide describes commands the operator may run **after reviewing and authorizing
those operations**. A Changelog date is presentation, not evidence of publication.

## Components and trust boundary

- `release.sh` and `schedule-release.sh`: public, configuration-free wrappers.
- `tools/release/engine.py`: candidate preparation, approval, timers, recovery.
- `tools/release/common.py`: checked commands, scanning, notes, timezone conversion.
- `tools/release/validation.py`: isolated candidate tests/build/runtime checks.
- `tools/release/image_policy.py`: Actions image identity and monotonic aliases.
- `app/content/changelog.json`: maintained release-note source for the public page
  and deterministic GitHub Markdown. No duplicate Markdown source is required.
- `.release-config.json`: ignored local paths/settings; copy the example and replace
  placeholders. Never put tokens/passwords here. Git, gh and Docker credential
  stores supply credentials. State defaults outside the repository, under
  `~/.local/state/armory-ledger/releases`.

State contains the candidate SHA/tree/parent, selected version, approved notes and
hashes, validation results, execution time, runner snapshot, progress and JSONL
history. Snapshot checksums detect accidental changes; they do not defend against a
malicious account owner/root who can change code and metadata together. Protect the
host, credential stores, state directory and Git object database. Back up release
state together with the Git repository. Do not hand-edit approved files.

## Required host setup (not performed automatically)

1. Use a persistent Python environment with Python 3.11+ including tar extraction
   filters, Git, Node 18+, gh, Docker with Buildx, and systemd user services. Install
   system timezone data or Python `tzdata` for `zoneinfo`. Keep test dependencies in
   a persistent location, not `/tmp`, for scheduled use. For example:

   ```bash
   python3 -m venv "$HOME/.local/share/armory-release-tests"
   "$HOME/.local/share/armory-release-tests/bin/pip" install -r requirements.txt
   npm install --prefix "$HOME/.local/share/armory-release-js" --no-package-lock --no-audit --no-fund jsdom@24
   cp .release-config.example.json .release-config.json
   ```

   Edit the JSON paths. The Python tests need the project's dependencies including
   psycopg; JavaScript tests need jsdom through `node_path`. The runner itself uses
   the standard library. No dependency installation occurs during publication.

2. Authenticate GitHub and Git transport for the **same user** that will own timers.
   Verify repository contents-write/push and Actions-read access. If using a classic
   token to push workflow changes, ensure its scopes permit that. Use SSH BatchMode
   with a noninteractive credential mechanism, or an approved HTTPS credential helper.
   An unlocked agent tied only to a terminal will not survive logout/reboot. Never
   put credentials into unit files, repository URLs or release metadata.

   ```bash
   gh auth status
   gh api repos/kennithjanderson/armory-ledger --jq '.permissions'
   git ls-remote origin
   docker info
   docker buildx version
   ```

   `docker` must work unattended. The supported alternative configuration is
   `"docker": ["sudo", "-n", "docker"]` if separately approved host policy permits it.
   Docker access is powerful host access; this software does not grant permissions.
   Configure registry authentication separately if private GHCR pulls require it.

3. Verify the user service manager, then separately authorize lingering if scheduled
   releases must survive logout/reboot:

   ```bash
   systemctl --user is-system-running
   loginctl show-user "$USER" -p Linger
   # Administrator setup, only when authorized:
   sudo loginctl enable-linger "$USER"
   loginctl show-user "$USER" -p Linger
   ```

   Scheduling refuses to proceed without `Linger=yes`. The scripts never enable
   lingering themselves. No active units are installed until the interactive
   schedule workflow has received exact candidate/notes/time approval.

4. Include the updated Actions workflow and `tools/release/image_policy.py` in the
   candidate. Static validation rejects a candidate lacking guarded publication.
   Existing older release workflows must not be re-run to publish mutable aliases:
   an old workflow does not gain these protections retroactively. No other workflow
   or publisher should write these image tags outside the serialized policy.

## Candidate preparation and normal development history

Prefer completing ordinary, reviewed development commits on `main` **before**
preparing a candidate. This is the simplest way to keep all feature changes in normal
history. A clean HEAD is a valid candidate; there need not be a new working-tree diff.

For last-minute pending changes, enter each exact file path when prompted. Tracked,
staged and untracked files are displayed but none are implicitly selected. The
private index starts from HEAD, then adds only selected working-tree files. It does
not modify the real index, move local main, reset files or add all untracked files.
Review the candidate file summary and selected content before approving it.

After validation and note review, `CREATE CANDIDATE` authorizes a local candidate
commit with the exact tree and current main as parent. A dedicated
`refs/armory/releases/<id>` keeps it reachable locally even if main moves. The final
approval includes its full SHA, version, notes and immediate/scheduled UTC time.
Declining final approval leaves a **prepared, unapproved** candidate for inspection;
it cannot publish. Cancel it to record abandonment, or prepare a replacement.

Publication pushes the exact candidate to `release-candidates/vX.Y.Z`, then an
annotated `vX.Y.Z` tag pointing to that commit. The release tag permanently retains
reachability even after a candidate branch is eventually removed. Never move or
rewrite release tags. Scheduled publication does **not** push main. Manual publication
also attempts a non-force update of remote main to the candidate; divergence stops
publication rather than rewriting history. Local main/worktree/index remain untouched.

If the candidate contained uncommitted features, those changes exist on its branch
and tag, **not automatically on local main**. Before continuing normal development,
review and commit remaining working-tree work, then merge the candidate reference
into main using ordinary Git review/conflict resolution. With a clean unchanged
main, a fast-forward merge may suffice. If main has advanced, merge the candidate
branch without resetting or force-pushing. Do not discard work to make this succeed.
Check containment before deleting candidate references:

```bash
git merge-base --is-ancestor vX.Y.Z main
```

Do not delete `refs/armory/releases/<id>` or state while its job is pending/recoverable.
Candidate commits and notes never change during retries; changes require a separately
prepared and approved candidate, not automatic substitution from current main.

## Validation and secret review

Preparation and execution both validate the exact archived candidate. Validation:

- Confirms repository/remote, strict version, tag absence or exact retry identity.
- Checks Git objects and candidate whitespace; verifies source version and guarded
  publishing workflow; scans file names/content for runtime files, private keys,
  known token formats, credential URLs, literal secrets and private references.
- Builds a clean candidate image. Starts a unique isolated PostgreSQL 17 container
  with tmpfs data and generated credentials, never the configured app database.
  Validation uses its own non-internal bridge network so Docker can publish dynamic
  ports bound only to 127.0.0.1 for PostgreSQL and the candidate application. It does
  not join existing application networks; the bridge permits outbound networking.
- Runs all Python tests, including opt-in PostgreSQL concurrency tests against that
  disposable database, and all Node tests using the configured test environment.
- Starts a unique candidate application using synthetic settings. Startup migrations
  run only against the disposable DB. Checks health/database/version, login, protected
  dashboard/admin redirects and public About/Changelog routes.
- Removes only its unique containers/network/image. It never runs Compose, restarts
  normal development services, mounts application data or reads application `.env`.

Output from failed external commands is withheld to avoid credential leakage. Errors
identify the failed tool/check; investigate using controlled synthetic inputs. Do not
paste raw container logs or environment dumps into public reports. Scanning is defense
in depth, not proof that secrets cannot exist (especially binary/encoded material).

False positives require human review. An optional version-controlled
`release-scan-allowlist.json` maps **exact path + rule + SHA256 of the complete line**
to `{ "reason": "review rationale" }`. Example key shape:
`tests/example.py:credential-url:<64-character-line-hash>`. Never allowlist real
credentials. Any line change invalidates its exception. Private runtime/key files
and symlinks cannot be allowlisted. Review untracked task instructions and old docs
carefully; do not include private installation references just to clear a scan.
No broad domain/path exclusions or automatic allowlist creation are provided.

## Manual publication

```bash
./release.sh
```

Enter version and explicit file selections. Choose `manual`, `auto`, or `edit` notes.
Manual mode reads an existing Markdown file without overwriting it. Edit mode opens
`VISUAL`/`EDITOR` on a temporary generated draft. Deterministic generation uses the
candidate Changelog, with candidate-range file changes/commit summaries as a clearly
labeled editorial fallback. It never invents features or test results. You may ask
Codex to edit the draft interactively, but review the resulting file yourself; no
Codex executable is invoked or needed by this workflow.

`VALIDATE` authorizes disposable validation. `CREATE CANDIDATE` authorizes only the
local candidate commit. Final `APPROVE <version> <full-SHA>` authorizes publication
of that exact candidate and displayed notes. Publication pushes without force,
creates the annotated tag, and creates the GitHub release using the saved notes.
GitHub's own latest-release designation is not automatically reassigned.

## Scheduling

```bash
./schedule-release.sh
```

Select IANA zone (environment/system zone default, UTC fallback) and local
`YYYY-MM-DD HH:mm`. Spring-forward gaps fail. Repeated fall-back times require
`earlier` or `later`. Both local and UTC times appear before approval; past times,
including a time that elapsed during validation, fail rather than publishing early.

After approval, user `.service`/`.timer` files are installed under
`~/.config/systemd/user/`. The unit executes the saved runner snapshot, not the moving
working-tree scripts. `OnCalendar` uses UTC; `Persistent=true` handles missed triggers.
Boot and five-minute inactive checks recover an interrupted due job after restart.
Before the approved time, or after cancellation/completion, execution is a no-op.
Service failures retry after five minutes. No input, git add, new commit or note
regeneration occurs in unattended execution. Revalidation failure stops before any
new publication operation, retaining the candidate and approved notes.

Verify a real approved job after scheduling:

```bash
systemctl --user list-timers 'armory-release-*'
systemctl --user status armory-release-<id>.timer
systemctl --user cat armory-release-<id>.service
journalctl --user -u armory-release-<id>.service
```

No job was installed or scheduled during implementation/testing.

## Inspection, cancellation, rescheduling and recovery

Use the same state root configured during preparation; a custom root requires
`--state-dir` for listing. `<state>` means the full path to one release's state folder.

```bash
python3 tools/release/engine.py list
python3 tools/release/engine.py inspect --state <state>
python3 tools/release/engine.py units --state <state>
python3 tools/release/engine.py cancel --state <state>
python3 tools/release/engine.py reschedule --state <state> --local '2026-10-15 09:00' --timezone America/Chicago
```

Inspection includes SHA, saved notes, schedule, validation results and last stage.
Cancellation writes a tombstone before disabling the timer/service; a stale queued
unit will refuse publication. Operations share a global lock. If publication holds
it, cancellation fails explicitly rather than falsely claiming the release stopped.
Once publication has started, cancellation/rescheduling is refused: inspect remote
state and recover the approved release instead. Cancellation cannot undo a push.
Rescheduling requires explicit confirmation and preserves the candidate and notes.

Retry the saved runner, with the same state, after resolving connectivity/credential
or workflow failures:

```bash
python3 <state>/engine/engine.py execute --state <state>
```

A retry checks local/remote tags against the approved SHA and published notes against
the saved body. Existing matching operations are reused; differing tags/notes stop
for manual review. If remote main diverged during a manual release, resolve history
through normal review; do not force-push or edit the approved candidate. If validation
can no longer pass for that candidate, do not publish a replacement under its approval.
Prepare a new release deliberately after resolving any partial remote state.

The statuses **github_published** and **complete** are distinct. A queued/failed
container workflow is not full success. The runner finds the release-event run for
that tag/SHA, requires success, downloads its receipt, pulls the version image and
checks OCI revision/version labels plus registry digest against the receipt. A retry
can finish verification without creating another release. Re-run the exact failed
Actions run if necessary; never dispatch a build from moving main as a substitute.
Receipts expire after 90 days; after expiry re-run the matching workflow for a new
receipt and review registry identity rather than bypassing checks.

Completed timers are harmless no-ops but can be removed from active scheduling:

```bash
systemctl --user disable --now armory-release-<id>.timer
```

Keep state, Git refs and event history for audit/recovery. A same-user/root attacker
can alter these controls; this is an operator tool, not a security boundary against
its account owner.

## Container identity and latest protection

The release-published Actions job checks out the exact tag and resolves its commit.
It embeds OCI revision/version labels. Existing version images may only be reused
when those labels match; different commits cannot overwrite the version tag.

A shared concurrency group with `queue: max` serializes all release publication.
After building the immutable version, the policy reads published stable versions
and the existing alias image labels. It advances `latest` only if no higher stable
version is published or already at that alias; major/minor aliases use the same
comparison within their series. Unknown labels/API errors fail closed. Therefore an
older scheduled release can publish its own version image without moving `latest`
backward. If a newer release's build failed, the older release still cannot claim
latest ahead of it. The verified digest/SHA/version are saved as a workflow artifact.

The published references are `https://github.com/<owner>/<repo>/releases/tag/vX.Y.Z`
and `ghcr.io/<owner>/<repo>:X.Y.Z`; full success also reports the verified digest.
Build dependencies/base images remain unpinned as in the existing project; identical
source commits do not guarantee bit-for-bit reproducible builds. Digest verification
identifies what this workflow actually published.

References: [GitHub concurrency queues](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/),
[workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[Docker image labels](https://docs.docker.com/engine/manage-resources/labels/),
[image digests](https://docs.docker.com/dhi/explore/security-concepts/digests/).

## Safe tests and dry-run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 ./tools/release/engine.py manual --repo "$PWD" --version 0.1.3 --dry-run
# Equivalent wrapper:
PYTHONDONTWRITEBYTECODE=1 ./release.sh --version 0.1.3 --dry-run
PYTHONDONTWRITEBYTECODE=1 /path/to/test/python -m unittest discover -s tests -p 'test_release_workflow.py' -v
```

Dry-run reads status/history/working-tree Changelog and displays the draft. It does
not create an index, candidate commit, tag, state, timer, container or GitHub object;
it does not claim a validated/approved candidate. Both wrappers support it.
Tests use temporary Git repositories and mocks for Docker, GitHub, registry, clock
and systemd operations. Live host scheduling/reboot and end-to-end publishing remain
operator acceptance checks after explicit authorization, never automatic test steps.

## Isolated validation without a release

```bash
./release.sh --validate-only --version 0.1.3
# Equivalent engine command:
python3 tools/release/engine.py manual --repo "$PWD" --validate-only --version 0.1.3
```

Use the persistent test Python/Node and Docker settings described above. This mode
needs Docker access and test dependencies, but no GitHub authentication, timer setup
or lingering. It may download build dependencies/container images; it never pushes.
It cannot be combined with `--dry-run` or a scheduling/recovery command.

Enter exact repository-relative **file** paths, one per prompt, including any
untracked files required by the implementation. A blank line finishes selection;
empty selection tests HEAD. The baseline is HEAD plus selected working-tree file
contents/deletions, not the real index. Staged changes are not implicitly included.
Review the displayed stat and full diff (after the secret scan), then type `VALIDATE`.
The Git tree hash identifies the frozen source; subsequent edits are not included.
Archive attributes that omit or substitute content cause validation to stop.

This reuses release candidate validation: static/version/secret checks, a clean
Docker build, unique disposable PostgreSQL, Python tests with PostgreSQL enabled,
JavaScript tests, startup migrations, a check that the disposable database is at
all migration heads, and application health/version/HTTP authorization checks.
The summary lists individual check outcomes and cleanup, including on failure;
failed validation exits nonzero. A failed early check leaves later checks unrun.

No candidate commit, branch, tag, notes, approval, release state/lock, timer or GitHub
release is created. No normal development containers/database are used. Selection
uses a temporary Git index; Git may retain unreachable blob/tree objects until normal
Git garbage collection, but the real index, HEAD and refs are unchanged.

Unique containers, network, image and generated environment files are cleaned on
success, failure, Ctrl-C and SIGTERM. Cleanup attempts continue if an individual
removal fails; failures exit nonzero and identify resources requiring manual cleanup.
SIGKILL, host power loss or an unavailable Docker daemon cannot guarantee cleanup;
review the reported `armory-release-test-*` resources before removing only those.
Validation-only success is not publication approval and does not save a resumable
candidate. Manual and scheduled releases still perform their own validation.

### Reviewed bulk selection for validation and preparation

```bash
./release.sh --validate-only --version 0.1.3 --include-all-changes
```

Git discovers modified, staged, added, deleted, renamed and untracked files using
NUL-delimited status records. Untracked directories are expanded into individual
files; ignored untracked files are excluded. Tracked files remain eligible even
if a later ignore rule matches them. Rename source and destination paths are both
included. Staged files use current working-tree contents, not an older staged copy.
A staged addition subsequently deleted from disk contributes no file to the tree.

The engine displays every selected path (JSON-quoted to make unusual names visible)
and requires `INCLUDE ALL CHANGES` before constructing the temporary index/tree.
It rejects symlinks, submodules, nonregular files, conflicted entries, control
characters and potentially sensitive filenames such as private environment files,
keys and databases. Resolve those findings or return to individual-file selection;
there is no bulk bypass. The existing source secret scan and final `VALIDATE`
approval still apply. File-list changes during confirmation require another review.

Without this option, individual-file prompts remain available. Bulk selection now
also supports manual and scheduled preparation. It is rejected for dry-run and
recovery commands. It never stages the real index or grants publication approval.

```bash
./release.sh --version 0.1.3 --include-all-changes --expected-tree FULL_TREE_SHA
./schedule-release.sh --version 0.1.3 --include-all-changes --expected-tree FULL_TREE_SHA
```

`--expected-tree` is optional for preparation and validation-only. Supply a full
40-character SHA-1 or 64-character SHA-256 Git tree hash, not a commit hash or
abbreviation. The selected tree must match before validation/candidate creation;
a mismatch stops without creating a candidate or publishing. The current selected
tree and HEAD are checked again immediately before creating the candidate.

Bulk preparation retains INCLUDE ALL CHANGES, VALIDATE, release-note review,
CREATE CANDIDATE and final APPROVE prompts. Scheduling also requires a future local
date/time with timezone handling and successful lingering verification. A timer
is installed only after final approval. An expected tree does not bypass validation.

Any selected source edits, including release tooling or documentation edits, change
the tree hash. Revalidate and review the new identity before using it as the expected
tree; the engine never updates or silently replaces the supplied hash.

## GitHub Latest designation — v0.1.4

Both manual and scheduled publication initially create the GitHub release without
promoting Latest. After immutable image identity verification, the serialized
publication workflow promotes the GitHub release using `gh release edit --latest`
only when no newer stable semantic version has been published. The workflow needs
`contents: write` for this designation. Container alias guards remain unchanged.
This fixes scheduled releases remaining unmarked; GitHub publication and verified
container completion remain distinct milestones. Existing saved scheduled runners
and workflows at older tags are immutable and are not rewritten by this change.
