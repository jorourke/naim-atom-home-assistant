"""Deploy and smoke-test the Naim integration on a live Home Assistant instance."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

DOMAIN = "naim_media_player"
DEFAULT_CONFIG_MOUNT = Path("/Volumes/config")
DEFAULT_HA_HOST = "192.168.1.111"
MANIFEST_NAME = "deploy-manifest.json"
VALID_MEDIA_STATES = {"off", "on", "idle", "playing", "paused", "standby", "unavailable", "unknown"}


class HAStageError(RuntimeError):
    """Raised when stage deployment cannot proceed."""


@dataclass(frozen=True)
class StageConfig:
    """Resolved configuration for stage deployment."""

    repo_root: Path
    config_mount: Path
    hass_server: str
    hass_token: str
    ha_host: str = DEFAULT_HA_HOST

    @property
    def source_dir(self) -> Path:
        """Return the repo integration source directory."""
        return self.repo_root / "custom_components" / DOMAIN

    @property
    def custom_components_dir(self) -> Path:
        """Return the live custom components directory."""
        return self.config_mount / "custom_components"

    @property
    def target_dir(self) -> Path:
        """Return the live integration target directory."""
        return self.custom_components_dir / DOMAIN

    @property
    def backup_root(self) -> Path:
        """Return the rollback backup root."""
        return self.custom_components_dir / ".deploy_backups" / DOMAIN


@dataclass(frozen=True)
class BackupManifest:
    """Metadata describing a deploy rollback backup."""

    backup_id: str
    created_at: str
    source_repo: str
    source_commit: str
    target_path: str
    target_existed: bool
    integration_domain: str
    manifest_version: str | None

    def write(self, path: Path) -> None:
        """Write this manifest as JSON."""
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")

    @classmethod
    def read(cls, path: Path) -> BackupManifest:
        """Read a manifest from JSON."""
        return cls(**json.loads(path.read_text()))


def redacted_env_status(hass_server: str | None, hass_token: str | None) -> dict[str, Any]:
    """Return environment status without exposing token contents."""
    return {
        "hass_server_present": bool(hass_server),
        "hass_token_present": bool(hass_token),
        "hass_server": hass_server,
    }


def repo_root_from_script() -> Path:
    """Return the repository root based on this script location."""
    return Path(__file__).resolve().parents[1]


def read_manifest_version(source_dir: Path) -> str | None:
    """Read integration version from manifest.json."""
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text()).get("version")


def git_commit(repo_root: Path) -> str:
    """Return short git commit for repo_root."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def backup_id(now: datetime, commit: str) -> str:
    """Build a backup ID from wall-clock time and commit."""
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{commit[:7]}"


def load_latest_backup(backup_root: Path) -> BackupManifest:
    """Load the newest backup manifest by backup ID."""
    manifests = sorted(backup_root.glob(f"*/{MANIFEST_NAME}"))
    if not manifests:
        raise HAStageError(f"No rollback backups found under {backup_root}")
    return BackupManifest.read(manifests[-1])


def choose_entity(states: list[dict[str, Any]], explicit_entity_id: str | None = None) -> dict[str, Any]:
    """Choose a Naim/Atom media player entity from HA state payloads."""
    if explicit_entity_id:
        for entity in states:
            if entity.get("entity_id") == explicit_entity_id:
                return entity
        raise HAStageError(f"Entity {explicit_entity_id} not found")

    for entity in states:
        entity_id = str(entity.get("entity_id", "")).lower()
        attributes = entity.get("attributes") or {}
        friendly_name = str(attributes.get("friendly_name", "")).lower()
        if entity_id.startswith("media_player.") and (
            "naim" in entity_id or "atom" in entity_id or "naim" in friendly_name or "atom" in friendly_name
        ):
            return entity

    raise HAStageError("No Naim/Atom media player entity found")


def copytree_replace(source: Path, target: Path) -> None:
    """Replace target directory with a copy of source."""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def create_backup(config: StageConfig, now: datetime | None = None, commit: str | None = None) -> BackupManifest:
    """Create a rollback backup for the current live integration."""
    now = now or datetime.now().astimezone()
    commit = commit or git_commit(config.repo_root)
    backup = backup_id(now, commit)
    backup_dir = config.backup_root / backup
    backup_dir.mkdir(parents=True, exist_ok=False)

    target_existed = config.target_dir.exists()
    if target_existed:
        shutil.copytree(config.target_dir, backup_dir / DOMAIN)

    manifest = BackupManifest(
        backup_id=backup,
        created_at=now.astimezone().isoformat(),
        source_repo=str(config.repo_root),
        source_commit=commit,
        target_path=str(config.target_dir),
        target_existed=target_existed,
        integration_domain=DOMAIN,
        manifest_version=read_manifest_version(config.target_dir) if target_existed else None,
    )
    manifest.write(backup_dir / MANIFEST_NAME)
    return manifest


def deploy_files(config: StageConfig) -> None:
    """Copy the repo integration directory to the live HA target."""
    if not config.source_dir.exists():
        raise HAStageError(f"Source integration directory does not exist: {config.source_dir}")
    config.custom_components_dir.mkdir(parents=True, exist_ok=True)
    copytree_replace(config.source_dir, config.target_dir)


def restore_backup(config: StageConfig, manifest: BackupManifest) -> None:
    """Restore a previous integration backup."""
    backup_dir = config.backup_root / manifest.backup_id
    backup_component = backup_dir / DOMAIN
    if manifest.target_existed:
        if not backup_component.exists():
            raise HAStageError(f"Backup component directory missing: {backup_component}")
        copytree_replace(backup_component, config.target_dir)
    elif config.target_dir.exists():
        shutil.rmtree(config.target_dir)


@dataclass(frozen=True)
class SmokeResult:
    """Summary of passive smoke check result."""

    entity_id: str
    state: str
    log_check: str


def build_config(
    repo_root: Path | None = None,
    config_mount: Path = DEFAULT_CONFIG_MOUNT,
    env: dict[str, str] | None = None,
) -> StageConfig:
    """Build StageConfig from environment."""
    env = env or os.environ
    hass_server = env.get("HASS_SERVER")
    hass_token = env.get("HASS_TOKEN")
    if not hass_server:
        raise HAStageError("HASS_SERVER is required")
    if not hass_token:
        raise HAStageError("HASS_TOKEN is required")
    return StageConfig(
        repo_root=repo_root or repo_root_from_script(),
        config_mount=config_mount,
        hass_server=hass_server,
        hass_token=hass_token,
    )


def ensure_config_mount(config: StageConfig) -> None:
    """Ensure the HA config SMB mount is available."""
    if config.custom_components_dir.exists():
        return
    subprocess.run(
        ["osascript", "-e", f'mount volume "smb://james@{config.ha_host}/config"'],
        check=False,
        capture_output=True,
        text=True,
    )
    if not config.custom_components_dir.exists():
        raise HAStageError(f"Home Assistant config mount unavailable: {config.config_mount}")


def ha_api_get(hass_server: str, hass_token: str, path: str, timeout: float = 10) -> Any:
    """GET JSON from the Home Assistant API."""
    url = urljoin(hass_server.rstrip("/") + "/", path.lstrip("/"))
    request = Request(url, headers={"Authorization": f"Bearer {hass_token}"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        raise HAStageError(f"HA API request failed for {path}: {error}") from error
    return json.loads(body.decode() or "{}")


def wait_for_ha(hass_server: str, hass_token: str, timeout: float = 180, interval: float = 3) -> None:
    """Wait until Home Assistant API responds."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            ha_api_get(hass_server, hass_token, "/api/")
            return
        except HAStageError as error:
            if time.monotonic() >= deadline:
                raise HAStageError(f"Home Assistant API did not recover within {timeout:.0f}s") from error
            time.sleep(interval)


def restart_home_assistant() -> None:
    """Restart Home Assistant through hass-cli."""
    subprocess.run(
        ["hass-cli", "raw", "post", "/api/services/homeassistant/restart"],
        check=True,
    )


def validate_live_files(config: StageConfig) -> None:
    """Validate deployed integration files on the HA config mount."""
    required = ["manifest.json", "media_player.py", "client.py", "state.py"]
    if not config.target_dir.exists():
        raise HAStageError(f"Live integration directory missing: {config.target_dir}")
    for filename in required:
        if not (config.target_dir / filename).exists():
            raise HAStageError(f"Live integration file missing: {filename}")
    if (config.target_dir / "websocket.py").exists():
        raise HAStageError("websocket.py should not exist for v0.4.0+ deployment")


def query_loki_for_errors() -> str:
    """Check recent Loki logs for naim_media_player warnings/errors."""
    query = '{container_name="homeassistant"} |~ "(?i)(naim_media_player).*(error|warning|exception)"'
    params = urlencode(
        {
            "query": query,
            "limit": "20",
            "start": f"{int(time.time() - 900)}000000000",
            "end": f"{int(time.time())}000000000",
        }
    )
    request = Request(
        f"http://192.168.1.145:3100/loki/api/v1/query_range?{params}",
        headers={"X-Scope-OrgID": "tenant1"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError):
        return "skipped"
    streams = payload.get("data", {}).get("result", [])
    if streams:
        raise HAStageError("Recent naim_media_player warnings/errors found in Loki")
    return "passed"


def run_smoke_checks(config: StageConfig, entity_id: str | None = None) -> SmokeResult:
    """Run passive smoke checks against live HA."""
    validate_live_files(config)
    ha_api_get(config.hass_server, config.hass_token, "/api/")
    states = ha_api_get(config.hass_server, config.hass_token, "/api/states")
    entity = choose_entity(states, explicit_entity_id=entity_id)
    entity_id = entity["entity_id"]
    entity = ha_api_get(config.hass_server, config.hass_token, f"/api/states/{quote(entity_id)}")
    state = str(entity.get("state"))
    if state not in VALID_MEDIA_STATES:
        raise HAStageError(f"Unexpected media player state for {entity_id}: {state}")
    log_check = query_loki_for_errors()
    attributes = entity.get("attributes") or {}
    print(
        f"Smoke OK: {entity_id} state={state} "
        f"source={attributes.get('source')} volume={attributes.get('volume_level')} "
        f"title={attributes.get('media_title')} logs={log_check}"
    )
    return SmokeResult(entity_id=entity_id, state=state, log_check=log_check)


def run_local_checks(config: StageConfig) -> None:
    """Run local verification before deployment."""
    commands = [
        ["uv", "run", "ruff", "check", "custom_components/", "tests/"],
        ["uv", "run", "ruff", "format", "--check", "custom_components/", "tests/"],
        ["uv", "run", "pytest", "tests/", "-q"],
        [
            "uv",
            "run",
            "python",
            "-c",
            (
                "from custom_components.naim_media_player.media_player import NaimPlayer; "
                "from custom_components.naim_media_player.client import NaimClient; "
                "from custom_components.naim_media_player.state import NaimPlayerState; "
                "print('All imports OK')"
            ),
        ],
    ]
    for command in commands:
        subprocess.run(command, cwd=config.repo_root, check=True)


def command_status(args: argparse.Namespace) -> int:
    """Print local and live deployment status."""
    config = build_config()
    status = {
        "repo_root": str(config.repo_root),
        "source_commit": git_commit(config.repo_root),
        "local_manifest_version": read_manifest_version(config.source_dir),
        "config_mount": str(config.config_mount),
        "config_mounted": config.custom_components_dir.exists(),
        "target_path": str(config.target_dir),
        "target_exists": config.target_dir.exists(),
        "target_manifest_version": read_manifest_version(config.target_dir),
        "env": redacted_env_status(config.hass_server, config.hass_token),
        "latest_backup_id": None,
        "ha_api_reachable": False,
    }
    try:
        status["latest_backup_id"] = load_latest_backup(config.backup_root).backup_id
    except HAStageError:
        pass
    try:
        ha_api_get(config.hass_server, config.hass_token, "/api/", timeout=3)
        status["ha_api_reachable"] = True
    except HAStageError:
        pass

    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        for key, value in status.items():
            print(f"{key}: {value}")
    return 0


def command_smoke(args: argparse.Namespace) -> int:
    """Run passive smoke checks."""
    config = build_config()
    ensure_config_mount(config)
    run_smoke_checks(config, entity_id=args.entity_id)
    return 0


def command_deploy(args: argparse.Namespace) -> int:
    """Deploy integration to live HA and smoke test it."""
    config = build_config()
    ensure_config_mount(config)
    if not args.skip_local_checks:
        run_local_checks(config)
    manifest = create_backup(config)
    print(f"Created rollback backup: {manifest.backup_id}")
    try:
        deploy_files(config)
    except Exception:
        print(
            "Deploy failed after backup. Roll back with: "
            f"uv run python scripts/ha_stage.py rollback --backup-id {manifest.backup_id}"
        )
        raise
    restart_home_assistant()
    wait_for_ha(config.hass_server, config.hass_token)
    run_smoke_checks(config, entity_id=args.entity_id)
    return 0


def command_rollback(args: argparse.Namespace) -> int:
    """Restore a previous deployment backup."""
    config = build_config()
    ensure_config_mount(config)
    manifest = (
        BackupManifest.read(config.backup_root / args.backup_id / MANIFEST_NAME)
        if args.backup_id
        else load_latest_backup(config.backup_root)
    )
    restore_backup(config, manifest)
    print(f"Restored rollback backup: {manifest.backup_id}")
    restart_home_assistant()
    wait_for_ha(config.hass_server, config.hass_token)
    run_smoke_checks(config, entity_id=args.entity_id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--entity-id")
    smoke.set_defaults(func=command_smoke)

    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--skip-local-checks", action="store_true")
    deploy.add_argument("--entity-id")
    deploy.set_defaults(func=command_deploy)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--backup-id")
    rollback.add_argument("--entity-id")
    rollback.set_defaults(func=command_rollback)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except HAStageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
