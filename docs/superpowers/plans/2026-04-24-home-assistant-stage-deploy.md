# Home Assistant Stage Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repo-local Python CLI that deploys `naim_media_player` to the live Home Assistant config mount, runs passive smoke checks, and supports rollback.

**Architecture:** Add one testable Python script at `scripts/ha_stage.py` with pure helper functions for environment/status/backup/smoke behavior and small command handlers for `status`, `smoke`, `deploy`, and `rollback`. Unit tests mock filesystem, subprocess, and HA HTTP calls so they do not touch `/Volumes/config` or the live HA API.

**Tech Stack:** Python 3.14 standard library (`argparse`, `dataclasses`, `json`, `pathlib`, `shutil`, `subprocess`, `urllib`), pytest, Ruff, Home Assistant CLI.

---

## File Map

| File | Action | Responsibility |
| --- | --- | --- |
| `.gitignore` | MODIFY | Ignore local `.envrc` so `HASS_TOKEN` stays untracked |
| `scripts/ha_stage.py` | CREATE | CLI, deployment, backup/rollback, restart, smoke checks |
| `tests/test_ha_stage.py` | CREATE | Unit tests for config, backup manifest, smoke helpers, rollback selection, and token redaction |

---

### Task 1: Add Tests for Config, Backup Manifest, Entity Selection, and Redaction

**Files:**

- Create: `tests/test_ha_stage.py`

- [ ] **Step 1: Write failing tests for pure helpers**

Create `tests/test_ha_stage.py`:

```python
"""Tests for the Home Assistant stage deployment CLI."""

import json
from pathlib import Path

import pytest

from scripts.ha_stage import (
    BackupManifest,
    HAStageError,
    StageConfig,
    choose_entity,
    load_latest_backup,
    redacted_env_status,
)


def test_stage_config_uses_repo_paths(tmp_path: Path):
    """StageConfig derives source, target, and backup paths."""
    config = StageConfig(
        repo_root=tmp_path,
        config_mount=tmp_path / "config",
        hass_server="http://ha.local:8123",
        hass_token="secret-token",
    )

    assert config.source_dir == tmp_path / "custom_components" / "naim_media_player"
    assert config.target_dir == tmp_path / "config" / "custom_components" / "naim_media_player"
    assert config.backup_root == tmp_path / "config" / "custom_components" / ".deploy_backups" / "naim_media_player"


def test_redacted_env_status_never_returns_token():
    """Status output must report token presence without leaking the value."""
    status = redacted_env_status("http://ha.local:8123", "secret-token")

    assert status == {
        "hass_server_present": True,
        "hass_token_present": True,
        "hass_server": "http://ha.local:8123",
    }
    assert "secret-token" not in json.dumps(status)


def test_backup_manifest_round_trip(tmp_path: Path):
    """Backup manifests can be written and loaded."""
    manifest = BackupManifest(
        backup_id="20260424-143012-abcdef0",
        created_at="2026-04-24T14:30:12+10:00",
        source_repo=str(tmp_path),
        source_commit="abcdef0",
        target_path=str(tmp_path / "target"),
        target_existed=True,
        integration_domain="naim_media_player",
        manifest_version="0.4.0",
    )

    path = tmp_path / "deploy-manifest.json"
    manifest.write(path)

    assert BackupManifest.read(path) == manifest


def test_load_latest_backup_uses_newest_manifest(tmp_path: Path):
    """Latest backup is selected by lexicographic backup ID order."""
    old_dir = tmp_path / "20260424-010000-aaaaaaa"
    new_dir = tmp_path / "20260424-020000-bbbbbbb"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)

    BackupManifest(
        backup_id=old_dir.name,
        created_at="2026-04-24T01:00:00+10:00",
        source_repo="/repo",
        source_commit="aaaaaaa",
        target_path="/target",
        target_existed=True,
        integration_domain="naim_media_player",
        manifest_version="0.3.0",
    ).write(old_dir / "deploy-manifest.json")
    BackupManifest(
        backup_id=new_dir.name,
        created_at="2026-04-24T02:00:00+10:00",
        source_repo="/repo",
        source_commit="bbbbbbb",
        target_path="/target",
        target_existed=True,
        integration_domain="naim_media_player",
        manifest_version="0.4.0",
    ).write(new_dir / "deploy-manifest.json")

    manifest = load_latest_backup(tmp_path)

    assert manifest.backup_id == new_dir.name


def test_load_latest_backup_errors_when_none_exist(tmp_path: Path):
    """Missing backup manifests produce a clear error."""
    with pytest.raises(HAStageError, match="No rollback backups found"):
        load_latest_backup(tmp_path)


def test_choose_entity_prefers_explicit_entity():
    """Explicit entity IDs are selected from state payloads."""
    states = [
        {"entity_id": "media_player.kitchen", "state": "off", "attributes": {}},
        {"entity_id": "media_player.naim_atom", "state": "playing", "attributes": {}},
    ]

    entity = choose_entity(states, explicit_entity_id="media_player.naim_atom")

    assert entity["entity_id"] == "media_player.naim_atom"


def test_choose_entity_finds_naim_or_atom_candidate():
    """Automatic discovery matches entity ID or friendly name."""
    states = [
        {"entity_id": "media_player.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen"}},
        {"entity_id": "media_player.lounge", "state": "on", "attributes": {"friendly_name": "Naim Atom"}},
    ]

    entity = choose_entity(states)

    assert entity["entity_id"] == "media_player.lounge"


def test_choose_entity_errors_when_no_candidate():
    """Smoke checks fail clearly when no Naim/Atom entity exists."""
    states = [{"entity_id": "light.kitchen", "state": "on", "attributes": {}}]

    with pytest.raises(HAStageError, match="No Naim/Atom media player entity found"):
        choose_entity(states)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_ha_stage.py -v
```

Expected: FAIL during collection because `scripts.ha_stage` does not exist.

- [ ] **Step 3: Commit is not needed yet**

This task only creates the RED state for the helper API. Commit after Task 2 passes.

---

### Task 2: Implement Core Helper API

**Files:**

- Create: `scripts/ha_stage.py`
- Modify: `.gitignore`
- Test: `tests/test_ha_stage.py`

- [ ] **Step 1: Add `.envrc` to `.gitignore`**

Append near the existing environment section in `.gitignore`:

```gitignore
.envrc
```

- [ ] **Step 2: Create the script with core helpers**

Create `scripts/ha_stage.py`:

```python
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
        return self.repo_root / "custom_components" / DOMAIN

    @property
    def custom_components_dir(self) -> Path:
        return self.config_mount / "custom_components"

    @property
    def target_dir(self) -> Path:
        return self.custom_components_dir / DOMAIN

    @property
    def backup_root(self) -> Path:
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
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")

    @classmethod
    def read(cls, path: Path) -> BackupManifest:
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
```

- [ ] **Step 3: Run helper tests**

Run:

```bash
uv run pytest tests/test_ha_stage.py -v
```

Expected: PASS for the helper tests.

- [ ] **Step 4: Run linter and formatter checks**

Run:

```bash
uv run ruff check scripts/ha_stage.py tests/test_ha_stage.py
uv run ruff format --check scripts/ha_stage.py tests/test_ha_stage.py
```

Expected: all checks passed.

- [ ] **Step 5: Commit**

Run:

```bash
git add .gitignore scripts/ha_stage.py tests/test_ha_stage.py
git commit -m "feat: add HA stage deploy helper core"
```

---

### Task 3: Add Tests for Filesystem Backup, Deploy, and Rollback

**Files:**

- Modify: `tests/test_ha_stage.py`

- [ ] **Step 1: Append failing filesystem workflow tests**

Append to `tests/test_ha_stage.py`:

```python
from scripts.ha_stage import create_backup, deploy_files, restore_backup


def write_integration(path: Path, version: str, marker: str) -> None:
    """Create a minimal integration directory for filesystem tests."""
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({"version": version}) + "\n")
    (path / "media_player.py").write_text(f"# {marker}\n")
    (path / "client.py").write_text(f"# {marker}\n")
    (path / "state.py").write_text(f"# {marker}\n")


def test_create_backup_copies_existing_target(tmp_path: Path):
    """Existing live integration is copied to a timestamped backup."""
    repo = tmp_path / "repo"
    mount = tmp_path / "config"
    source = repo / "custom_components" / "naim_media_player"
    target = mount / "custom_components" / "naim_media_player"
    write_integration(source, "0.4.0", "new")
    write_integration(target, "0.3.0", "old")
    config = StageConfig(repo, mount, "http://ha.local:8123", "token")

    manifest = create_backup(config, now=datetime(2026, 4, 24, 14, 30, 12), commit="abcdef0")

    backup_dir = config.backup_root / manifest.backup_id / "naim_media_player"
    assert manifest.target_existed is True
    assert (backup_dir / "manifest.json").exists()
    assert json.loads((backup_dir / "manifest.json").read_text())["version"] == "0.3.0"


def test_create_backup_records_missing_target(tmp_path: Path):
    """Missing live integration still creates a rollback manifest."""
    repo = tmp_path / "repo"
    mount = tmp_path / "config"
    (mount / "custom_components").mkdir(parents=True)
    source = repo / "custom_components" / "naim_media_player"
    write_integration(source, "0.4.0", "new")
    config = StageConfig(repo, mount, "http://ha.local:8123", "token")

    manifest = create_backup(config, now=datetime(2026, 4, 24, 14, 30, 12), commit="abcdef0")

    assert manifest.target_existed is False
    assert (config.backup_root / manifest.backup_id / "deploy-manifest.json").exists()


def test_deploy_files_replaces_only_integration_target(tmp_path: Path):
    """Deploy replaces naim_media_player without touching sibling components."""
    repo = tmp_path / "repo"
    mount = tmp_path / "config"
    source = repo / "custom_components" / "naim_media_player"
    target = mount / "custom_components" / "naim_media_player"
    sibling = mount / "custom_components" / "amber_energy"
    write_integration(source, "0.4.0", "new")
    write_integration(target, "0.3.0", "old")
    sibling.mkdir(parents=True)
    (sibling / "manifest.json").write_text("{}\n")
    config = StageConfig(repo, mount, "http://ha.local:8123", "token")

    deploy_files(config)

    assert json.loads((target / "manifest.json").read_text())["version"] == "0.4.0"
    assert (sibling / "manifest.json").exists()


def test_restore_backup_restores_previous_target(tmp_path: Path):
    """Rollback restores the backed-up integration directory."""
    repo = tmp_path / "repo"
    mount = tmp_path / "config"
    source = repo / "custom_components" / "naim_media_player"
    target = mount / "custom_components" / "naim_media_player"
    write_integration(source, "0.4.0", "new")
    write_integration(target, "0.3.0", "old")
    config = StageConfig(repo, mount, "http://ha.local:8123", "token")
    manifest = create_backup(config, now=datetime(2026, 4, 24, 14, 30, 12), commit="abcdef0")
    deploy_files(config)

    restore_backup(config, manifest)

    assert json.loads((target / "manifest.json").read_text())["version"] == "0.3.0"


def test_restore_backup_removes_target_when_original_missing(tmp_path: Path):
    """Rollback removes deployed files if no original integration existed."""
    repo = tmp_path / "repo"
    mount = tmp_path / "config"
    (mount / "custom_components").mkdir(parents=True)
    source = repo / "custom_components" / "naim_media_player"
    write_integration(source, "0.4.0", "new")
    config = StageConfig(repo, mount, "http://ha.local:8123", "token")
    manifest = create_backup(config, now=datetime(2026, 4, 24, 14, 30, 12), commit="abcdef0")
    deploy_files(config)

    restore_backup(config, manifest)

    assert not config.target_dir.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_ha_stage.py -v
```

Expected: FAIL because `create_backup`, `deploy_files`, and `restore_backup` are not implemented.

---

### Task 4: Implement Filesystem Backup, Deploy, and Rollback

**Files:**

- Modify: `scripts/ha_stage.py`
- Test: `tests/test_ha_stage.py`

- [ ] **Step 1: Add filesystem functions**

Append these functions to `scripts/ha_stage.py` after `choose_entity()`:

```python
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
```

- [ ] **Step 2: Run filesystem tests**

Run:

```bash
uv run pytest tests/test_ha_stage.py -v
```

Expected: PASS.

- [ ] **Step 3: Run linter and formatter checks**

Run:

```bash
uv run ruff check scripts/ha_stage.py tests/test_ha_stage.py
uv run ruff format --check scripts/ha_stage.py tests/test_ha_stage.py
```

Expected: all checks passed.

- [ ] **Step 4: Commit**

Run:

```bash
git add scripts/ha_stage.py tests/test_ha_stage.py
git commit -m "feat: add HA stage deploy backup and rollback"
```

---

### Task 5: Add Tests for HA API, Smoke Checks, Mounting, Restart, and CLI Status

**Files:**

- Modify: `tests/test_ha_stage.py`

- [ ] **Step 1: Append failing tests for operational behavior**

Append to `tests/test_ha_stage.py`:

```python
from unittest.mock import MagicMock, patch

from scripts.ha_stage import (
    SmokeResult,
    build_config,
    ensure_config_mount,
    ha_api_get,
    restart_home_assistant,
    run_smoke_checks,
    wait_for_ha,
)


def test_build_config_requires_hass_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing HA environment fails before deployment."""
    monkeypatch.delenv("HASS_SERVER", raising=False)
    monkeypatch.delenv("HASS_TOKEN", raising=False)

    with pytest.raises(HAStageError, match="HASS_SERVER"):
        build_config(repo_root=tmp_path, config_mount=tmp_path / "config")


def test_ensure_config_mount_noops_when_custom_components_exists(tmp_path: Path):
    """Already-mounted config continues without osascript."""
    config = StageConfig(tmp_path, tmp_path / "config", "http://ha.local:8123", "token")
    config.custom_components_dir.mkdir(parents=True)

    with patch("subprocess.run") as run:
        ensure_config_mount(config)

    run.assert_not_called()


def test_ensure_config_mount_attempts_mount_when_missing(tmp_path: Path):
    """Missing config mount triggers one SMB mount attempt."""
    config = StageConfig(tmp_path, tmp_path / "config", "http://ha.local:8123", "token")

    def fake_run(*args, **kwargs):
        config.custom_components_dir.mkdir(parents=True)
        return subprocess.CompletedProcess(args[0], 0)

    with patch("subprocess.run", side_effect=fake_run) as run:
        ensure_config_mount(config)

    run.assert_called_once()


def test_ha_api_get_sends_bearer_token():
    """HA API calls use Authorization header without exposing token."""
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"message":"ok"}'

    with patch("scripts.ha_stage.urlopen", return_value=response) as mocked_urlopen:
        payload = ha_api_get("http://ha.local:8123", "secret-token", "/api/")

    request = mocked_urlopen.call_args.args[0]
    assert payload == {"message": "ok"}
    assert request.headers["Authorization"] == "Bearer secret-token"


def test_wait_for_ha_retries_until_api_succeeds():
    """HA readiness polling tolerates temporary connection failures."""
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HAStageError("not ready")
        return {"message": "ok"}

    with (
        patch("scripts.ha_stage.ha_api_get", side_effect=fake_get),
        patch("time.sleep"),
    ):
        wait_for_ha("http://ha.local:8123", "token", timeout=5, interval=0.01)

    assert calls == 2


def test_restart_home_assistant_uses_hass_cli():
    """Restart command delegates to hass-cli."""
    with patch("subprocess.run") as run:
        restart_home_assistant()

    run.assert_called_once_with(
        ["hass-cli", "raw", "post", "/api/services/homeassistant/restart"],
        check=True,
    )


def test_run_smoke_checks_reports_entity_and_skips_loki(tmp_path: Path):
    """Passive smoke checks validate files, HA API, and entity state."""
    config = StageConfig(tmp_path, tmp_path / "config", "http://ha.local:8123", "token")
    write_integration(config.target_dir, "0.4.0", "live")
    states = [
        {
            "entity_id": "media_player.naim_atom",
            "state": "playing",
            "attributes": {"friendly_name": "Naim Atom", "source": "Spotify", "volume_level": 0.2},
        }
    ]

    def fake_get(server, token, path):
        if path == "/api/":
            return {"message": "API running."}
        if path == "/api/states":
            return states
        if path == "/api/states/media_player.naim_atom":
            return states[0]
        raise AssertionError(path)

    with patch("scripts.ha_stage.ha_api_get", side_effect=fake_get):
        result = run_smoke_checks(config, entity_id=None)

    assert result == SmokeResult(
        entity_id="media_player.naim_atom",
        state="playing",
        log_check="skipped",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_ha_stage.py -v
```

Expected: FAIL because the operational functions do not exist.

---

### Task 6: Implement HA API, Smoke Checks, Mounting, Restart, and CLI

**Files:**

- Modify: `scripts/ha_stage.py`
- Test: `tests/test_ha_stage.py`

- [ ] **Step 1: Add operational dataclass and functions**

Append to `scripts/ha_stage.py`:

```python
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
        except HAStageError:
            if time.monotonic() >= deadline:
                raise HAStageError(f"Home Assistant API did not recover within {timeout:.0f}s")
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
```

- [ ] **Step 2: Add command handlers and parser**

Append to `scripts/ha_stage.py`:

```python
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
        print(f"Deploy failed after backup. Roll back with: uv run python scripts/ha_stage.py rollback --backup-id {manifest.backup_id}")
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
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_ha_stage.py -v
```

Expected: PASS.

- [ ] **Step 4: Run linter and formatter checks**

Run:

```bash
uv run ruff check scripts/ha_stage.py tests/test_ha_stage.py
uv run ruff format --check scripts/ha_stage.py tests/test_ha_stage.py
```

Expected: all checks passed.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/ha_stage.py tests/test_ha_stage.py
git commit -m "feat: add HA stage smoke and CLI commands"
```

---

### Task 7: Full Verification and Documentation

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Add README deployment section**

Add this section to `README.md`:

```markdown
## Home Assistant Stage Deploy

This repo includes a local-only deployment helper for testing the integration on James's Home Assistant instance.

Prerequisites:

- `.envrc` or shell environment provides `HASS_SERVER` and `HASS_TOKEN`
- `/Volumes/config` is the Home Assistant `/config` SMB mount, or the helper can mount it via macOS Finder/Keychain
- `hass-cli` is installed

Commands:

```bash
uv run python scripts/ha_stage.py status
uv run python scripts/ha_stage.py smoke --entity-id media_player.naim_atom
uv run python scripts/ha_stage.py deploy --entity-id media_player.naim_atom
uv run python scripts/ha_stage.py rollback
```

Every deploy creates a timestamped backup under `/Volumes/config/custom_components/.deploy_backups/naim_media_player/`.
Rollback restores the latest backup by default, restarts Home Assistant, and reruns passive smoke checks.

The helper never prints `HASS_TOKEN` and does not create or copy `.envrc`.
```
```

- [ ] **Step 2: Run full test suite**

Run:

```bash
uv run pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Run full Ruff checks**

Run:

```bash
uv run ruff check custom_components/ tests/ scripts/
uv run ruff format --check custom_components/ tests/ scripts/
```

Expected: all checks passed.

- [ ] **Step 4: Run CLI help and status**

Run:

```bash
uv run python scripts/ha_stage.py --help
uv run python scripts/ha_stage.py status --json
```

Expected:

- help shows `status`, `smoke`, `deploy`, and `rollback`
- status JSON never includes the raw `HASS_TOKEN`

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md scripts/ha_stage.py tests/test_ha_stage.py .gitignore
git commit -m "docs: document HA stage deploy workflow"
```

---

### Task 8: Optional Live Smoke Check

**Files:** None.

- [ ] **Step 1: Run passive smoke against live HA if environment is available**

Run:

```bash
uv run python scripts/ha_stage.py smoke
```

Expected:

- If `HASS_SERVER`, `HASS_TOKEN`, `/Volumes/config`, and HA API are available: PASS with selected entity details.
- If HA is unreachable from this shell: FAIL clearly without printing the token.

- [ ] **Step 2: Do not commit live-only output**

No files should change from this task.
