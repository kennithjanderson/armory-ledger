#!/usr/bin/env python3
"""Interactive/manual and immutable scheduled releases. Dry-run has no external effects."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import sys
import tarfile
import tempfile
import time
import uuid

from common import (ReleaseError, assert_scan, canonical, default_zone, event, git, locked,
                    release_notes, require, resolve_time, run, save_json, sha256, version)
from validation import static_validate, validate

DEFAULT_REPOSITORY = 'kennithjanderson/armory-ledger'
ENGINE_FILES = ('engine.py', 'common.py', 'validation.py')


class PendingVerification(ReleaseError):
    """GitHub publication exists, but container verification has not finished."""



def repository(path, expected):
    root = Path(git(path, 'rev-parse', '--show-toplevel')).resolve()
    require(root == Path(path).resolve(), 'Run against the repository root')
    require(expected.count('/') == 1 and all(part.replace('-', '').replace('_', '').replace('.', '').isalnum() for part in expected.split('/')), 'Invalid GitHub repository name')
    remote = git(root, 'remote', 'get-url', 'origin')
    allowed = {f'git@github.com:{expected}.git', f'https://github.com/{expected}.git',
               f'https://github.com/{expected}', f'ssh://git@github.com/{expected}.git'}
    require(remote in allowed, 'Origin does not match the configured GitHub repository')
    return root


def remote_tag(repo, target):
    tag = 'refs/tags/v' + target
    output = git(repo, 'ls-remote', '--tags', 'origin', tag, tag + '^{}')
    refs = dict(line.split()[::-1] for line in output.splitlines())
    return refs.get(tag + '^{}', refs.get(tag))


def local_tag(repo, target):
    names = git(repo, 'tag', '--list', 'v' + target)
    return git(repo, 'rev-parse', f'refs/tags/v{target}^{{commit}}') if names else None


def github_access(expected):
    record = json.loads(run(['gh', 'api', f'repos/{expected}']))
    require(record.get('full_name', '').lower() == expected.lower(), 'GitHub repository mismatch')
    require(record.get('permissions', {}).get('push') is True, 'GitHub authentication lacks repository push permission')


@contextmanager
def exported(repo, tree):
    with tempfile.TemporaryDirectory(prefix='armory-candidate-') as folder:
        folder = Path(folder); archive = folder / 'candidate.tar'; root = folder / 'source'; root.mkdir()
        git(repo, 'archive', '--format=tar', '-o', str(archive), tree)
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                require(not member.issym() and not member.islnk() and (member.isfile() or member.isdir()), 'Candidate archive contains unsupported file type')
                require(not Path(member.name).is_absolute() and '..' not in Path(member.name).parts, 'Unsafe archive path')
            stream.extractall(root, filter='data')
        yield root


def discover_changes(repo):
    """NUL-delimited porcelain includes both paths of staged renames."""
    output = git(repo, 'status', '--porcelain=v2', '-z', '--untracked-files=all',
                 '--ignore-submodules=none', env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    records = iter(output.split('\0'))
    paths = set()
    for record in records:
        if not record: continue
        kind = record[0]
        require(kind != 'u', 'Resolve merge conflicts before bulk selection')
        if kind == '?':
            paths.add(record[2:])
        elif kind == '1':
            paths.add(record.split(' ', 8)[8])
        elif kind == '2':
            paths.add(record.split(' ', 9)[9])
            paths.add(next(records))
        else:
            raise ReleaseError('Unexpected Git status record')
    return sorted(paths)


def bulk_selection(repo):
    paths = discover_changes(repo)
    print(f'Exact bulk selection ({len(paths)} files; working-tree contents):')
    issues = []
    for path in paths:
        print('  ' + json.dumps(path))
        source = Path(repo) / path
        parts = Path(path).parts
        if any(ord(c) < 32 for c in path):
            issues.append((path, 'unexpected control character in filename'))
        if any((Path(repo).joinpath(*parts[:n])).is_symlink() for n in range(1, len(parts)+1)):
            issues.append((path, 'symlink'))
        elif source.exists() and not source.is_file():
            issues.append((path, 'directory, submodule or special file'))
        entries = git(repo, 'ls-files', '--stage', '--', path,
                      env=dict(os.environ, GIT_LITERAL_PATHSPECS='1'))
        original = git(repo, 'ls-tree', 'HEAD', '--', path,
                       env=dict(os.environ, GIT_LITERAL_PATHSPECS='1'))
        if any(entry.startswith(('160000 ', '120000 ')) for entry in (entries, original)):
            issues.append((path, 'submodule or tracked symlink'))
        if (source.name in ('.env', 'compose.yaml', '.release-config.json')
                or (source.name.startswith('.env.') and source.name != '.env.example')
                or source.suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.pfx')
                or any(part.lower() in ('secrets', 'credentials', '.ssh', '.aws') for part in parts)):
            issues.append((path, 'potentially sensitive file'))
    for path, reason in issues:
        print(f'REJECTED {json.dumps(path)}: {reason}')
    require(not issues, 'Bulk selection contains unsafe/unexpected files; review or use individual selection')
    confirm('Approve the exact file list before constructing the temporary tree.', 'INCLUDE ALL CHANGES')
    require(discover_changes(repo) == paths, 'Changed-file list changed during review; repeat selection')
    return paths


def selected_tree(repo, paths):
    """Private index: never stage/reset the user's real index."""
    with tempfile.TemporaryDirectory(prefix='armory-index-') as folder:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder) / 'index'), GIT_LITERAL_PATHSPECS='1')
        git(repo, 'read-tree', 'HEAD', env=env)
        if paths:
            for path in paths:
                require(path and not Path(path).is_absolute() and '..' not in Path(path).parts and path != '.', 'Choose explicit repository-relative file paths')
                require(not (Path(repo) / path).is_dir(), 'Select files, not entire directories')
            tracked = set(git(repo, 'ls-tree', '-rz', '--name-only', 'HEAD').split('\0'))
            # A staged addition removed from disk has no HEAD content to delete.
            effective = [path for path in paths if path in tracked or (Path(repo) / path).exists() or (Path(repo) / path).is_symlink()]
            if effective:
                git(repo, 'add', '-A', '--', *effective, env=env)
        git(repo, 'diff', '--cached', '--check', env=env)
        return git(repo, 'write-tree', env=env)


def history(repo, commit):
    tags = git(repo, 'tag', '--merged', commit, '--sort=-version:refname').splitlines()
    previous = next((tag for tag in tags if __import__('re').fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag)), None)
    return git(repo, 'log', '--format=%s', f'{previous}..{commit}' if previous else commit).splitlines()


def choose_notes(root, target, commits, mode, notes_file=None, changes=()):
    if mode == 'manual':
        require(notes_file is not None, 'Manual notes require a file; they are never automatically replaced')
        notes = Path(notes_file).read_text()
    else:
        notes = release_notes(root, target, commits, changes)
    if mode == 'edit':
        editor = shlex.split(os.environ.get('VISUAL') or os.environ.get('EDITOR') or '')
        require(bool(editor), 'Set EDITOR or VISUAL, or use manual notes from a file')
        with tempfile.TemporaryDirectory(prefix='armory-notes-') as folder:
            path = Path(folder) / 'notes.md'; path.write_text(notes)
            result = __import__('subprocess').run([*editor, str(path)], check=False)
            require(result.returncode == 0, 'Editor failed; notes were not approved')
            notes = path.read_text()
    require(bool(notes.strip()), 'Release notes cannot be empty')
    with tempfile.TemporaryDirectory(prefix='armory-notes-scan-') as folder:
        (Path(folder) / 'notes.md').write_text(notes)
        assert_scan(folder)
    return notes.replace('\r\n', '\n')


def confirm(message, expected):
    require(input(f'{message}\nType {expected!r} to approve: ').strip() == expected, 'Cancelled; no approval recorded')


def frozen_payload(folder):
    folder = Path(folder)
    require(not folder.is_symlink(), 'Symlinked release state is not allowed')
    record = json.loads((folder / 'approval.json').read_text())
    payload = record['payload']
    require(sha256(canonical(payload)) == record['sha256'], 'Approved metadata changed')
    require(payload['id'] == folder.name, 'Release state ID mismatch')
    require(version(payload['version']) == payload['version'], 'Invalid approved version')
    require(sha256((folder / 'notes.md').read_bytes()) == payload['notes_sha256'], 'Approved release notes changed')
    for name, digest in payload['engine_sha256'].items():
        require(name in ENGINE_FILES and sha256((folder / 'engine' / name).read_bytes()) == digest, 'Approved release runner changed')
    require(set(payload['engine_sha256']) == set(ENGINE_FILES), 'Incomplete approved release runner')
    return payload


def status(folder):
    return json.loads((Path(folder) / 'status.json').read_text())


def scheduled_release_rows(state_dir, now=None, home=None):
    """Read saved schedule and user-timer health without changing release state."""
    now = now or datetime.now(timezone.utc)
    home = Path(home or Path.home())
    rows = []
    for approval in sorted(Path(state_dir).expanduser().glob('*/approval.json')):
        folder = approval.parent
        payload = frozen_payload(folder)
        state = status(folder)
        if not state.get('scheduled') and not state.get('when'):
            continue

        when = datetime.fromisoformat(state['when']) if state.get('when') else None
        timer = state.get('timer')
        stage = state.get('stage', 'unknown')
        timer_state = 'not configured'
        timer_next = None
        timer_matches = False
        if timer:
            unit_path = home / '.config/systemd/user' / f'{timer}.timer'
            expected_calendar = (when.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                                 if when else None)
            try:
                unit_text = unit_path.read_text()
                calendar_matches = any(
                    line.strip() == f'OnCalendar={expected_calendar}'
                    for line in unit_text.splitlines()
                ) if expected_calendar else False
                properties = run(['systemctl', '--user', 'show', '--no-pager',
                                  '--property=ActiveState', '--property=UnitFileState',
                                  '--property=NextElapseUSecRealtime', f'{timer}.timer'])
                values = dict(line.split('=', 1) for line in properties.splitlines() if '=' in line)
                active = values.get('ActiveState') == 'active'
                enabled = values.get('UnitFileState') == 'enabled'
                timer_next = values.get('NextElapseUSecRealtime') or None
                expected_next = (when.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
                                 if when and when > now else None)
                next_matches = (expected_next in timer_next if expected_next and timer_next else
                                bool(when and when <= now))
                timer_matches = calendar_matches and active and enabled and next_matches
                timer_state = ('active and enabled' if timer_matches else
                               f"needs attention (active={values.get('ActiveState', 'unknown')}, "
                               f"enabled={values.get('UnitFileState', 'unknown')}, "
                               f"schedule_matches={'yes' if calendar_matches else 'no'}, "
                               f"next_trigger_matches={'yes' if next_matches else 'no'})")
            except (OSError, ReleaseError):
                timer_state = 'unavailable or missing'

        if state.get('cancelled') or stage == 'cancelled':
            release_status, timing = 'Cancelled', 'N/A'
        elif stage == 'complete':
            release_status, timing = 'Complete', 'N/A'
        elif stage == 'failed':
            release_status, timing = 'Failed; review required', 'Delayed'
        elif state.get('github_published') or stage.startswith('container_'):
            release_status = 'Published; container verification pending'
            timing = 'Delayed' if when and now >= when else 'On-Target'
        elif stage in {'validating', 'publication_started', 'candidate_pushed',
                       'main_pushed', 'tag_pushed', 'github_published'}:
            release_status = 'In progress'
            timing = 'On-Target' if timer_matches or (when and now <= when) else 'Delayed'
        elif when and now >= when:
            release_status, timing = 'Scheduled; execution overdue', 'Delayed'
        elif timer_matches:
            release_status, timing = 'Scheduled', 'On-Target'
        else:
            release_status, timing = 'Schedule needs attention', 'Delayed'

        local_when = when.astimezone().strftime('%Y-%m-%d %H:%M %Z') if when else 'Not set'
        utc_when = when.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if when else 'Not set'
        rows.append({
            'version': payload['version'], 'sha': payload['sha'], 'when_local': local_when,
            'when_utc': utc_when, 'status': release_status, 'timing': timing,
            'timer': timer_state, 'timer_next': timer_next,
        })
    return rows


def print_scheduled_release_status(state_dir, now=None, home=None):
    rows = scheduled_release_rows(state_dir, now=now, home=home)
    print('Armory Ledger Scheduled Release Status')
    if not rows:
        print('No saved scheduled releases found.')
        return
    for row in rows:
        print(f"\nRelease version: v{row['version']}")
        print(f"Scheduled date/time: {row['when_local']} ({row['when_utc']})")
        print(f"Status: {row['status']}")
        print(f"Timing: {row['timing']}")
        print(f"Timer: {row['timer']}")
        if row['timer_next']:
            print(f"Timer next trigger: {row['timer_next']}")
        print(f"Candidate: {row['sha']}")
    print('\nTiming reports local schedule/timer health only; it does not contact GitHub or verify image publication.')


def update(folder, stage, **extra):
    data = status(folder); data.update(stage=stage, **extra); save_json(Path(folder) / 'status.json', data)
    event(folder, stage, **extra)


def make_candidate(repo, tree, parent, target, release_id):
    sha = git(repo, 'commit-tree', tree, '-p', parent, input=f'Release candidate v{target}\n')
    git(repo, 'update-ref', f'refs/armory/releases/{release_id}', sha, '0' * 40)
    return sha


def expected_tree_sha(value):
    if not __import__('re').fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', value):
        raise argparse.ArgumentTypeError('Expected a full Git tree SHA (40 or 64 hexadecimal characters)')
    return value.lower()


def check_expected_tree(tree, expected):
    if expected is not None:
        require(tree == expected_tree_sha(expected),
                f'Selected tree {tree} does not match expected tree {expected}; no candidate created')


def prepare(repo, config, target, paths, mode, notes_file, when=None, expected_tree=None):
    expected = config['repository']
    repository(repo, expected)
    require(git(repo, 'branch', '--show-current') == 'main', 'Prepare candidates from main')
    parent = git(repo, 'rev-parse', 'HEAD')
    tree = selected_tree(repo, paths)
    check_expected_tree(tree, expected_tree)
    require(not local_tag(repo, target) and not remote_tag(repo, target), 'Release tag already exists')
    github_access(expected)
    git(repo, 'fsck', '--no-reflogs')
    print('Candidate file summary:\n' + git(repo, 'diff', '--stat', parent, tree))
    root_state = Path(config['state_dir']).expanduser().resolve()
    root_state.mkdir(parents=True, exist_ok=True, mode=0o700)
    event(root_state, 'preparation_started', version=target, tree=tree)
    with exported(repo, tree) as root:
        static_validate(root, target)
        confirm('Validate this exact candidate using disposable containers (no application DB)?', 'VALIDATE')
        event(root_state, 'validation_started', tree=tree)
        try:
            results = validate(root, target, config)
        except Exception:
            event(root_state, 'validation_failed', tree=tree)
            raise
        event(root_state, 'validation_passed', tree=tree, results=results)
        tags = git(repo, 'tag', '--merged', parent, '--sort=-version:refname').splitlines()
        previous = next((tag for tag in tags if __import__('re').fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag)), None)
        baseline = previous or '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
        changes = git(repo, 'diff', '--name-status', baseline, tree).splitlines()
        notes = choose_notes(root, target, history(repo, parent), mode, notes_file, changes)
    print(notes)
    confirm(f'Create an immutable LOCAL candidate commit for tree {tree}?\nNo remote publication yet.', 'CREATE CANDIDATE')
    require(git(repo, 'rev-parse', 'HEAD') == parent and selected_tree(repo, paths) == tree, 'Selected source changed during preparation; prepare again')
    release_id = 'v' + target + '-' + uuid.uuid4().hex[:12]
    root_state = Path(config['state_dir']).expanduser().resolve()
    folder = root_state / release_id; folder.mkdir(parents=True, mode=0o700)
    current_tree = selected_tree(repo, paths)
    check_expected_tree(current_tree, expected_tree)
    require(git(repo, 'rev-parse', 'HEAD') == parent and current_tree == tree, 'Selected source changed before candidate creation; prepare again')
    sha = make_candidate(repo, tree, parent, target, release_id)
    (folder / 'engine').mkdir(mode=0o700)
    for name in ENGINE_FILES:
        shutil.copyfile(Path(__file__).parent / name, folder / 'engine' / name)
    (folder / 'notes.md').write_text(notes); (folder / 'notes.md').chmod(0o600)
    payload = {'id': release_id, 'repo': str(Path(repo).resolve()), 'repository': expected,
               'version': target, 'sha': sha, 'tree': tree, 'parent': parent,
               'notes_sha256': sha256(notes.encode()), 'config': config,
               'engine_sha256': {name: sha256((folder / 'engine' / name).read_bytes()) for name in ENGINE_FILES}}
    save_json(folder / 'approval.json', {'payload': payload, 'sha256': sha256(canonical(payload))})
    save_json(folder / 'status.json', {'stage': 'prepared', 'approved': False, 'cancelled': False,
                                     'when': when, 'scheduled': when is not None, 'validation': results})
    event(folder, 'candidate_prepared', sha=sha, version=target)
    print(f'Candidate: {sha}\nNotes: {folder / "notes.md"}\nExecution UTC: {when or "immediate"}\nCandidate will remain reachable through its release tag after publication.')
    require(when is None or datetime.fromisoformat(when) > datetime.now(timezone.utc), 'Scheduled time elapsed during preparation; candidate retained but not approved')
    confirm('Approve these exact notes, commit, version and execution time?', f'APPROVE {target} {sha}')
    update(folder, 'approved', approved=True, approved_at=datetime.now(timezone.utc).isoformat(), approved_by_uid=os.getuid(), when=when, notes_sha256=payload['notes_sha256'])
    return folder


def systemd_quote(value):
    require('\n' not in value and '\r' not in value, 'Invalid systemd argument')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def timer_units(folder, instant, python=sys.executable):
    folder = Path(folder).resolve()
    when = datetime.fromisoformat(instant).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    command = ' '.join(systemd_quote(str(value)) for value in [python, folder / 'engine/engine.py', 'execute', '--state', folder])
    service = ('[Unit]\nDescription=Approved Armory Ledger release\nWants=network-online.target\nAfter=network-online.target\n'
               '[Service]\nType=oneshot\nUMask=0077\nEnvironment=GIT_TERMINAL_PROMPT=0\nEnvironment=GH_PROMPT_DISABLED=1\n'
               f'ExecStart={command}\nTimeoutStartSec=2h\nRestart=on-failure\nRestartSec=300\n'
               '[Install]\nWantedBy=default.target\n')
    timer = f'[Unit]\nDescription=Armory Ledger approved release timer\n[Timer]\nOnCalendar={when}\nPersistent=true\nOnBootSec=2min\nOnUnitInactiveSec=5min\nAccuracySec=1s\n[Install]\nWantedBy=timers.target\n'
    return service, timer


def install_timer(folder):
    payload = frozen_payload(folder); state = status(folder)
    require(state['approved'] and not state['cancelled'] and state.get('when'), 'Schedule is not approved')
    units = timer_units(folder, state['when'], payload['config'].get('runner_python', sys.executable))
    directory = Path.home() / '.config/systemd/user'; directory.mkdir(parents=True, exist_ok=True)
    name = 'armory-release-' + payload['id']
    for extension, content in zip(('service', 'timer'), units):
        path = directory / f'{name}.{extension}'; path.write_text(content); path.chmod(0o600)
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'enable', '--now', name + '.timer'])
    update(folder, 'scheduled', timer=name)


def github_release(expected, tag):
    # A successful list distinguishes "not found" from network/auth errors.
    matches = []
    for page in range(1, 1001):
        releases = json.loads(run(['gh', 'api', f'repos/{expected}/releases?per_page=100&page={page}']))
        require(isinstance(releases, list), 'Invalid GitHub release-list response')
        matches.extend(release for release in releases if release['tag_name'] == tag)
        if len(releases) < 100:
            require(len(matches) <= 1, 'Multiple matching GitHub releases')
            return matches[0] if matches else None
    raise ReleaseError('Release enumeration exceeded limit; stop for review')



def verify_image(payload, folder):
    expected, sha, target = payload['repository'], payload['sha'], payload['version']
    runs = json.loads(run(['gh', 'api', f'repos/{expected}/actions/workflows/docker-publish.yml/runs?event=release&head_sha={sha}&per_page=100']))['workflow_runs']
    matching = [item for item in runs if item['head_sha'] == sha and item.get('head_branch') == 'v' + target and item['event'] == 'release']
    if not matching:
        raise PendingVerification('GitHub release published; matching container workflow not yet available. Retry later.')
    attempt = max(matching, key=lambda item: (item['id'], item.get('run_attempt', 1)))
    update(folder, 'container_' + attempt['status'], workflow_run=attempt['id'])
    if attempt['status'] != 'completed':
        raise PendingVerification('GitHub release published; container workflow is queued/running, not yet verified. Retry later.')
    require(attempt['conclusion'] == 'success', 'GitHub release published; container workflow failed. Inspect/re-run that exact workflow, then retry.')
    with tempfile.TemporaryDirectory(prefix='armory-receipt-') as temp:
        run(['gh', 'run', 'download', str(attempt['id']), '--repo', expected, '--name', 'release-receipt', '--dir', temp])
        receipt = json.loads((Path(temp) / 'release-receipt.json').read_text())
    require(receipt.get('commit') == sha and receipt.get('version') == target, 'Container receipt does not match approved candidate')
    digest = receipt.get('digest', '')
    require(__import__('re').fullmatch(r'sha256:[a-f0-9]{64}', digest), 'Invalid container digest')
    image = f'ghcr.io/{expected.lower()}:{target}'
    docker = payload['config'].get('docker', ['docker'])
    run([*docker, 'pull', image])
    inspection = json.loads(run([*docker, 'image', 'inspect', image]))[0]
    labels = inspection.get('Config', {}).get('Labels') or {}
    require(labels.get('org.opencontainers.image.revision') == sha and labels.get('org.opencontainers.image.version') == target, 'Published image revision/version mismatch')
    require(f'ghcr.io/{expected.lower()}@{digest}' in inspection.get('RepoDigests', []), 'Registry version tag no longer matches verified workflow digest')
    update(folder, 'complete', image=image, digest=digest, github_published=True, container_verified=True, waiting_for_container=False)
    print(f'Release: https://github.com/{expected}/releases/tag/v{target}\nVerified image: {image}@{digest}')


def publish(folder, validator=validate, verifier=verify_image):
    """Caller holds global lock. No prompts, staging, commits or note generation here."""
    payload = frozen_payload(folder); state = status(folder)
    require(state['approved'], 'Release lacks explicit approval')
    if state['cancelled']:
        return
    if state['stage'] == 'complete':
        return
    if state.get('when'):
        if datetime.now(timezone.utc) < datetime.fromisoformat(state['when']):
            return
    repo = repository(payload['repo'], payload['repository'])
    sha, target, expected = payload['sha'], payload['version'], payload['repository']
    require(git(repo, 'rev-parse', sha + '^{tree}') == payload['tree'], 'Approved candidate tree mismatch')
    require(git(repo, 'rev-parse', f'refs/armory/releases/{payload["id"]}') == sha, 'Candidate retention reference changed')
    require(local_tag(repo, target) in (None, sha), 'Local tag points to another commit')
    require(remote_tag(repo, target) in (None, sha), 'Remote tag points to another commit')
    github_access(expected)
    # Revalidation always uses the pinned archive, never the current checkout.
    update(folder, 'validating')
    with exported(repo, sha) as root:
        validator(root, target, payload['config'])
    frozen_payload(folder)
    require(not status(folder)['cancelled'], 'Release cancelled')
    notes = (Path(folder) / 'notes.md').read_text()
    tag = 'v' + target
    release = github_release(expected, tag)
    if release:
        require(not release.get('draft') and not release.get('prerelease') and release.get('body', '').replace('\r\n', '\n').rstrip() == notes.rstrip(), 'Existing release differs from approved notes/state; manual review required')
        require(remote_tag(repo, target) == sha, 'Existing release tag does not match candidate')
    else:
        update(folder, 'publication_started', publishing_started=True)
        candidate_ref = 'refs/heads/release-candidates/' + tag
        existing = git(repo, 'ls-remote', 'origin', candidate_ref).split()
        require(not existing or existing[0] == sha, 'Remote candidate reference differs')
        run(['git', '-C', str(repo), 'push', 'origin', f'{sha}:{candidate_ref}'])
        update(folder, 'candidate_pushed')
        if not state['scheduled']:
            # Ordinary non-force push rejects divergence. Local working tree is untouched.
            git(repo, 'push', 'origin', f'{sha}:refs/heads/main')
            update(folder, 'main_pushed')
        if remote_tag(repo, target) is None:
            if not local_tag(repo, target):
                git(repo, 'tag', '-a', tag, sha, '-m', f'Armory Ledger {tag}')
            git(repo, 'push', 'origin', 'refs/tags/' + tag)
        update(folder, 'tag_pushed')
        run(['gh', 'release', 'create', tag, '--repo', expected, '--verify-tag', '--latest=false',
             '--title', f'Armory Ledger {tag}', '--notes-file', str(Path(folder) / 'notes.md')])
    update(folder, 'github_published', github_published=True, container_verified=False)
    verifier(payload, folder)


def execute(folder):
    folder = Path(folder).resolve()
    with locked(folder.parent):
        try:
            publish(folder)
        except (ReleaseError, ValueError, TypeError, KeyError, OSError) as exc:
            # Error text from our checked commands excludes raw stderr/credentials.
            message = str(exc) if isinstance(exc, ReleaseError) else 'Release state or verification response is invalid; review required'
            if isinstance(exc, PendingVerification):
                update(folder, status(folder)['stage'], waiting_for_container=True, error=message)
            else:
                update(folder, 'failed', error=message)
            raise ReleaseError(message) from exc


def manage(folder, action, when=None):
    folder = Path(folder).resolve()
    with locked(folder.parent):
        payload = frozen_payload(folder); state = status(folder)
        require(not state.get('github_published') and not state.get('publishing_started') and state['stage'] != 'complete', 'Publication has started; inspect remote state and recover explicitly rather than cancelling/rescheduling')
        if action == 'cancel':
            # Tombstone first; even a queued/restarted unit can no longer publish.
            update(folder, 'cancelled', cancelled=True)
        else:
            require(not state['cancelled'], 'Prepare a replacement for a cancelled release')
            require(when and datetime.fromisoformat(when) > datetime.now(timezone.utc), 'Reschedule must be in the future')
            confirm(f'Reschedule {payload["sha"]} with unchanged notes to {when}?', 'RESCHEDULE')
            update(folder, 'rescheduled', when=when, scheduled=True)
        name = state.get('timer')
        if name:
            run(['systemctl', '--user', 'disable', '--now', name + '.timer'])
            run(['systemctl', '--user', 'stop', name + '.service'])
        if action != 'cancel':
            install_timer(folder)


def validate_only(repo, config, target, paths, expected_tree=None):
    """Validate a selected tree without entering the release state machine."""
    tree = selected_tree(repo, paths)
    check_expected_tree(tree, expected_tree)
    results = {}
    outcome = 'FAILED / INTERRUPTED'
    print(f'Validation source tree: {tree}')
    print(git(repo, 'diff', '--stat', 'HEAD', tree) or 'Committed HEAD; no selected differences.')
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    previous_signal = signal.signal(signal.SIGTERM, interrupted)
    try:
        with exported(repo, tree) as root:
            # Reject export-ignore/substitution: the archive must match the tree identity.
            for entry in git(repo, 'ls-tree', '-rz', tree).split('\0'):
                if not entry: continue
                metadata, path = entry.split('\t', 1)
                mode, kind, digest = metadata.split()
                source = root / path
                require(kind == 'blob' and source.is_file(), 'Archive does not contain the complete selected tree')
                require(git(repo, 'hash-object', '--no-filters', str(source)) == digest, 'Archive content differs from selected tree')
            # Scan the candidate at its source paths so exact allowlist entries apply.
            results['static'] = 'failed'
            static_validate(root, target)
            results['static'] = 'passed'
            diff = git(repo, 'diff', '--no-ext-diff', '--no-textconv', 'HEAD', tree)
            print(diff)
            confirm('Review this exact tree, then validate using disposable Docker resources.', 'VALIDATE')
            validate(root, target, config, results=results)
            outcome = 'PASSED'
    finally:
        signal.signal(signal.SIGTERM, previous_signal)
        print(f'Validation summary: {outcome} — source tree {tree}')
        for check, result in results.items():
            print(f'  {check}: {result}')
        print('No candidate commit, release state, tag, branch, timer or publication created.')
    return tree


def interactive(args):
    repo = Path(args.repo).resolve()
    config_path = repo / '.release-config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    config.setdefault('repository', DEFAULT_REPOSITORY)
    config.setdefault('state_dir', str(Path.home() / '.local/state/armory-ledger/releases'))
    config.setdefault('runner_python', sys.executable)
    require(set(config) <= {'repository','state_dir','runner_python','test_python','node','node_path','docker'}, 'Unknown release configuration key; credentials must stay in Git/GitHub/Docker credential stores')
    require(config.get('docker', ['docker']) in (['docker'], ['sudo','-n','docker']), 'docker must be [docker] or [sudo,-n,docker]')
    repository(repo, config['repository'])
    target = version(args.version or input('Release version: ').strip())
    print(git(repo, 'status', '--short', env=dict(os.environ, GIT_OPTIONAL_LOCKS='0')))
    if args.dry_run:
        # Read-only demonstration: no candidate commit/index, network, Docker or jobs.
        print(choose_notes(repo, target, history(repo, 'HEAD'), 'auto'))
        print('DRY RUN ONLY: working-tree notes; no immutable candidate or publication approval created.')
        print('Required later: explicit file selection, scans, isolated validation, pinned SHA and final approval.')
        return
    if getattr(args, 'include_all_changes', False):
        require(args.command in ('manual', 'schedule'), 'Bulk selection requires release preparation')
        paths = bulk_selection(repo)
    else:
        paths = []
        print('Enter each exact file path to include; blank line finishes. Empty selection uses committed HEAD.\nExisting staged/untracked changes are NOT implicitly selected.')
        while True:
            value = input('File: ').strip()
            if not value: break
            paths.append(value)
    if args.validate_only:
        validate_only(repo, config, target, paths, expected_tree=getattr(args, 'expected_tree', None))
        return
    mode = input('Notes: manual / auto / edit [auto]: ').strip() or 'auto'
    require(mode in ('manual', 'auto', 'edit'), 'Unknown note mode')
    notes_file = input('Existing Markdown file: ').strip() if mode == 'manual' else None
    when = None
    if args.command == 'schedule':
        zone = input(f'IANA timezone [{default_zone()}]: ').strip() or default_zone()
        local = input('Local release date/time (YYYY-MM-DD HH:mm): ').strip()
        occurrence = input('If ambiguous, earlier/later (otherwise blank): ').strip() or None
        when = resolve_time(local, zone, occurrence)
        print(f'Local: {local} {zone}\nUTC: {when}')
        linger = run(['loginctl', 'show-user', str(os.getuid()), '-p', 'Linger', '--value'])
        require(linger == 'yes', 'User lingering is disabled. Follow docs/RELEASE-WORKFLOW.md setup; no settings changed.')
    with locked(Path(config['state_dir']).expanduser()):
        folder = prepare(repo, config, target, paths, mode, notes_file, when, expected_tree=getattr(args, 'expected_tree', None))
        if when:
            install_timer(folder)
            print(f'Scheduled state: {folder}')
    if not when:
        execute(folder)


def main():
    os.umask(0o077)
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    os.environ['GH_PROMPT_DISABLED'] = '1'
    os.environ['GIT_SSH_COMMAND'] = 'ssh -oBatchMode=yes'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['manual','schedule','execute','list','inspect','cancel','reschedule','units'])
    parser.add_argument('--repo', default=str(Path.cwd()))
    parser.add_argument('--version')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true')
    modes.add_argument('--validate-only', action='store_true', help='Validate selected source in disposable resources; create no release')
    parser.add_argument('--include-all-changes', action='store_true', help='Review all Git changes for validation or release preparation')
    parser.add_argument('--expected-tree', type=expected_tree_sha, help='Require this exact selected Git tree before validation/candidate creation')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--state-dir', type=Path, default=Path.home()/'.local/state/armory-ledger/releases')
    parser.add_argument('--status', action='store_true', help='Show scheduled release timing and local timer health; read-only')
    parser.add_argument('--local'); parser.add_argument('--timezone', default=default_zone())
    parser.add_argument('--occurrence', choices=['earlier','later'])
    args = parser.parse_args()
    if args.status and (args.command != 'schedule' or args.dry_run or args.validate_only
                        or args.version or args.include_all_changes or args.expected_tree
                        or args.state or args.local or args.occurrence):
        parser.error('--status is a read-only schedule query; do not combine it with preparation or recovery options')
    if (args.include_all_changes or args.expected_tree) and (args.command not in ('manual', 'schedule') or args.dry_run):
        parser.error('--include-all-changes / --expected-tree require validation or release preparation, not dry-run or recovery')
    if args.validate_only and args.command != 'manual':
        parser.error('--validate-only is supported only by the manual command / release.sh')
    try:
        if args.status:
            print_scheduled_release_status(args.state_dir)
        elif args.command in ('manual','schedule'):
            interactive(args)
        elif args.command == 'list':
            for path in sorted(args.state_dir.glob('*/approval.json')):
                payload = frozen_payload(path.parent)
                print(json.dumps({'id':payload['id'],'version':payload['version'],'sha':payload['sha'],**status(path.parent)}))
        else:
            require(args.state is not None, '--state is required')
            if args.command == 'execute': execute(args.state)
            elif args.command == 'inspect':
                print(json.dumps(frozen_payload(args.state), indent=2)); print(json.dumps(status(args.state), indent=2))
                print((args.state/'notes.md').read_text())
            elif args.command == 'units':
                state = status(args.state)
                print('\n'.join(timer_units(args.state, state['when'])))
            else:
                require(args.command != 'reschedule' or args.local is not None, '--local is required for rescheduling')
                when = resolve_time(args.local, args.timezone, args.occurrence) if args.command == 'reschedule' else None
                manage(args.state, args.command, when)
    except KeyboardInterrupt:
        print('Validation/release interrupted.', file=sys.stderr)
        return 130
    except (ReleaseError, ValueError, TypeError, KeyError, OSError) as exc:
        print('ERROR: ' + (str(exc) if isinstance(exc, ReleaseError) else 'Invalid state/configuration; review required'), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
