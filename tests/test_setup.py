"""Installer integration tests with mocked Docker and disposable directories."""

import base64
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKER_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$1" in
  --version) printf 'Docker version 29.0.0\\n'; exit 0 ;;
  info) [ "${MOCK_DAEMON:-ok}" = ok ] || exit 1; printf '29.0.0\\n'; exit 0 ;;
  volume)
    [ "$2" = ls ] || exit 2
    [ "${MOCK_VOLUME:-false}" = true ] && printf '%s\\n' 'armory-ledger-test_postgres_data'
    exit 0
    ;;
  compose)
    if [ "$2" = version ]; then
      [ "${MOCK_COMPOSE:-ok}" = ok ] || exit 1
      printf 'Docker Compose version v2.30.0\\n'
      exit 0
    fi
    if [ "${MOCK_FAIL_CONFIG_ONCE:-false}" = true ] && [ ! -e "$MOCK_FAIL_MARKER" ]; then
      : > "$MOCK_FAIL_MARKER"
      exit 1
    fi
    exit 0
    ;;
esac
exit 2
"""


def parse_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


class GetStartedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="armory-setup-test-")
        self.root = Path(self.temp.name) / "armory-ledger-test"
        self.root.mkdir()
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        (self.bin / "docker").write_text(DOCKER_STUB)
        (self.bin / "docker").chmod(0o755)
        python = shutil.which("python3")
        if not python:
            self.fail("test requires Python 3")
        (self.bin / "python3").symlink_to(python)
        for relative in (
            "get-started.sh",
            ".env.example",
            "compose.example.yaml",
            "compose.build.yaml",
            "Dockerfile",
            "tools/setup/prepare_install.py",
        ):
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if relative.endswith(".sh"):
                target.chmod(0o755)
        self.docker_log = Path(self.temp.name) / "docker.log"
        self.fail_marker = Path(self.temp.name) / "compose-failed-once"

    def tearDown(self):
        self.temp.cleanup()

    def run_setup(self, *args, **flags):
        env = {
            "PATH": str(self.bin),
            "DOCKER_LOG": str(self.docker_log),
            "MOCK_FAIL_MARKER": str(self.fail_marker),
        }
        env.update({key: str(value).lower() if isinstance(value, bool) else str(value)
                    for key, value in flags.items()})
        return subprocess.run(
            ["/bin/bash", str(self.root / "get-started.sh"), *args],
            cwd=self.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

    def test_fresh_published_setup_generates_valid_private_secrets_without_printing_them(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = parse_env(self.root / ".env")
        self.assertTrue(values["POSTGRES_PASSWORD"])
        self.assertGreaterEqual(len(values["SESSION_SECRET"]), 64)
        backup = values["ARMORY_BACKUP_ENCRYPTION_KEY"]
        self.assertEqual(len(base64.b64decode(backup, altchars=b"-_", validate=True)), 32)
        smtp_key = values["ARMORY_SECRET_KEY"]
        self.assertEqual(len(base64.urlsafe_b64decode(smtp_key)), 32)
        self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "compose.yaml").read_text(), (self.root / "compose.example.yaml").read_text())
        for secret in (values["POSTGRES_PASSWORD"], values["SESSION_SECRET"], backup, smtp_key):
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertIn("OIDC_CLIENT_ID", result.stdout)
        self.assertIn("docker compose pull", result.stdout)
        calls = self.docker_log.read_text()
        self.assertIn("compose -f compose.yaml config -q", calls)
        self.assertNotIn("compose.build.yaml", calls)

    def test_rerun_preserves_existing_secrets_oidc_and_compose(self):
        self.assertEqual(self.run_setup().returncode, 0)
        env_path = self.root / ".env"
        before = parse_env(env_path)
        before["OIDC_CLIENT_ID"] = "external-client-id"
        before["OIDC_CLIENT_SECRET"] = "operator-provided-secret"
        before["OIDC_ISSUER"] = "https://identity.example.invalid/issuer"
        before["OIDC_REDIRECT_URI"] = "https://ledger.example.invalid/auth/callback"
        before["ARMORY_SECRET_KEY"] = base64.urlsafe_b64encode(b"m" * 32).decode()
        lines = env_path.read_text().splitlines()
        replacements = {key: f"{key}={value}" for key, value in before.items()}
        env_path.write_text("\n".join(replacements.get(line.split("=", 1)[0], line) if "=" in line else line for line in lines) + "\n")
        compose_path = self.root / "compose.yaml"
        compose_path.write_text(compose_path.read_text() + "\n# operator configuration\n")
        compose_before = compose_path.read_text()
        env_before = parse_env(env_path)

        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = parse_env(env_path)
        for key in ("POSTGRES_PASSWORD", "SESSION_SECRET", "ARMORY_BACKUP_ENCRYPTION_KEY", "ARMORY_SECRET_KEY",
                    "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER", "OIDC_REDIRECT_URI"):
            self.assertEqual(after[key], env_before[key])
        self.assertEqual(compose_path.read_text(), compose_before)
        self.assertIn("Preserved existing .env values and compose.yaml", result.stdout)

    def test_source_build_uses_override_without_rewriting_published_compose(self):
        result = self.run_setup("--build")
        self.assertEqual(result.returncode, 0, result.stderr)
        compose = (self.root / "compose.yaml").read_text()
        override = (self.root / "compose.build.yaml").read_text()
        self.assertIn("ghcr.io/kennithjanderson/armory-ledger:latest", compose)
        self.assertNotIn("armory-ledger:local", compose)
        self.assertIn("armory-ledger:local", override)
        self.assertIn("compose.build.yaml config -q", self.docker_log.read_text())
        self.assertIn("compose.build.yaml up --build -d", result.stdout)

    def test_existing_volume_or_backup_data_without_config_stops_before_writes(self):
        result = self.run_setup(MOCK_VOLUME=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Existing PostgreSQL or backup data was detected", result.stderr)
        self.assertFalse((self.root / ".env").exists())
        self.assertFalse((self.root / "compose.yaml").exists())

        (self.root / "data/backups").mkdir(parents=True)
        (self.root / "data/backups/archive.armorybackup").write_bytes(b"encrypted-test-data")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / ".env").exists())
        self.assertFalse((self.root / "compose.yaml").exists())

    def test_existing_incomplete_environment_does_not_regenerate_credentials(self):
        text = (self.root / ".env.example").read_text().replace("POSTGRES_HOST=db", "POSTGRES_HOST=existing-db")
        (self.root / ".env").write_text(text)
        before = (self.root / ".env").read_bytes()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("They were not regenerated", result.stderr)
        self.assertEqual((self.root / ".env").read_bytes(), before)
        self.assertFalse((self.root / "compose.yaml").exists())

    def test_unchanged_example_env_is_recognized_as_a_fresh_install_template(self):
        shutil.copyfile(self.root / ".env.example", self.root / ".env")
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = parse_env(self.root / ".env")
        self.assertTrue(values["POSTGRES_PASSWORD"])
        self.assertTrue(values["SESSION_SECRET"])
        self.assertTrue(values["ARMORY_BACKUP_ENCRYPTION_KEY"])
        self.assertTrue(values["ARMORY_SECRET_KEY"])
        self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)

    def test_existing_compose_without_env_is_not_completed_with_guessed_secrets(self):
        shutil.copyfile(self.root / "compose.example.yaml", self.root / "compose.yaml")
        before = (self.root / "compose.yaml").read_bytes()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compose.yaml exists but .env is missing", result.stderr)
        self.assertEqual((self.root / "compose.yaml").read_bytes(), before)
        self.assertFalse((self.root / ".env").exists())

    def test_invalid_existing_backup_or_smtp_key_is_not_replaced(self):
        self.assertEqual(self.run_setup().returncode, 0)
        env_path = self.root / ".env"
        before = env_path.read_text()
        values = parse_env(env_path)
        env_path.write_text(before.replace(values["ARMORY_BACKUP_ENCRYPTION_KEY"], "bad-key"))
        invalid = env_path.read_text()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid URL-safe base64", result.stderr)
        self.assertEqual(env_path.read_text(), invalid)

        restored = invalid.replace("ARMORY_BACKUP_ENCRYPTION_KEY=bad-key",
                                   f"ARMORY_BACKUP_ENCRYPTION_KEY={values['ARMORY_BACKUP_ENCRYPTION_KEY']}")
        env_path.write_text(restored.replace(values["ARMORY_SECRET_KEY"], "bad-fernet-key"))
        invalid = env_path.read_text()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a valid Fernet key", result.stderr)
        self.assertEqual(env_path.read_text(), invalid)

    def test_compose_validation_failure_can_be_rerun_without_rotating_secrets_or_leaving_temps(self):
        failed = self.run_setup(MOCK_FAIL_CONFIG_ONCE=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Docker Compose rejected", failed.stderr)
        self.assertTrue((self.root / ".env").is_file())
        self.assertTrue((self.root / "compose.yaml").is_file())
        original = parse_env(self.root / ".env")
        self.assertEqual(list(self.root.glob(".*.tmp.*")), [])

        recovered = self.run_setup(MOCK_FAIL_CONFIG_ONCE=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(parse_env(self.root / ".env"), original)

    def test_atomic_write_failure_preserves_user_file_and_removes_secret_temp(self):
        spec = importlib.util.spec_from_file_location("armory_setup_helper", ROOT / "tools/setup/prepare_install.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        target = self.root / ".env"
        target.write_text("operator-setting=keep\n")
        with self.assertRaises(helper.SetupError):
            helper.atomic_create(target, "SESSION_SECRET=temporary-secret\n", 0o600,
                                 expected_existing=b"a different source file")
        self.assertEqual(target.read_text(), "operator-setting=keep\n")
        self.assertEqual(list(self.root.glob(".*.tmp.*")), [])

    def test_missing_docker_compose_or_daemon_has_actionable_error(self):
        empty_bin = Path(self.temp.name) / "no-python-bin"
        empty_bin.mkdir()
        result = subprocess.run(["/bin/bash", str(self.root / "get-started.sh")], cwd=self.root,
                                env={"PATH": str(empty_bin)}, text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3 is required", result.stderr)

        docker_missing_bin = Path(self.temp.name) / "no-docker-bin"
        docker_missing_bin.mkdir()
        (docker_missing_bin / "python3").symlink_to(shutil.which("python3"))
        result = subprocess.run(["/bin/bash", str(self.root / "get-started.sh")], cwd=self.root,
                                env={"PATH": str(docker_missing_bin)}, text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Docker CLI was not found", result.stderr)

        result = self.run_setup(MOCK_COMPOSE="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Docker Compose v2 is unavailable", result.stderr)

        result = self.run_setup(MOCK_DAEMON="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("daemon is unavailable or this account lacks access", result.stderr)

    def test_templates_readme_and_ignore_rules_match_supported_modes(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("./get-started.sh", readme)
        self.assertIn("./get-started.sh --build", readme)
        self.assertIn("docker compose -f compose.yaml -f compose.build.yaml up --build -d", readme)
        ignore = (ROOT / ".gitignore").read_text()
        dockerignore = (ROOT / ".dockerignore").read_text()
        for content in (ignore, dockerignore):
            self.assertIn(".env", content)
            self.assertIn("data/", content)
        self.assertIn("!.env.example", ignore)
        self.assertIn("!.env.example", dockerignore)
        template = (ROOT / ".env.example").read_text()
        for name in ("POSTGRES_PASSWORD", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER",
                     "OIDC_REDIRECT_URI", "SESSION_SECRET", "ARMORY_BACKUP_ENCRYPTION_KEY", "ARMORY_SECRET_KEY"):
            self.assertRegex(template, rf"(?m)^{name}=")
        values = parse_env(ROOT / ".env.example")
        for name in ("POSTGRES_PASSWORD", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER",
                     "OIDC_REDIRECT_URI", "SESSION_SECRET", "ARMORY_BACKUP_ENCRYPTION_KEY", "ARMORY_SECRET_KEY"):
            self.assertEqual(values[name], "", f"{name} must be a safe empty example value")
        compose = (ROOT / "compose.example.yaml").read_text()
        self.assertIn('"127.0.0.1:8000:8000"', compose)
        db_service = compose.split("\n  db:\n", 1)[1]
        self.assertNotRegex(db_service, r"(?m)^    ports:")
        self.assertIn("internal: true", compose)
        # Candidate validation runs from a Git archive, which intentionally has
        # no .git directory. Check actual Git ignore semantics when available;
        # the assertions above still verify the archived ignore rules.
        if (ROOT / ".git").exists():
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode, 0)
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", "data/backups/example"], cwd=ROOT).returncode, 0)


if __name__ == "__main__":
    unittest.main()
