# Naim Atom Home Assistant Integration

## Project Overview

This is a **HACS (Home Assistant Community Store)** custom integration that provides local network control of **Naim audio devices** (primarily Naim Atom). The integration creates a fully-featured media player entity in Home Assistant with real-time status updates.

**Version:** 0.2.0
**Type:** Local IoT integration (no cloud dependency)
**Communication:** Dual protocol (HTTP API + WebSocket)

## Architecture

```
Home Assistant Media Player Entity
         ↓
    NaimPlayer (media_player.py)
         ↓
    ┌────────────┬────────────┐
    ↓            ↓            ↓
HTTP Client  WebSocket   State Manager
(15081)      (4545)      (thread-safe)
    ↓            ↓            ↓
        Naim Atom Device
```

### Core Components

- **`media_player.py`** (690 lines) - Main entity implementation with debounce logic
- **`client.py`** (241 lines) - HTTP API client + WebSocket client
- **`websocket.py`** (89 lines) - Low-level TCP socket wrapper
- **`config_flow.py`** (140 lines) - UI configuration flow
- **`const.py`** - Configuration constants (ports, intervals, steps)
- **`exceptions.py`** - Custom exception hierarchy

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
# Prevent feedback loops between UI actions and WebSocket updates
_last_user_volume_action: float  # 2 second window
_last_user_mute_action: float    # 2 second window
_debounce_timeout: float = 2.0   # Ignore device echo
_update_debounce_timeout: float = 1.0  # Rate limit polling
```

**Why:** When user changes volume via UI → HTTP command → device updates → WebSocket echoes change → UI would flicker. Debounce prevents this.

### Error Handling Pattern
```python
try:
    await self._api_client.set_value(...)
except aiohttp.ClientError as error:
    _LOGGER.error("Error: %s", error)
    # Revert optimistic state update
    await self._state.update(old_value)
```

### Retry Logic
```python
for retry in range(max_retries):
    try:
        return await operation()
    except Exception:
        if retry < max_retries - 1:
            await asyncio.sleep(2**retry)  # Exponential backoff
```

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
pytest tests/
```

**Test structure:**
- `test_client.py` - API client and WebSocket tests
- `test_media_player.py` - Entity behavior tests
- `test_config_flow.py` - Configuration UI tests
- `conftest.py` - Shared fixtures

**Mocking:**
- Use `aioresponses` for HTTP mocking
- Use `AsyncMock` for async methods
- Mock WebSocket connections for integration tests

## Common Tasks

### Adding a New Source

1. Update `SOURCE_TO_INPUT_MAP` in media_player.py:
```python
SOURCE_TO_INPUT_MAP = {
    "New Source": "newsource",  # Add here
    # ...
}
```

2. Add to config flow if needed (config_flow.py)

### Changing Debounce Timing

Edit constants in media_player.py:
```python
_debounce_timeout: float = 2.0  # User action ignore window
_update_debounce_timeout: float = 1.0  # Polling rate limit
```

### Adding New Device Commands

1. Add method to `NaimApiClient` in client.py
2. Add corresponding method to `NaimPlayer` entity
3. Update supported features flags if needed

## Configuration Constants

```python
DOMAIN = "naim_media_player"
DEFAULT_PORT = 4545           # WebSocket
DEFAULT_HTTP_PORT = 15081     # HTTP API
VOLUME_STEP = 0.05            # 5% default
SOCKET_RECONNECT_INTERVAL = 5  # seconds
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
├── __init__.py           # Platform setup
├── const.py              # Constants
├── exceptions.py         # Custom exceptions
├── client.py             # HTTP + WebSocket clients
├── websocket.py          # Low-level socket wrapper
├── media_player.py       # Main entity implementation
├── config_flow.py        # UI configuration
├── manifest.json         # Integration metadata
└── translations/
    └── en.json           # UI strings

tests/
├── conftest.py           # Pytest fixtures
├── test_client.py        # Client tests
├── test_media_player.py  # Entity tests
├── test_config_flow.py   # Config flow tests
└── test_websocket.py     # WebSocket tests
```

## Dependencies

**None!** This integration uses only Home Assistant's built-in `aiohttp` library.

## Version History

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
pytest tests/ -v
```

**Check code quality:**
```bash
# No linting configured yet - use your editor's Python linter
```

**Create release:**
1. Update version in `manifest.json`
2. Tag commit: `git tag v0.x.x`
3. Push: `git push origin v0.x.x`
4. HACS will auto-detect new release
