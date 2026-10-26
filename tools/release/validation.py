"""Validate an archived candidate using disposable containers; no Compose/app DB."""
import ast
import json
import os
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.request
import uuid

from common import ReleaseError, assert_scan, require, run


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check_http(base, target):
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(base + '/health', timeout=5) as response:
        health = json.load(response)
    require(health.get('status') == 'healthy' and health.get('database') == 'connected', 'Candidate application/database unhealthy')
    require(health.get('version') == target, 'Candidate runtime version mismatch')
    for path, expected in [('/', 200), ('/dashboard', 303), ('/admin', 303), ('/changelog', 200), ('/about', 200)]:
        try:
            response = opener.open(base + path, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            require(response.code == expected, f'Candidate HTTP check failed: {path}')


def static_validate(root, target):
    assert_scan(root)
    tree = ast.parse((Path(root) / 'app/core/config.py').read_text())
    values = [n.value.value for n in ast.walk(tree) if isinstance(n, ast.AnnAssign)
              and isinstance(n.target, ast.Name) and n.target.id == 'app_version'
              and isinstance(n.value, ast.Constant)]
    require(values == [target], 'Candidate source version mismatch')
    workflow = Path(root) / '.github/workflows/docker-publish.yml'
    require(workflow.exists() and (Path(root) / 'tools/release/image_policy.py').exists(), 'Candidate lacks guarded container publication workflow')
    policy = workflow.read_text()
    require(all(marker in policy for marker in ('queue: max', 'cancel-in-progress: false', 'image_policy.py plan', 'image_policy.py promote', 'release-receipt', 'github.event.release.tag_name')), 'Candidate uses an obsolete/unguarded publication workflow')
    for path in Path(root).rglob('*.py'):
        ast.parse(path.read_text(), filename=str(path.relative_to(root)))


def validate(root, target, config, *, results=None):
    """Explicitly invoked by release preparation/execution, never by dry-run."""
    results = results if results is not None else {}
    results.update(dict.fromkeys(('static', 'build', 'postgresql', 'python', 'javascript',
                                  'health_version_auth', 'migrations', 'cleanup'), 'not run'))
    def stage(name):
        results[name] = 'running'
    stage('static')
    try:
        static_validate(root, target)
    except BaseException:
        results['static'] = 'failed'
        raise
    results['static'] = 'passed'
    docker = config.get('docker', ['docker'])
    require(isinstance(docker, list) and all(isinstance(x, str) for x in docker), 'docker must be an argv list')
    python = config.get('test_python', 'python3')
    node = config.get('node', 'node')
    name = 'armory-release-test-' + uuid.uuid4().hex
    db_name, app_name, image = name + '-db', name + '-app', name + ':candidate'
    password = secrets.token_hex(24)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHON=python)
    # Never inherit a previously configured application/test database URL.
    env.pop('ARMORY_TEST_POSTGRES_URL', None); env.pop('ARMORY_DISPOSABLE_POSTGRES', None)
    if config.get('node_path'):
        env['NODE_PATH'] = config['node_path']
    db_env = Path(root) / '.release-db.env'
    app_env = Path(root) / '.release-app.env'
    created_network = False
    created = set()
    try:
        # Build before synthetic env files are created, so they cannot enter context.
        stage('build')
        run([*docker, 'build', '--no-cache', '-t', image, '.'], cwd=root)
        created.add(image); results['build'] = 'passed'
        stage('postgresql')
        # A non-internal bridge permits Docker to publish the localhost test ports.
        run([*docker, 'network', 'create', '--driver', 'bridge', name]); created_network = True
        db_env.write_text(f'POSTGRES_USER=release_test\nPOSTGRES_DB=release_test\nPOSTGRES_PASSWORD={password}\n'); db_env.chmod(0o600)
        run([*docker, 'run', '-d', '--name', db_name, '--network', name,
             '--env-file', str(db_env), '--tmpfs', '/var/lib/postgresql/data',
             '-p', '127.0.0.1::5432', 'postgres:17'])
        created.add(db_name)
        for _ in range(60):
            try:
                run([*docker, 'exec', db_name, 'pg_isready', '-U', 'release_test']); break
            except ReleaseError:
                time.sleep(1)
        else:
            raise ReleaseError('Disposable PostgreSQL did not become ready')
        db_port = run([*docker, 'port', db_name, '5432/tcp']).rsplit(':', 1)[1]
        env['ARMORY_DISPOSABLE_POSTGRES'] = '1'
        env['ARMORY_TEST_POSTGRES_URL'] = f'postgresql+psycopg://release_test:{password}@127.0.0.1:{db_port}/release_test'
        # Tests may import application services whose Settings object validates
        # the normal runtime configuration at import time. Supply synthetic
        # values pointed only at this disposable database; never inherit an
        # operator's app database or identity-provider credentials.
        env.update({
            'POSTGRES_DB': 'release_test',
            'POSTGRES_USER': 'release_test',
            'POSTGRES_PASSWORD': password,
            'POSTGRES_HOST': '127.0.0.1',
            'POSTGRES_PORT': db_port,
            'OIDC_CLIENT_ID': 'release-test',
            'OIDC_CLIENT_SECRET': secrets.token_hex(24),
            'OIDC_ISSUER': 'https://example.invalid',
            'OIDC_REDIRECT_URI': 'https://example.invalid/auth/callback',
            'SESSION_SECRET': secrets.token_hex(32),
        })
        results['postgresql'] = 'passed'
        stage('python')
        run([python, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v'], cwd=root, env=env)
        results['python'] = 'passed-with-disposable-postgres'
        stage('javascript')
        js_tests = sorted(str(p.relative_to(root)) for p in Path(root).glob('tests/*.test.cjs'))
        require(bool(js_tests), 'Candidate has no JavaScript tests')
        run([node, '--test', *js_tests], cwd=root, env=env)
        results['javascript'] = 'passed'
        stage('health_version_auth')
        app_env.write_text('\n'.join([
            'POSTGRES_USER=release_test', 'POSTGRES_DB=release_test', f'POSTGRES_PASSWORD={password}',
            f'POSTGRES_HOST={db_name}', 'POSTGRES_PORT=5432', 'OIDC_CLIENT_ID=release-test',
            'OIDC_CLIENT_SECRET=' + secrets.token_hex(24), 'OIDC_ISSUER=https://example.invalid',
            'OIDC_REDIRECT_URI=https://example.invalid/auth/callback', 'SESSION_SECRET=' + secrets.token_hex(32), '',
        ])); app_env.chmod(0o600)
        run([*docker, 'run', '-d', '--name', app_name, '--network', name,
             '--env-file', str(app_env), '-p', '127.0.0.1::8000', image])
        created.add(app_name)
        port = run([*docker, 'port', app_name, '8000/tcp']).rsplit(':', 1)[1]
        for _ in range(90):
            try:
                check_http(f'http://127.0.0.1:{port}', target); break
            except (ReleaseError, OSError, ValueError):
                time.sleep(1)
        else:
            raise ReleaseError('Candidate health/version/HTTP checks failed; container output withheld')
        results['health_version_auth'] = 'passed'
        stage('migrations')
        # Exec bypasses the image entrypoint; inspect only this disposable database.
        run([*docker, 'exec', app_name, 'python', '-c',
             'from alembic.config import Config; from alembic.script import ScriptDirectory; '
             'from alembic.runtime.migration import MigrationContext; '
             'from app.db.session import engine; '
             'connection = engine.connect(); '
             'assert set(MigrationContext.configure(connection).get_current_heads()) == '
             'set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()); '
             'connection.close()'])
        results['migrations'] = 'passed'
        return results
    except BaseException:
        for check, result in results.items():
            if result == 'running': results[check] = 'failed'
        raise
    finally:
        # Attempt every cleanup even when an earlier removal fails. Only our unique names.
        failures = []
        commands = [([*docker, 'rm', '-fv', resource], resource in created)
                    for resource in (app_name, db_name)]
        if created_network:
            commands.append(([*docker, 'network', 'rm', name], True))
        commands.append(([*docker, 'image', 'rm', image], image in created))
        for command, required in commands:
            try: run(command)
            except (ReleaseError, OSError):
                if required: failures.append(command[-1])
        for path in (db_env, app_env):
            try: path.unlink(missing_ok=True)
            except OSError: failures.append(path.name)
        results['cleanup'] = 'failed' if failures else 'passed'
        if failures:
            raise ReleaseError('Disposable cleanup failed; remove these validation resources: ' + ', '.join(failures))
