"""Daily, read-only check of the upstream GHCR latest image tag."""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.notification import SystemSetting

REGISTRY = 'https://ghcr.io'
IMAGE = 'kennithjanderson/armory-ledger'
CHECK_KEY = 'upstream_image_update_check'
CHECK_INTERVAL = timedelta(days=1)
REQUEST_TIMEOUT = 5
VERSION_RE = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
MANIFEST_ACCEPT = ', '.join((
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
))


def version_tuple(value):
    match = VERSION_RE.fullmatch(value.removeprefix('v') if isinstance(value, str) else '')
    if not match:
        raise ValueError('Image version label is not a stable semantic version')
    return tuple(int(part) for part in match.groups())


def request_json(url, headers=None):
    request = Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'Armory-Ledger update-check',
        **(headers or {}),
    })
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        if response.status != 200:
            raise ValueError('Registry returned an unexpected status')
        return json.load(response)


def image_version():
    """Read the version label from the manifest currently addressed by GHCR latest."""
    scope = urlencode({'scope': f'repository:{IMAGE}:pull', 'service': 'ghcr.io'})
    token_data = request_json(f'{REGISTRY}/token?{scope}')
    token = token_data.get('token') or token_data.get('access_token')
    if not isinstance(token, str) or not token:
        raise ValueError('Registry did not provide a pull token')
    headers = {'Authorization': f'Bearer {token}', 'Accept': MANIFEST_ACCEPT}
    base = f'{REGISTRY}/v2/{IMAGE}'
    manifest = request_json(f'{base}/manifests/latest', headers)
    descriptors = manifest.get('manifests')
    if descriptors is not None:
        descriptor = next((item for item in descriptors
                           if item.get('platform', {}).get('os') == 'linux'
                           and item.get('platform', {}).get('architecture') == 'amd64'), None)
        if not descriptor or not isinstance(descriptor.get('digest'), str):
            raise ValueError('Latest image has no linux/amd64 manifest')
        manifest = request_json(f"{base}/manifests/{descriptor['digest']}", headers)
    config_digest = manifest.get('config', {}).get('digest')
    if not isinstance(config_digest, str) or not config_digest.startswith('sha256:'):
        raise ValueError('Latest image manifest has no valid config digest')
    config = request_json(f'{base}/blobs/{config_digest}', headers)
    labels = config.get('config', {}).get('Labels') or {}
    version = labels.get('org.opencontainers.image.version')
    version_tuple(version)
    return version.removeprefix('v')


def _save_state(db, value):
    row = db.get(SystemSetting, CHECK_KEY)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=CHECK_KEY, value=value))


def check_if_due(current_time=None, fetch_version=None):
    """Poll no more than once per day; failures are remembered without alerting users."""
    current_time = current_time or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError('Update-check time must be timezone-aware')
    current_time = current_time.astimezone(timezone.utc)
    with SessionLocal() as db:
        row = db.get(SystemSetting, CHECK_KEY)
        previous = row.value if row else {}
        checked_at = previous.get('checked_at')
        if checked_at:
            last_check = datetime.fromisoformat(checked_at)
            if last_check.tzinfo is None:
                last_check = last_check.replace(tzinfo=timezone.utc)
            if current_time - last_check.astimezone(timezone.utc) < CHECK_INTERVAL:
                return False
        _save_state(db, {'checked_at': current_time.isoformat(), 'latest_version': previous.get('latest_version')})
        db.commit()

    try:
        latest = (fetch_version or image_version)()
        latest_tuple = version_tuple(latest)
        current_tuple = version_tuple(settings.app_version)
    except Exception as exc:
        with SessionLocal() as db:
            row = db.get(SystemSetting, CHECK_KEY)
            state = dict(row.value) if row else {'checked_at': current_time.isoformat()}
            state['error'] = type(exc).__name__
            _save_state(db, state)
            db.commit()
        return True

    with SessionLocal() as db:
        row = db.get(SystemSetting, CHECK_KEY)
        state = dict(row.value) if row else {}
        state.update(checked_at=current_time.isoformat(), latest_version=latest)
        state.pop('error', None)
        _save_state(db, state)
        db.commit()
    from app.services.notification_service import update_available
    update_available(latest if latest_tuple > current_tuple else None, current_time)
    return True
