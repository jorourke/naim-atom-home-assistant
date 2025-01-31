# Naim Media Player - Home Assistant Integration

A Home Assistant custom component to control Naim audio devices (like the Naim Atom) over your local network. This integration provides full control of your Naim device including playback, volume, source selection, and real-time status updates via WebSocket connection.

## Features

### Playback Controls

- 🎵 Full playback controls (play, pause, next/previous track)
- ⏱️ Media position and duration tracking
- 🔊 Volume control with 5% increments
- 🔇 Mute functionality

### Source Management

- 📻 Source selection:
  - Analog 1
  - Digital 1-3
  - Bluetooth
  - Web Radio
  - Spotify

### Media Information

- 🖼️ Album art display
- 🏷️ Rich metadata display:
  - Track title
  - Artist name
  - Album name
  - Duration
  - Current position

### Connectivity

- 📊 Real-time status updates via WebSocket
- 🔌 Local network control (no cloud dependency)

## Installation

### Method 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Custom Repositories"
3. Add this repository URL with category "Integration"
4. Click "Install"

### Method 2: Manual Installation

1. Copy the `custom_components/naim_media_player` directory to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

Follow the config flow when you add it by navigating to the integrations page in Home Assistant, then search for "Naim Media Player", then enter the IP address of your Naim device, the name you choose and an optional entity name.

## Supported Devices

### Fully Tested

- Naim Atom

### Should Work (Untested)

- Naim Streamers that have http api support

Please report your experience with other Naim devices to help expand this list.

## Available Sources

- Analog 1
- Digital 1
- Digital 2
- Digital 3
- Bluetooth
- Web Radio
- Spotify

## Example UI

<img src="images/media_player.png" width="400">

## Debugging

If you're experiencing issues, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.naim_media_player: debug
```
