"""Standard-library release primitives. Never import application Settings."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def run(args, cwd=None, env=None, input=None, ok=(0,)):
    """Capture output; errors never echo arguments, environment or secret-bearing output."""
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, input=input,
                                text=True, capture_output=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError(f"{Path(args[0]).name}: command unavailable or timed out") from exc
    require(result.returncode in ok, f"{Path(args[0]).name}: command failed (exit {result.returncode}); output withheld")
    return result.stdout.strip()


def git(repo, *args, **kwargs):
    return run(['git', '-C', str(repo), *args], **kwargs)


def version(value):
    value = value.removeprefix('v')
    require(bool(re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value)), 'Version must be major.minor.patch without leading zeroes')
    return value


def version_key(value):
    return tuple(map(int, version(value).split('.')))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


@contextmanager
def locked(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'release.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReleaseError('Another release or management operation holds the lock') from exc
        yield


def event(folder, name, **fields):
    """Callers pass only identifiers/status, never subprocess output or credentials."""
    record = {'at': datetime.now(timezone.utc).isoformat(), 'event': name, **fields}
    with (Path(folder) / 'events.jsonl').open('a') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')


def resolve_time(local, zone, occurrence=None, now=None):
    require(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}', local)), 'Use YYYY-MM-DD HH:mm (24-hour)')
    try:
        wall = datetime.fromisoformat(local)
        tz = ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ReleaseError('Invalid date/time or IANA timezone') from exc
    choices = sorted({wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
                      if wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == wall})
    require(bool(choices), 'Nonexistent local time: clocks move forward; choose another time')
    require(len(choices) == 1 or occurrence in ('earlier', 'later'), 'Ambiguous local time: explicitly choose earlier or later')
    instant = choices[-1] if occurrence == 'later' else choices[0]
    require(instant > (now or datetime.now(timezone.utc)), 'Release time must be in the future')
    return instant.isoformat()


def default_zone():
    candidate = os.environ.get('TZ', '')
    if not candidate:
        try:
            candidate = str(Path('/etc/localtime').resolve()).split('/zoneinfo/', 1)[1]
        except (OSError, IndexError):
            candidate = 'UTC'
    try:
        ZoneInfo(candidate)
    except (ValueError, ZoneInfoNotFoundError):
        candidate = 'UTC'
    return candidate


def scan_files(root):
    """Defense in depth. Return locations/rule names only, not matching content."""
    findings = []
    rules = {
        'private-key': r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----',
        'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
        'aws-key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
        'credential-url': r'(?i)\b(?:postgres(?:ql)?|https?)://[^\s/:]+:[^\s/@]+@',
        'private-reference': r'(?i)(?:heytechguy|@(?:gmail|outlook|yahoo)\.com|\b192\.168\.\d+\.\d+\b|\b10\.\d+\.\d+\.\d+\b|\b172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+\b)',
        'literal-secret': r'''(?im)^\s*["']?(?:password|postgres_password|client_secret|oidc_client_secret|session_secret|api_key|access_token)["']?\s*[:=]\s*["']([^"'\n]{12,})["']''',
    }
    # Exact path/line-content hashes may acknowledge reviewed public examples.
    allow = {}
    allow_path = Path(root) / 'release-scan-allowlist.json'
    if allow_path.exists():
        allow = json.loads(allow_path.read_text())
    for path in sorted(Path(root).rglob('*')):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            findings.append((relative, 0, 'symlink')); continue
        if not path.is_file():
            continue
        if path.name in ('.env', 'compose.yaml', '.release-config.json') or path.suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.pem', '.key'):
            findings.append((relative, 0, 'runtime-or-key-file')); continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
            for name, pattern in rules.items():
                if re.search(pattern, line):
                    fingerprint = sha256(line.encode())
                    entry = allow.get(f'{relative}:{name}:{fingerprint}', {})
                    if not isinstance(entry, dict) or not entry.get('reason'):
                        findings.append((relative, number, name))
    return findings


def assert_scan(root):
    findings = scan_files(root)
    require(not findings, 'Candidate scan requires review: ' + '; '.join(f'{p}:{n} [{rule}]' for p, n, rule in findings))


def release_notes(root, target, commits=(), changes=()):
    path = Path(root) / 'app/content/changelog.json'
    if path.exists():
        source = json.loads(path.read_text())
        entries = [entry for entry in source if entry.get('version') == target]
        require(len(entries) <= 1, 'Duplicate Changelog version')
        if entries:
            entry = entries[0]
            sections = [('added','New Features'),('improved','Improvements'),('fixed','Bug Fixes'),
                        ('breaking','Breaking Changes'),('upgrade_notes','Upgrade Notes')]
            lines = [f'# Armory Ledger v{target}', '']
            for key, title in sections:
                items = entry.get(key, [])
                require(isinstance(items, list) and all(isinstance(item, str) for item in items), 'Invalid Changelog section')
                if items:
                    lines.extend([f'## {title}', '', *['- ' + item for item in items], ''])
            return '\n'.join(lines).rstrip() + '\n'
    lines = [f'# Armory Ledger v{target}', '', '## Changes requiring editorial review', '']
    lines += ['- Changed path: ' + line for line in changes]
    lines += ['- Commit summary: ' + line for line in commits]
    if not changes and not commits:
        lines += ['No release summary is available. Add reviewed notes before approval.']
    return '\n'.join(lines) + '\n'
