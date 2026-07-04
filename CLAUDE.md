# Naim Atom Home Assistant Integration

## Project Overview

This is a **HACS (Home Assistant Community Store)** custom integration that provides local network control of **Naim audio devices** (primarily Naim Atom). The integration creates a fully-featured media player entity in Home Assistant with real-time status updates.

**Version:** 0.5.1 (see `manifest.json` for the current release)
**Type:** Local IoT integration (no cloud dependency)
**Communication:** Dual protocol (HTTP API + WebSocket), consolidated into one client

## Architecture

```
Home Assistant Media Player Entity
         ↓
    NaimPlayer (media_player.py)
         ↓
    NaimClient (client.py)
    ┌────────────┬────────────┐
    ↓            ↓            ↓
HTTP requests  WebSocket   NaimPlayerState (state.py)
(15081)        (4545)      (asyncio.Lock, single source of truth)
    ↓            ↓
        Naim Atom Device
```

### Core Components

- **`media_player.py`** - Thin HA entity adapter; delegates I/O to `client.py` and reads all state from `state.py`
- **`client.py`** - Consolidated HTTP API client + WebSocket listener (`NaimClient`); owns retries/backoff and WebSocket reconnect/buffering
- **`state.py`** - `NaimPlayerState`/`MediaInfo`; single source of truth for device state, updated only via `NaimPlayerState.update(...)` under an `asyncio.Lock`, with debounce and value-guard logic
- **`config_flow.py`** - UI setup + options flow; device discovery (serial, inputs) and identity (unique_id) resolution
- **`const.py`** - Configuration constants (ports, intervals, steps)
- **`exceptions.py`** - Custom exception hierarchy

There is no separate `websocket.py` module — the WebSocket listener, reconnect loop, and buffered JSON parsing live in `client.py` alongside the HTTP methods.

### Communication Protocols

#### HTTP API (Port 15081)
Used for **control commands** with immediate feedback:
- Power: `PUT /power?system=on|lona`
- Volume: `PUT /levels/room?volume=0-100&mute=0|1`
- Playback: `GET /nowplaying?cmd=playpause|next|prev|seek`
- Source: `GET /inputs/{input}?cmd=select`

#### WebSocket (Port 4545)
Used for **real-time status updates**:
- Persistent TCP connection
- Line-delimited JSON messages
- Auto-reconnect with exponential backoff
- Incremental JSON parsing for streaming data

## Code Patterns & Conventions

### Async/Await Everywhere
- All I/O operations are async
- Use `asyncio.Lock()` for thread-safe state updates
- Use `async_get_clientsession()` for HTTP requests

### Debounce Mechanism (Critical)
```python
# state.py — NaimPlayerState
DEBOUNCED_FIELDS = {"volume", "muted"}
_debounce_timestamps: dict[str, float]  # per-field, set on source="user" updates
_debounce_timeout: float = 2.0          # 2 second window; non-"user" updates to a
                                         # debounced field are ignored inside this window
```

**Why:** When user changes volume via UI → HTTP command → device updates → WebSocket echoes change → UI would flicker. Debounce prevents this.

### Error Handling Pattern
`client.py` never optimistically writes state and then reverts it. Each setter sends the HTTP
command first; `NaimPlayerState.update(...)` (with `source="user"`) only runs after the command
succeeds. If the HTTP call raises, the exception propagates and state is left untouched — a
later poll or WebSocket update is free to correct it:
```python
async def set_volume(self, volume: int) -> None:
    await self.set_value("levels/room", {"volume": volume})  # raises on failure
    await self._state.update(source="user", volume=volume / 100)  # only reached on success
```

### Retry Logic
```python
for retry in range(max_retries):
    try:
        return await operation()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        if retry < max_retries - 1:
            await asyncio.sleep(2**retry)  # Exponential backoff
```
Polling (`poll_state`) passes `single_attempt=True` through `_get_json_safe`/`_get_json`/`_request`
so a slow/unreachable device never blocks `async_update` for the full retry duration; the safe
path (`_get_json_safe`) always returns `None` on failure instead of raising, and malformed JSON
bodies are treated the same as any other failed attempt (never escape `poll_state`).

### State Management
```python
class NaimPlayerState:
    _lock: asyncio.Lock  # Thread-safe updates

    async def update(self, **kwargs):
        async with self._lock:
            # Update state atomically
```

## Development Workflows

### Adding New Features

1. **Research existing patterns** - Read similar features first
2. **Update client.py** - Add API methods if needed
3. **Update media_player.py** - Implement entity methods
4. **Add tests** - Update test files
5. **Test manually** - Use Home Assistant dev environment

### Fixing Bugs

1. **Check debounce logic** - Most UI issues are timing-related
2. **Check WebSocket parsing** - JSON streaming can be fragile
3. **Check state locking** - Race conditions cause flicker
4. **Add logging** - DEBUG level logs help diagnose issues

### Testing

**Run tests:**
```bash
uv run pytest tests/
```

**Check formatting:**
```bash
uv run ruff format --check custom_components/ tests/
```

**Fix formatting:**
```bash
uv run ruff format custom_components/ tests/
```

**Run linter:**
```bash
uv run ruff check custom_components/ tests/
```

**Test structure:**
- `test_client.py` - HTTP client and WebSocket tests
- `test_state.py` - `NaimPlayerState`/`MediaInfo` behavior tests
- `test_media_player.py` - Entity behavior tests
- `test_config_flow.py` - Configuration UI tests
- `test_init.py` - Integration setup/options-reload tests
- `test_ha_stage.py` - `scripts/ha_stage.py` deploy helper tests (mocks subprocess/HTTP)
- `conftest.py` - Shared fixtures

**Mocking:**
- Use `aioresponses` for HTTP mocking
- Use `AsyncMock` for async methods
- Mock WebSocket connections for integration tests

## Common Tasks

### Adding a New Source

Sources are normally discovered live from the device's `/inputs` endpoint during config flow
setup (and refreshed in the options flow), and stored per-entry as `CONF_SOURCES`. Update
`NaimPlayer.DEFAULT_SOURCE_MAP` in media_player.py only to extend the hardcoded fallback used
when a device's inputs can't be discovered:
```python
DEFAULT_SOURCE_MAP = {
    "New Source": "newsource",  # Add here
    # ...
}
```

### Changing Debounce Timing

Edit the constant in state.py:
```python
_debounce_timeout: float = 2.0  # User action ignore window, applies to DEBOUNCED_FIELDS
```

### Changing the Volume Step

The volume step is user-configurable (1-20%) via `CONF_VOLUME_STEP` in the config/options flow;
`DEFAULT_VOLUME_STEP` in const.py is only the pre-filled default (5%).

### Adding New Device Commands

1. Add method to `NaimClient` in client.py
2. Add corresponding method to `NaimPlayer` entity
3. Update supported features flags if needed

## Configuration Constants

```python
DOMAIN = "naim_media_player"
DEFAULT_PORT = 4545              # WebSocket
DEFAULT_HTTP_PORT = 15081        # HTTP API
CONF_VOLUME_STEP = "volume_step" # user-configurable, 1-20 (integer percent)
DEFAULT_VOLUME_STEP = 5          # 5% default
CONF_SOURCES = "sources"         # discovered/selected input map, stored per config entry
CONF_SERIAL = "serial"           # device serial, used for identity + device registry
SOCKET_RECONNECT_INTERVAL = 5    # seconds
```

## Naim Device API Reference

### Transport States
- `1` = Stopped
- `2` = Playing
- `3` = Paused

### Input IDs
- `ana1` - Analog 1
- `dig1`, `dig2`, `dig3` - Digital 1/2/3
- `bluetooth` - Bluetooth
- `radio` - Web Radio
- `spotify` - Spotify Connect
- `roon` - Roon endpoint
- `hdmi` - HDMI ARC

### WebSocket Message Structure
```json
{
  "data": {
    "state": "playing|paused|stopped",
    "trackRoles": {
      "title": "Track Title",
      "mediaData": {
        "metaData": {
          "artist": "Artist",
          "album": "Album"
        }
      }
    }
  },
  "playTime": {
    "i64_": position_ms
  }
}
```

## Known Issues & Considerations

### Feedback Loops
**Problem:** User action → HTTP command → device updates → WebSocket echo → UI flicker
**Solution:** Debounce mechanism ignores device updates for 2 seconds after user action

### WebSocket Reconnection
**Problem:** Device may close WebSocket connection unexpectedly
**Solution:** Auto-reconnect with exponential backoff (5s base interval)

### Partial JSON Messages
**Problem:** TCP stream may deliver incomplete JSON
**Solution:** Buffer incomplete data and use `JSONDecoder.raw_decode()`

### Volume Precision
**Problem:** Device uses 0-100 scale, HA uses 0.0-1.0
**Solution:** Convert with `int(volume * 100)` and round appropriately

## File Structure

```
custom_components/naim_media_player/
├── __init__.py           # Integration setup/unload, options-reload listener
├── const.py              # Constants
├── exceptions.py         # Custom exceptions
├── state.py              # NaimPlayerState / MediaInfo — single source of truth
├── client.py             # Consolidated HTTP API client + WebSocket listener
├── media_player.py       # Main entity implementation
├── config_flow.py        # UI configuration + options flow
├── manifest.json         # Integration metadata
└── translations/
    └── en.json           # UI strings

scripts/
└── ha_stage.py           # Deploy helper (needs HASS_SERVER/HASS_TOKEN; not part of the test gates)

tests/
├── conftest.py           # Pytest fixtures
├── test_client.py        # Client tests
├── test_state.py         # State management tests
├── test_media_player.py  # Entity tests
├── test_config_flow.py   # Config flow tests
├── test_init.py          # Integration setup tests
└── test_ha_stage.py      # Deploy helper tests (mocked)
```

## Dependencies

**None!** This integration uses only Home Assistant's built-in `aiohttp` library.

## Version History

- **v0.5.x** - Reliability/quality fixes (issue #21): deterministic serial/IP identity, unified
  entity/config-entry unique_id, position-timestamp and negative-duration guards, malformed-JSON
  tolerance in polling
- **v0.5.0** - Configurable integer volume step (1-20%) with options-flow reconfigure support
- **v0.4.x** - Device-registry integration, serial-based unique_id, options-flow reload,
  `state.py`/`client.py` consolidation (WebSocket folded into `client.py`, `websocket.py` removed)
- **v0.2.0** - WebSocket real-time updates, debounce mechanism, enhanced error handling
- **v0.1.1** - Config flow UI, improved setup
- **v0.1.0** - Initial release

## Contributing Guidelines

### Code Style
- Use async/await for all I/O
- Add type hints where helpful (but not required)
- Follow Home Assistant entity patterns
- Keep line length reasonable (~100 chars)
- Use `_LOGGER` for debug/error logging

### Commit Messages
Follow conventional commits with emoji:
- `✨ feat:` - New features
- `🐛 fix:` - Bug fixes
- `♻️ refactor:` - Code refactoring
- `📝 docs:` - Documentation
- `✅ test:` - Tests

### Before Committing
1. Run tests: `pytest tests/`
2. Test in Home Assistant dev environment
3. Update this CLAUDE.md if architecture changes

## Debugging Tips

### Enable Debug Logging
In Home Assistant `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.naim_media_player: debug
```

### Common Issues

**"No WebSocket connection"**
- Check device is powered on
- Verify port 4545 is accessible
- Check firewall rules

**"Volume changes are jerky"**
- Adjust debounce timeout
- Check WebSocket message rate
- Verify network latency

**"Album art not showing"**
- Check artwork URL in WebSocket data
- Verify HTTP access to artwork host
- Check CORS if artwork is external

**"Entity unavailable"**
- Check HTTP API connectivity (port 15081)
- Verify device power state
- Check error logs for connection failures

## Testing Checklist

Before merging changes:
- [ ] All pytest tests pass
- [ ] Manual test in Home Assistant
- [ ] Volume control works smoothly
- [ ] Source switching works
- [ ] Play/pause responsive
- [ ] Album art displays
- [ ] WebSocket reconnects after device restart
- [ ] Config flow works for new devices
- [ ] No error logs during normal operation

## Quick Reference

**Start development environment:**
```bash
# Home Assistant dev container
# Mount this repo to custom_components/naim_media_player
```

**Run tests:**
```bash
uv run pytest tests/ -v
```

**Check formatting:**
```bash
uv run ruff format --check custom_components/ tests/
```

**Fix formatting:**
```bash
uv run ruff format custom_components/ tests/
```

**Run linter:**
```bash
uv run ruff check custom_components/ tests/
```

**Create release:**
1. Update version in `manifest.json`
2. Tag commit: `git tag v0.x.x`
3. Push: `git push origin v0.x.x`
4. HACS will auto-detect new release
