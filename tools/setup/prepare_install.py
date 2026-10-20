#!/usr/bin/env python3
"""Prepare a first-run Armory Ledger configuration without touching services."""

import argparse
import base64
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import tempfile


SECRET_NAMES = (
    "POSTGRES_PASSWORD",
    "SESSION_SECRET",
    "ARMORY_BACKUP_ENCRYPTION_KEY",
    "ARMORY_SECRET_KEY",
)
REQUIRED_SECRET_NAMES = SECRET_NAMES[:3]
ENV_NAME = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


class SetupError(Exception):
    pass


def remove_temporary_file(path: Path) -> None:
    """Best-effort overwrite and remove a private atomic-write temporary file."""
    try:
        with path.open("r+b") as stream:
            remaining = os.fstat(stream.fileno()).st_size
            zeroes = b"\0" * 65536
            while remaining:
                chunk = min(remaining, len(zeroes))
                stream.write(zeroes[:chunk])
                remaining -= chunk
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def project_name(root: Path, env_path: Path | None = None) -> str:
    """Match Compose's default project name unless COMPOSE_PROJECT_NAME overrides it."""
    candidate_name = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if not candidate_name and env_path and env_path.is_file() and not env_path.is_symlink():
        candidate_name = read_env(env_path).get("COMPOSE_PROJECT_NAME", "")
    if candidate_name:
        candidate = re.sub(r"[^a-z0-9_-]+", "-", candidate_name.lower()).strip("-_")
        if candidate and candidate[0].isalnum():
            return candidate
    candidate = re.sub(r"[^a-z0-9_-]+", "-", root.name.lower()).strip("-_")
    if not candidate:
        candidate = "armory-ledger"
    if not candidate[0].isalnum():
        candidate = f"armory-{candidate}"
    return candidate


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    duplicates: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SetupError(f"Could not read {path.name}: {exc}") from exc
    for line in lines:
        match = ENV_NAME.match(line)
        if not match:
            continue
        name, value = match.groups()
        if name in values:
            duplicates.add(name)
        values[name] = unquote(value)
    required_duplicates = duplicates.intersection((*SECRET_NAMES, "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_HOST", "POSTGRES_PORT"))
    if required_duplicates:
        raise SetupError(f".env contains duplicate settings ({', '.join(sorted(required_duplicates))}); resolve them manually.")
    return values


def validate_backup_key(name: str, value: str) -> None:
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise SetupError(f"{name} is not valid URL-safe base64; restore its original key or configure a reviewed value.") from exc
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii") != value:
        raise SetupError(f"{name} must be canonical URL-safe base64 encoding exactly 32 bytes; do not replace a key used by existing backups.")


def validate_fernet_key(value: str) -> None:
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise SetupError("ARMORY_SECRET_KEY is not a valid Fernet key; restore the original key before using stored SMTP credentials.") from exc
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii") != value:
        raise SetupError("ARMORY_SECRET_KEY is not a valid Fernet key; restore the original key before using stored SMTP credentials.")


def new_secrets() -> dict[str, str]:
    return {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(48),
        "SESSION_SECRET": secrets.token_urlsafe(64),
        "ARMORY_BACKUP_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "ARMORY_SECRET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
    }


def atomic_create(path: Path, content: str, mode: int, expected_existing: bytes | None = None) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise SetupError(f"{path.name} became a symlink while setup was running; it was not followed or overwritten.")
        if path.exists():
            if expected_existing is None or path.read_bytes() != expected_existing:
                raise SetupError(f"{path.name} changed while setup was running; it was not overwritten. Review the files and rerun.")
        elif expected_existing is not None:
            raise SetupError(f"{path.name} changed while setup was running; it was not recreated. Review the files and rerun.")
        os.replace(temp, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        remove_temporary_file(temp)
        raise


def replace_template_secrets(text: str, generated: dict[str, str]) -> str:
    lines = text.splitlines()
    for name, value in generated.items():
        matches = [index for index, line in enumerate(lines) if ENV_NAME.match(line) and ENV_NAME.match(line).group(1) == name]
        if len(matches) != 1:
            raise SetupError(f".env.example must contain exactly one {name}= entry; restore the tracked template.")
        lines[matches[0]] = f"{name}={value}"
    return "\n".join(lines) + "\n"


def has_backup_data(root: Path) -> bool:
    backup_dir = root / "data" / "backups"
    if backup_dir.is_symlink():
        return True
    if not backup_dir.exists():
        return False
    if not backup_dir.is_dir():
        return True
    try:
        return next(backup_dir.iterdir(), None) is not None
    except OSError as exc:
        raise SetupError("Cannot inspect data/backups safely; check directory permissions before continuing.") from exc


def require_regular_or_absent(path: Path) -> bool:
    if path.is_symlink():
        raise SetupError(f"{path.name} is a symlink. Setup will not follow or replace it; review it manually.")
    if not path.exists():
        return False
    if not path.is_file():
        raise SetupError(f"{path.name} exists but is not a regular file; review it manually.")
    return True


def prepare(root: Path, volume_exists: bool, mode: str) -> int:
    root = root.resolve()
    env_file = root / ".env"
    env_template = root / ".env.example"
    compose_file = root / "compose.yaml"
    compose_template = root / "compose.example.yaml"
    env_exists = require_regular_or_absent(env_file)
    compose_exists = require_regular_or_absent(compose_file)
    if not env_template.is_file() or not compose_template.is_file():
        raise SetupError("Required tracked templates (.env.example and compose.example.yaml) are missing.")

    data_exists = has_backup_data(root)
    has_persistent_state = bool(volume_exists or data_exists)
    env_is_unmodified_template = env_exists and env_file.read_bytes() == env_template.read_bytes()
    if has_persistent_state and (not env_exists or not compose_exists):
        raise SetupError(
            "Existing PostgreSQL or backup data was detected, but .env or compose.yaml is missing. "
            "Setup stopped without generating credentials or creating files. Restore the original configuration "
            "and encryption keys from a protected copy, then rerun."
        )
    if compose_exists and not env_exists:
        raise SetupError("compose.yaml exists but .env is missing. Setup will not invent credentials for a possibly existing deployment; restore the original .env and rerun.")

    pristine = not compose_exists and not has_persistent_state and (not env_exists or env_is_unmodified_template)
    generated_count = 0
    if pristine:
        template = env_template.read_text(encoding="utf-8")
        generated = new_secrets()
        env_content = replace_template_secrets(template, generated)
        atomic_create(env_file, env_content, 0o600,
                      expected_existing=env_template.read_bytes() if env_is_unmodified_template else None)
        generated_count = len(generated)
    else:
        values = read_env(env_file)
        missing_required = [name for name in REQUIRED_SECRET_NAMES if not values.get(name, "").strip()]
        if missing_required:
            raise SetupError(
                f"Existing .env is missing required secret(s): {', '.join(missing_required)}. "
                "They were not regenerated because this may connect to an existing database or encrypted backup set. "
                "Restore the original values from a protected copy; do not reset the database password or backup key."
            )
        for name in REQUIRED_SECRET_NAMES:
            if name == "ARMORY_BACKUP_ENCRYPTION_KEY":
                validate_backup_key(name, values[name])
        if values.get("ARMORY_SECRET_KEY", "").strip():
            validate_fernet_key(values["ARMORY_SECRET_KEY"].strip())
        try:
            env_file.chmod(0o600)
        except OSError as exc:
            raise SetupError("Could not set .env permissions to 0600; check ownership and permissions.") from exc
        generated = {}

    if not compose_exists:
        atomic_create(compose_file, compose_template.read_text(encoding="utf-8"), 0o644)

    if mode == "build" and not (root / "compose.build.yaml").is_file():
        raise SetupError("compose.build.yaml is missing. Restore the tracked source-build override.")

    values = read_env(env_file)
    invalid_base = [name for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_HOST", "POSTGRES_PORT") if not values.get(name, "").strip()]
    if invalid_base:
        raise SetupError(f".env has empty required database setting(s): {', '.join(invalid_base)}. Configure them before continuing.")
    if not values.get("ARMORY_SECRET_KEY", "").strip():
        print("NOTICE: ARMORY_SECRET_KEY is unset. SMTP password storage requires this separate Fernet key; existing SMTP credentials require their original key.")
    if not generated_count and not values.get("ARMORY_BACKUP_ENCRYPTION_KEY", "").strip():
        raise SetupError("ARMORY_BACKUP_ENCRYPTION_KEY is required for encrypted backups and restores and must not be replaced when archives may exist.")

    if pristine:
        print("Prepared .env with fresh local secrets (values were not displayed).")
        if not compose_exists:
            print("Created compose.yaml from the published-image template.")
    else:
        print("Preserved existing .env values and compose.yaml; .env permissions are 0600.")
    if generated_count:
        print("Generated: PostgreSQL password, session signing secret, backup AES-256 key, and SMTP Fernet key.")
        print("Store protected copies of both encryption keys outside this host. Never replace keys used by existing data.")

    required_oidc = ("OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER", "OIDC_REDIRECT_URI")
    placeholders = ("example.com", "replace-me", "your-")
    pending = [name for name in required_oidc if not values.get(name, "").strip() or any(token in values.get(name, "").lower() for token in placeholders)]
    if pending:
        print("OPERATOR ACTION REQUIRED before starting: configure " + ", ".join(pending) + " in .env and register the matching OIDC callback URL with your identity provider.")
    else:
        print("OIDC settings are populated; verify that the callback URL matches your identity provider.")
    print("Optional: ARMORY_OPERATOR_NAME, ARMORY_SUPPORT_EMAIL, and ARMORY_SUPPORT_URL may remain blank.")
    print("SMTP delivery is optional and configured later in Admin → Email; backup scheduling is disabled until enabled in Admin → Backup & Recovery.")
    return generated_count


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    project = subparsers.add_parser("project-name")
    project.add_argument("--root", type=Path, required=True)
    action = subparsers.add_parser("prepare")
    action.add_argument("--root", type=Path, required=True)
    action.add_argument("--database-volume", choices=("true", "false"), required=True)
    action.add_argument("--mode", choices=("published", "build"), required=True)
    args = parser.parse_args()
    if args.command == "project-name":
        try:
            print(project_name(args.root, args.root / ".env"))
            return 0
        except (SetupError, OSError, UnicodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        prepare(args.root, args.database_volume == "true", args.mode)
    except KeyboardInterrupt:
        print("ERROR: Setup was interrupted. Atomic temporary files were cleaned up; rerun to resume.", file=sys.stderr)
        return 130
    except (SetupError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
