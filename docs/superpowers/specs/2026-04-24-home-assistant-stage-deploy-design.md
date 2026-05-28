# Home Assistant Stage Deploy and Smoke Test — Design Spec

## Summary

Add a repo-local Python deployment tool for testing this custom integration on the live Home Assistant instance. The tool deploys only `custom_components/naim_media_player`, creates a rollback backup before replacing live files, restarts Home Assistant, waits for the API to recover, and runs passive smoke checks against the real Naim/Atom entity.

The workflow is intended for stage/smoke testing on James's actual Home Assistant system, not for HACS release packaging.

## Goals

1. Deploy the current repo's `custom_components/naim_media_player` to `/Volumes/config/custom_components/naim_media_player`
2. Create a timestamped rollback backup before every deploy
3. Restart Home Assistant automatically after deploy or rollback
4. Wait for Home Assistant to become reachable after restart
5. Run passive smoke checks against the live HA API and existing Naim/Atom entity
6. Provide explicit commands for status, deploy, smoke, and rollback
7. Reuse the Home Assistant config repo conventions for `HASS_SERVER`, `HASS_TOKEN`, `/Volumes/config`, `hass-cli`, and Loki logs

## Non-Goals

- Do not copy or create `.envrc`
- Do not store, print, or commit `HASS_TOKEN`
- Do not manage HA secrets
- Do not deploy unrelated custom components
- Do not create or modify HA config entries through the UI/API
- Do not perform active device-control smoke tests in the first version
- Do not support remote hosts beyond James's HA config mount workflow

## Assumptions

- The user has a local `.envrc` or equivalent environment setup for this repo.
- `HASS_SERVER` and `HASS_TOKEN` are available to the process when the tool runs.
- `/Volumes/config` is the live Home Assistant `/config` SMB mount.
- The Home Assistant host is `192.168.1.111`.
- `hass-cli` is installed and can use `HASS_SERVER` / `HASS_TOKEN`.
- The live HA instance already has a Naim/Atom media player entity configured.
- The integration domain remains `naim_media_player`.

## Command Interface

Add `scripts/ha_stage.py`.

Primary commands:

```bash
uv run python scripts/ha_stage.py status
uv run python scripts/ha_stage.py deploy
uv run python scripts/ha_stage.py smoke
uv run python scripts/ha_stage.py rollback
```

Useful options:

```bash
uv run python scripts/ha_stage.py deploy --skip-local-checks
uv run python scripts/ha_stage.py deploy --entity-id media_player.naim_atom
uv run python scripts/ha_stage.py rollback --backup-id 20260424-143012-3cc9801
uv run python scripts/ha_stage.py smoke --entity-id media_player.naim_atom
uv run python scripts/ha_stage.py status --json
```

Default paths:

```text
Source:   <repo>/custom_components/naim_media_player
Target:   /Volumes/config/custom_components/naim_media_player
Backups:  /Volumes/config/custom_components/.deploy_backups/naim_media_player/<backup-id>
```

## Deployment Flow

`deploy` performs these steps in order:

1. Validate environment:
   - `HASS_SERVER` is set
   - `HASS_TOKEN` is set
   - source integration directory exists
   - target custom components parent exists or can be reached after mount
2. Ensure `/Volumes/config` is mounted:
   - If already mounted, continue without warning.
   - If missing, try `osascript` SMB mount for `smb://james@192.168.1.111/config`.
   - If still unavailable, fail before changing anything.
3. Run local verification unless `--skip-local-checks`:
   - `uv run ruff check custom_components/ tests/`
   - `uv run ruff format --check custom_components/ tests/`
   - `uv run pytest tests/ -q`
   - import check for `NaimPlayer`, `NaimClient`, `NaimPlayerState`
4. Create rollback backup:
   - If the target integration exists, copy it to a timestamped backup directory.
   - If the target integration does not exist, create a manifest recording that rollback should remove the deployed directory.
5. Replace target integration:
   - Remove only `/Volumes/config/custom_components/naim_media_player`
   - Copy only `<repo>/custom_components/naim_media_player`
6. Restart Home Assistant:
   - Use `hass-cli raw post /api/services/homeassistant/restart`
   - Do not print `HASS_TOKEN`
7. Wait for API recovery:
   - Poll `HASS_SERVER/api/` with the bearer token
   - Use a bounded timeout, for example 180 seconds
   - Show concise progress
8. Run passive smoke checks.

## Rollback Flow

`rollback` restores the latest backup by default, or a specific `--backup-id`.

Steps:

1. Validate environment and mount.
2. Locate backup manifest.
3. Restore target:
   - If backup contains a previous integration directory, replace live target with that directory.
   - If backup manifest says the target did not exist before deploy, remove live target.
4. Restart Home Assistant.
5. Wait for API recovery.
6. Run passive smoke checks.

Rollback never deletes backup history automatically.

## Backup Manifest

Each backup directory contains a manifest file such as `deploy-manifest.json`.

Example:

```json
{
  "backup_id": "20260424-143012-3cc9801",
  "created_at": "2026-04-24T14:30:12+10:00",
  "source_repo": "/Users/james/workspace/naim-atom-home-assistant/.worktrees/v0.4.0-architecture",
  "source_commit": "3cc9801",
  "target_path": "/Volumes/config/custom_components/naim_media_player",
  "target_existed": true,
  "integration_domain": "naim_media_player",
  "manifest_version": "0.4.0"
}
```

The backup ID includes timestamp plus source commit prefix so operators can connect a live deployment to a local revision.

## Passive Smoke Checks

`smoke` performs checks that do not intentionally change the device state.

Checks:

1. Live files:
   - target directory exists
   - `manifest.json`, `media_player.py`, `client.py`, and `state.py` exist
   - `websocket.py` does not exist for v0.4.0+
2. HA API:
   - `GET /api/` succeeds with bearer token
3. Entity discovery:
   - If `--entity-id` is provided, fetch that entity.
   - Otherwise list states and find media player entities matching `naim` or `atom` in entity ID or friendly name.
   - Fail if no candidate is found.
4. Entity state:
   - Fetch the selected entity state.
   - Pass if state is one of HA's normal media player states or `unavailable`.
   - Print entity ID, state, source, volume, and media title when present.
5. Logs:
   - Query Loki for recent Home Assistant logs when Loki is reachable.
   - Fail on recent warnings/errors containing `naim_media_player`.
   - If Loki is unavailable, report the log check as skipped rather than failing the whole smoke test.

No media player service calls are made in the first version.

## Status Command

`status` prints:

- source repo path and current git commit
- local integration manifest version
- whether `/Volumes/config` is mounted
- live integration path status
- live integration manifest version if present
- latest backup ID if present
- whether `HASS_SERVER` and `HASS_TOKEN` are present, without printing token contents
- HA API reachability

`--json` emits machine-readable status for future automation.

## Error Handling

The tool should fail before copying files when prerequisites are missing:

- missing `HASS_TOKEN`
- missing `HASS_SERVER`
- source directory missing
- `/Volumes/config` unavailable after mount attempt
- local checks fail

The deploy should fail after backup but before restart if copying fails. In that case it should print the rollback command using the backup ID it just created.

Restart failures should not attempt automatic rollback by default. They should report:

- whether files were deployed
- backup ID
- restart command attempted
- suggested rollback command

## Security

- Never print `HASS_TOKEN`.
- Never write `.envrc`.
- Keep `.envrc` ignored by git as a local operator concern.
- Avoid shelling through commands that interpolate token values.
- Prefer Python `requests`/`urllib` style API calls for HA API polling and log checks so headers stay in process memory and out of shell history.

## Implementation Notes

- Use only Python standard library where practical: `argparse`, `json`, `os`, `pathlib`, `shutil`, `subprocess`, `time`, `datetime`, `urllib.request`.
- Shell out to `uv`, `git`, `hass-cli`, and `osascript` only where they are the local operational interface.
- Use deterministic, targeted copy behavior. Do not copy the repo root.
- Preserve file permissions enough for HA to read the component; exact source file modes are not important.
- Keep backup directories under the live custom components folder so rollback artifacts travel with the HA config mount.

## Test Strategy

Unit tests should cover the deploy tool without touching `/Volumes/config`:

- environment validation
- backup ID generation
- manifest writing/reading
- source/target path selection
- rollback target selection
- HA API polling success/failure with mocked HTTP
- smoke entity selection from mocked state payloads
- token redaction in displayed status

Integration-style manual verification is expected for the real HA deployment:

```bash
uv run python scripts/ha_stage.py status
uv run python scripts/ha_stage.py smoke --entity-id media_player.<actual_entity>
uv run python scripts/ha_stage.py deploy --entity-id media_player.<actual_entity>
uv run python scripts/ha_stage.py rollback
```

## Open Decisions

None. The first version is passive smoke only, deploys a single integration directory, and supports manual rollback through the CLI.
