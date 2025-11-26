# TODO

## Current Tasks

- [ ] Test v0.2.0 release by removing existing Naim setup from Home Assistant and reinstalling via HACS

## Bug Fixes

### Issue #3: Mute Function Not Working Properly
- [x] Already fixed in current codebase - close the issue

### Issue #4: Repeated error messages if Atom is offline
- [ ] Add `_attr_available` property tracking to `NaimPlayer`
- [ ] Set `_attr_available = False` when device is unreachable in `async_update`
- [ ] Set `_attr_available = True` when connection succeeds
- [ ] Change log level from ERROR to DEBUG/WARNING in `websocket.py:72` for connection failures
- [ ] Change log level from ERROR to DEBUG in `media_player.py:365` for expected offline states
- [ ] Add explicit timeout (5s) to HTTP requests in `async_get_current_value`

### Issue #5: Lose config after cutting power
- [ ] Clear `_buffer` on reconnection attempt in `websocket.py:_socket_listener` (add `self._buffer = ""` at start of while loop)
- [ ] Expose WebSocket `_connected` state to entity for availability tracking
- [ ] Consider adding connection-restored callback to trigger full state refresh

## Completed

- [x] Release v0.2.0 with WebSocket support and enhanced client
- [x] Release v0.1.1 with config flow UI setup
- [x] Add auto-release workflow with PR labels
- [x] Update README with new sources (Roon, HDMI) and changelog
