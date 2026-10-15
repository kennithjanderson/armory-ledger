#!/usr/bin/env python3
"""GitHub Actions image policy: immutable version identity and monotonic aliases."""
import argparse
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from common import ReleaseError, require, run, version, version_key


def request_json(url, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return json.load(response), response.headers
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, exc.headers
        raise ReleaseError(f'Remote API failed with HTTP {exc.code}; no alias promotion') from exc
    except OSError as exc:
        raise ReleaseError('Remote API unavailable; no alias promotion') from exc


class Registry:
    def __init__(self, repository):
        self.repository = repository.lower()
        auth = base64.b64encode(f'{os.environ["GITHUB_ACTOR"]}:{os.environ["GITHUB_TOKEN"]}'.encode()).decode()
        query = urllib.parse.urlencode({'service':'ghcr.io','scope':f'repository:{self.repository}:pull'})
        token, _ = request_json('https://ghcr.io/token?' + query, {'Authorization':'Basic ' + auth})
        require(token and token.get('token'), 'Registry token unavailable')
        self.headers = {'Authorization':'Bearer ' + token['token'], 'Accept':
                        'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'}

    def image(self, reference):
        base = f'https://ghcr.io/v2/{self.repository}'
        manifest, headers = request_json(f'{base}/manifests/{reference}', self.headers)
        if manifest is None:
            return None
        digest = headers.get('Docker-Content-Digest')
        require(digest, 'Registry omitted image digest')
        if 'manifests' in manifest:
            platform = next((m for m in manifest['manifests'] if m.get('platform', {}).get('os') == 'linux' and m.get('platform', {}).get('architecture') == 'amd64'), None)
            require(platform is not None, 'Image lacks expected linux/amd64 platform')
            manifest, _ = request_json(f'{base}/manifests/{platform["digest"]}', self.headers)
        require(manifest and manifest.get('config', {}).get('digest'), 'Image config missing')
        config, _ = request_json(f'{base}/blobs/{manifest["config"]["digest"]}', self.headers)
        require(config is not None, 'Registry image config unavailable')
        labels = config.get('config', {}).get('Labels') or {}
        return {'digest': digest, 'version': labels.get('org.opencontainers.image.version'),
                'commit': labels.get('org.opencontainers.image.revision')}


def published_versions(repository):
    values = []
    for page in range(1, 1001):
        releases, _ = request_json(f'https://api.github.com/repos/{repository}/releases?per_page=100&page={page}',
                                  {'Authorization':'Bearer ' + os.environ['GITHUB_TOKEN'], 'Accept':'application/vnd.github+json'})
        require(isinstance(releases, list), 'Cannot enumerate published releases')
        for release in releases:
            if not release.get('draft') and not release.get('prerelease'):
                try: values.append(version(release['tag_name']))
                except (ReleaseError, KeyError): continue
        if len(releases) < 100:
            return values
    raise ReleaseError('Release enumeration exceeded limit; no alias promotion')


def may_promote(target, published, current=None, minor=False):
    key = version_key(target)
    competitors = [version_key(item) for item in published]
    if current:
        # An unlabeled/unknown existing alias cannot safely be overwritten.
        require(current.get('version'), 'Existing alias has no version label; operator review required')
        competitors.append(version_key(current['version']))
    if minor:
        competitors = [item for item in competitors if item[:2] == key[:2]]
    return all(item <= key for item in competitors)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['plan','promote'])
    parser.add_argument('--digest'); args = parser.parse_args()
    repository = os.environ['GITHUB_REPOSITORY']
    target = version(os.environ['RELEASE_TAG'])
    sha = os.environ['RELEASE_SHA']
    require(__import__('re').fullmatch('[a-f0-9]{40}', sha), 'Invalid release commit')
    registry = Registry(repository); existing = registry.image(target)
    if existing:
        require(existing['commit'] == sha and existing['version'] == target, 'Version image already belongs to another commit; refusing overwrite')
    if args.mode == 'plan':
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'version={target}\nskip={str(existing is not None).lower()}\ndigest={existing["digest"] if existing else ""}\n')
        return
    require(existing and existing['digest'] == args.digest, 'Published version digest does not match this workflow')
    published = published_versions(repository)
    image = 'ghcr.io/' + repository.lower()
    for alias, minor in [('latest', False), ('.'.join(target.split('.')[:2]), True)]:
        current = registry.image(alias)
        if may_promote(target, published, current, minor):
            run(['docker','buildx','imagetools','create','--tag',image+':'+alias,image+'@'+args.digest])
    Path('release-receipt.json').write_text(json.dumps({'version':target,'commit':sha,'digest':args.digest}) + '\n')


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, KeyError, ValueError, OSError):
        raise SystemExit('Image verification/promotion failed; inspect policy and registry state. No secret output is logged.')
