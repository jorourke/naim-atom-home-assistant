# Naim Media Player Integration

Control your Naim audio device locally through Home Assistant with real-time updates and full media player functionality.

{% if installed %}
## Thank you for installing!

Remember to restart Home Assistant after installation.
{% endif %}

## Features

- **Full Playback Control** - Play, pause, next/previous track, seek
- **Volume & Mute** - Smooth volume control with configurable step size
- **Dynamic Source Discovery** - Automatically detects available inputs from your device
- **Customizable Sources** - Choose which inputs appear in Home Assistant
- **Real-time Updates** - WebSocket connection for instant status changes
- **Rich Media Info** - Artist, title, album, and album art display
- **Local Control** - No cloud dependency, works entirely on your network

## Setup

1. Go to **Settings** → **Devices & Services**
2. Click **+ ADD INTEGRATION** and search for "Naim Media Player"
3. Enter your device's IP address
4. Select which input sources to show
5. Done! Your Naim device appears as a media player entity

## Reconfigure Sources

Changed your setup? Go to the integration and click **Configure** to update which sources are visible.

## Supported Devices

- **Naim Atom** (fully tested)
- Other Naim streamers with HTTP API support (please report your experience!)

## Issues?

If you're experiencing issues, please [report them on GitHub](https://github.com/jorourke/naim-atom-home-assistant/issues).
