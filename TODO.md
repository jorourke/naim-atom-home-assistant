# TODO

## Current Tasks

- [ ] Test v0.2.0 release without breaking existing setup (see Testing Strategy below)
- [ ] Clean up orphaned "jatom" entities (jatom 3-218) from previous test runs

## Testing Strategy

**Option 1: Docker Test Instance (Recommended)**
```bash
docker run -d \
  --name homeassistant-test \
  -p 8124:8123 \
  -v /path/to/test-config:/config \
  homeassistant/home-assistant:latest
```
Then install dev integration into `/path/to/test-config/custom_components/`.

**Option 2: Home Assistant Dev Container**
Mount this repo directly into HA dev container and test there.

**Option 3: Add as Second Instance**
Keep existing working integration, add another config entry pointing to same device IP with different name. Both entities control the same device - if new one breaks, old one still works.

## Bug Fixes

### Issue #3: Mute Function Not Working Properly
- [x] Already fixed in current codebase - close the issue

### Issue #4: Repeated error messages if Atom is offline
- [x] Add `_attr_available` property tracking to `NaimPlayer`
- [x] Set `_attr_available = False` when device is unreachable in `async_update`
- [x] Set `_attr_available = True` when connection succeeds
- [x] Change log level from ERROR to DEBUG/WARNING in `websocket.py:72` for connection failures
- [x] Change log level from ERROR to DEBUG in `media_player.py:365` for expected offline states
- [x] Add explicit timeout (5s) to HTTP requests in `async_get_current_value`

### Issue #5: Lose config after cutting power
- [ ] Clear `_buffer` on reconnection attempt in `websocket.py:_socket_listener` (add `self._buffer = ""` at start of while loop)
- [ ] Expose WebSocket `_connected` state to entity for availability tracking
- [ ] Consider adding connection-restored callback to trigger full state refresh

## Completed

- [x] Release v0.2.0 with WebSocket support and enhanced client
- [x] Release v0.1.1 with config flow UI setup
- [x] Add auto-release workflow with PR labels
- [x] Update README with new sources (Roon, HDMI) and changelog
