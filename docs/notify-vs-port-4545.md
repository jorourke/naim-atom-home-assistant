# Spike: `GET :15081/notify` vs the port 4545 socket (issue #44)

Captured on 2026-11-19 from a live Naim Atom (firmware app 3.13.0.5828, `hardwareType` stream800)
using a raw socket reader and `curl -N`. Both streams were open at the same time.

## Decision

**Keep port 4545 for now. Switch later, when one of the triggers below happens.**
The integration still polls HTTP every 3 seconds for power, source, volume and the restrict flags,
so `/notify` would not remove the poll today. It would only make that poll faster to react.

## What each channel sends

| | Port 4545 socket | `GET /notify` (HTTP, `text/event-stream`) |
|---|---|---|
| Framing | Concatenated JSON objects, no event names | `id:` / `event:` / `data:` lines, one JSON object per event |
| Size | Full snapshot every time, about 3 to 5 KB (118 KB in 8 s on a radio stream) | Small deltas, about 100 to 250 bytes |
| Now playing | Title, artist, album, artwork, duration, `playTime.i64_` (ms) | Only changed keys, for example `{"transportPosition":"178013"}`. An `event:nowplaying` with no `parameters` means "changed, fetch it" |
| Transport | `data.state`: `playing`, `paused`, `stopped`, `transitioning` | `transportState` (`2` playing, `3` paused, `1` stopped) and `command/transport/state` |
| Volume | `senderVolume.i32_` (it read 50 while `/levels/room` said 60, so it is not the room volume) | `levels/room` and `levels` events with `{"volume":"61"}` |
| Power | None | `event:power`, for example `{"state":"lona"}` |
| Restrict flags | `data.controls` (`next_: true` on radio while HTTP said `restrictSkipNext: 128`, so they disagree) | `restrictPause`, `restrictResume` deltas, same values as HTTP |
| Other | | `userinterface` (`lightActive`), `system/status` temperatures, empty keep-alives (`ussi:""`, `id:0`) |

## Behaviour across standby and reconnect

- **Standby, 4545:** the socket stayed open. It kept sending snapshots with `state: stopped` and no
  title. There was no power message. On wake it sent `transitioning` then `playing` about 3 seconds later.
- **Standby, `/notify`:** the stream stayed open. It sent `event:power` twice (a bare one, then
  `{"state":"lona"}`), a `transport/state` of `1`, then cleared metadata fields (`albumName:""`,
  `bitRate:"0"`). On wake it sent `system/status` and `userinterface` events.
- **Reconnect:** `/notify` event ids count up (`id:512441`, `512442`, ...). I did not test
  `Last-Event-ID` resume or a forced reconnect, so replay after a drop is unknown. Port 4545 has no ids,
  so a reconnect always needs a full poll, which the client already does.

## Why not switch now

1. `/notify` carries deltas without metadata. A switch needs "event, then refetch `/nowplaying`", which is a
   new listener design and not a small change.
2. Both channels would still disagree in places (restrict flags). The poll already owns those fields.
3. Nothing is broken with 4545 today.

## Revisit when

- Firmware stops serving port 4545, or
- Power or volume changes made outside HA must show in under 3 seconds without polling faster, or
- The 3 second poll becomes a problem for the device or the network.

A switch would use `/notify` for power, volume, transport and restrict flags, refetch `/nowplaying` on
`event:nowplaying` without parameters, and keep one HTTP poll as the safety net.
