"""Tests for the Home Assistant stage deployment CLI."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.ha_stage import (
    BackupManifest,
    HAStageError,
    SmokeResult,
    StageConfig,
    build_config,
    choose_entity,
    create_backup,
    deploy_files,
    ensure_config_mount,
    ha_api_get,
    load_latest_backup,
    redacted_env_status,
    restart_home_assistant,
    restore_backup,
    run_smoke_checks,
    wait_for_ha,
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

    manifest = create_backup(config, now=datetime_for_test(), commit="abcdef0")

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

    manifest = create_backup(config, now=datetime_for_test(), commit="abcdef0")

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
    manifest = create_backup(config, now=datetime_for_test(), commit="abcdef0")
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
    manifest = create_backup(config, now=datetime_for_test(), commit="abcdef0")
    deploy_files(config)

    restore_backup(config, manifest)

    assert not config.target_dir.exists()


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

    with (
        patch("scripts.ha_stage.ha_api_get", side_effect=fake_get),
        patch("scripts.ha_stage.query_loki_for_errors", return_value="skipped"),
    ):
        result = run_smoke_checks(config, entity_id=None)

    assert result == SmokeResult(
        entity_id="media_player.naim_atom",
        state="playing",
        log_check="skipped",
    )


def datetime_for_test():
    """Return the fixed datetime used in backup tests."""
    from datetime import datetime

    return datetime(2026, 4, 24, 14, 30, 12)
