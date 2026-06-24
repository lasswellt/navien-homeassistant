# Navien NaviLink Water Heater — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A custom [Home Assistant](https://www.home-assistant.io/) integration for
**Navien** tankless water heaters and boilers connected through the
**NaviLink** cloud service (AWS IoT).

> Modern rewrite scaffolded from
> [nikshriv/hass_navien_water_heater](https://github.com/nikshriv/hass_navien_water_heater),
> restructured around config entries, `runtime_data`, a connection coordinator,
> and a shared base entity.

## Features

- **Water heater** entity per channel — target temperature, away mode, power.
- **Switches** — channel power and on-demand (hot-button) recirculation.
- **Sensors** — inlet / outlet temperature, hot-water flow, instant and
  cumulative gas usage, and heating power, with automatic metric ↔ imperial
  conversion.
- UI config flow with gateway selection and an options flow for the polling
  interval.
- Diagnostics download with credentials redacted.

## Requirements

- Home Assistant `2024.11.0` or newer.
- A NaviLink account (the same username/password used in the NaviLink mobile
  app).
- `AWSIoTPythonSDK` — installed automatically from the manifest.

## Installation

### HACS (recommended)

1. In HACS → **Integrations**, add this repository as a **Custom repository**
   (category: *Integration*).
2. Install **Navien NaviLink Water Heater**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/navien_navilink_wh` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → Navien NaviLink Water
Heater.** Enter your NaviLink credentials, pick the gateway, and adjust the
polling interval via the integration's **Configure** dialog (10–120 s).

## Architecture

```
custom_components/navien_navilink_wh/
├── __init__.py        # setup/unload, runtime_data, platform forwarding
├── coordinator.py     # owns the NavilinkConnect lifecycle
├── entity.py          # NavienChannelEntity base (device_info, availability, push callbacks)
├── config_flow.py     # user + gateway steps, options flow
├── water_heater.py    # WaterHeaterEntity per channel
├── switch.py          # power + on-demand switches
├── sensor.py          # temp / flow / gas / heating-power sensors
├── diagnostics.py     # redacted diagnostics
└── navien_api.py      # NaviLink AWS IoT client (vendored; root CA via certifi)
```

## Credits

- Original integration and NaviLink protocol work by
  [@nikshriv](https://github.com/nikshriv).

## License

[MIT](LICENSE)
