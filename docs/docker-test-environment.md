# Docker-based Home Assistant Test Environment

## Overview

This guide describes how to set up a reproducible Docker-based Home Assistant test environment that:
- Runs separately from production Home Assistant
- Automatically mounts the development integration
- Can reach the real Naim device on the local network
- Can be started/stopped easily for testing
- Persists configuration between restarts

## Files to Create

### 1. `docker-compose.test.yml`

```yaml
services:
  homeassistant:
    container_name: homeassistant-test
    image: homeassistant/home-assistant:latest
    network_mode: host  # Required to reach Naim device on local network
    volumes:
      - ./test-ha-config:/config
      - ./custom_components:/config/custom_components
    environment:
      - TZ=Australia/Sydney  # Adjust to your timezone
    restart: unless-stopped
```

**Note:** Using `network_mode: host` means HA will be on port 8123 (same as production). Either run when production is stopped, or configure a different port via HA config.

### 2. `test-ha-config/configuration.yaml`

```yaml
homeassistant:
  name: HA Test
  unit_system: metric

logger:
  default: info
  logs:
    custom_components.naim_media_player: debug

# Minimal config - no other integrations
```

### 3. `.gitignore` additions

```
# Test HA config - ignore state files but keep configuration.yaml
test-ha-config/*
!test-ha-config/configuration.yaml
```

## Usage Workflow

1. **Stop production HA** if running on same port (or configure different port)

2. **Start test environment:**
   ```bash
   docker compose -f docker-compose.test.yml up -d
   ```

3. **Access test HA** at http://localhost:8123

4. **Complete initial onboarding** (create test user) - only needed first time

5. **Add the Naim integration** via Settings → Integrations → Add Integration

6. **Test changes** - restart container to pick up code changes:
   ```bash
   docker compose -f docker-compose.test.yml restart
   ```

7. **View logs:**
   ```bash
   docker compose -f docker-compose.test.yml logs -f
   ```

8. **Stop when done:**
   ```bash
   docker compose -f docker-compose.test.yml down
   ```

## Network Considerations

- `network_mode: host` gives container direct access to host network
- Container can reach Naim device at its IP (e.g., 192.168.x.x)
- WebSocket (port 4545) and HTTP API (port 15081) will both work
- No port mapping needed - container uses host's network stack directly

## Quick Reference Commands

| Action | Command |
|--------|---------|
| Start | `docker compose -f docker-compose.test.yml up -d` |
| Stop | `docker compose -f docker-compose.test.yml down` |
| Restart | `docker compose -f docker-compose.test.yml restart` |
| Logs | `docker compose -f docker-compose.test.yml logs -f` |
| Shell | `docker compose -f docker-compose.test.yml exec homeassistant bash` |
