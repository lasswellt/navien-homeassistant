# Navien NaviLink Water Heater — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A custom [Home Assistant](https://www.home-assistant.io/) integration for
**Navien** tankless water heaters and boilers connected through the
**NaviLink** cloud service (AWS IoT).

> Modern rewrite scaffolded from
> [nikshriv/hass_navien_water_heater](https://github.com/nikshriv/hass_navien_water_heater),
> restructured around config entries, `runtime_data`, a connection coordinator,
> and a shared base entity.

## Supported devices

Navien residential tankless water heaters and combi-boilers that connect to the
**NaviLink** cloud service (the same account used by the NaviLink mobile app).
The `DeviceSorting` product families the protocol exposes:

| Family | Type | Notes |
|---|---|---|
| NPE / NPE2 / NPN | Tankless DHW | Primary target; on-demand recirculation on supported models |
| NCB / NCB-H | Combi (DHW + heat) | Space-heating channel present (`heatControl`) |
| NFB / NFC | Commercial combi | |
| NHB | Heating boiler | |
| NVW | Storage / hybrid | |
| CAS_* | Cascade | Multiple units behind one channel |

Validated against a live **NPE-2** (NaviLink US, `swVersion 4352`). Other
families use the same protocol; if your unit type is not recognised, a repair
issue is raised and basic controls still work — please open an issue with your
model so support can be confirmed.

**Not supported:** units without a NaviLink gateway (Wi-Fi/cloud), and the
NWP500 heat-pump water heater (different protocol — use a dedicated integration).

## Supported functions

| Platform | Entities |
|---|---|
| `water_heater` | Target temperature, away mode, operation mode (on/off), current temperature |
| `switch` | Power; on-demand (hot-button) recirculation (when the unit reports `onDemandUse`) |
| `sensor` | Hot-water / inlet temperature, hot-water flow, current + cumulative gas usage, heating power; *(diagnostic, disabled by default)* supply/return/recirculation/outdoor/tank temps, cumulative water usage, water-draw counts, filter days/status, recirculation, CIP descaling, operation/thermostat status, error + sub-error codes, controller/panel firmware, Wi-Fi signal, country code, descaling window start/end |
| `binary_sensor` | Fault (`problem`, with `error_code` / `sub_error_code` attributes); freeze protection, cloud connection *(diagnostic)* |

The integration surfaces the **full** NaviLink MQTT/API telemetry surface — the
primary readings are enabled; everything else is a disabled-by-default
diagnostic entity you can turn on per-entity. Device firmware (`sw_version`) and
MAC are set on the device record. The diagnostics download includes the complete
raw `device_info` / `device_status` / per-channel payloads with identity,
credentials, and location redacted.

Diagnostic and rarely-needed sensors are disabled by default — enable them from
the entity settings. Gas / flow / temperature use the unit's own measurement
system (°F + gal/min, or °C + L/min) and Home Assistant converts as needed.

## Requirements

- Home Assistant `2024.12.0` or newer.
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
Heater.**

### Configuration parameters (setup)

| Field | Required | Description |
|---|---|---|
| Username (email) | yes | NaviLink account email |
| Password | yes | NaviLink account password |
| Gateway | yes | Which gateway to add (one config entry per gateway) |

### Options

| Option | Default | Range | Description |
|---|---|---|---|
| Polling interval | `15` s | `10`–`120` s | How often the client requests channel status |

Use **Reconfigure** (entry menu) to update credentials, and **Configure** to
change the polling interval. Credentials that stop working trigger a
re-authentication prompt automatically.

## Data updates

The integration is **push-based**. The NaviLink client maintains an AWS-IoT
MQTT (websocket) connection and requests channel status on the configured
polling interval; each response is pushed to the `DataUpdateCoordinator`, so
entity states update without Home Assistant polling. The AWS session token
expires roughly hourly and the client reconnects automatically.

## Removal

**Settings → Devices & Services → Navien NaviLink Water Heater → ⋮ → Delete.**
The MQTT connection is closed and all entities/devices are removed. No external
cleanup is required (no data is stored on Navien's side by this integration).

## Use cases

- **Recirculation on demand:** turn on the hot-button switch from a motion
  sensor or a "good morning" routine so hot water is ready at the tap.
- **Energy tracking:** add *Cumulative gas usage* to the Energy dashboard (gas
  source) to track consumption over time.
- **Fault alerting:** notify when the *Fault* binary sensor turns on, surfacing
  the raw `error_code` for support calls.
- **Vacation mode:** put the heater in away mode when everyone leaves, restore
  it on arrival.

## Examples

Notify on a fault and include the error code:

```yaml
automation:
  - alias: "Navien fault alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.test_heater_ch1_fault
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Water heater fault"
          message: >
            Error code {{ state_attr('binary_sensor.test_heater_ch1_fault',
            'error_code') }}
```

Start recirculation when morning motion is detected:

```yaml
automation:
  - alias: "Pre-heat hot water in the morning"
    trigger:
      - platform: state
        entity_id: binary_sensor.hallway_motion
        to: "on"
    condition:
      - condition: time
        after: "05:30:00"
        before: "08:00:00"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.test_heater_ch1_hot_button
```

## Known limitations

- **Trend / schedule history is not available.** NaviLink exposes weekly
  schedule and energy-trend MQTT topics, but the request command codes are not
  reverse-engineered, so usage history is not surfaced.
- **Cloud dependency.** All data flows through Navien's AWS-IoT service; there
  is no local (LAN) control. NaviLink outages make the device unavailable.
- **Hourly reconnects.** The AWS session token has no refresh endpoint, so the
  client fully reconnects about once an hour; brief unavailability is normal.
- **Space-heating control on combi units** is read-only for now (heating
  setpoint write path is unverified).
- **Validated on one model (NPE-2).** Other families are capability-gated from
  the device's own descriptors, but field semantics may vary.

## Troubleshooting

- **"Invalid authentication" at setup** — confirm the email/password work in the
  NaviLink mobile app. The integration uses the same account.
- **Entity unavailable** — usually a transient NaviLink/AWS reconnect; it clears
  on the next status push. Persistent unavailability means the gateway is
  offline (check the unit's Wi-Fi).
- **"Unsupported Navien model" repair** — your unit type isn't recognised yet.
  Basic controls still work; open an issue with your model number.
- **Missing sensors** — diagnostic sensors are disabled by default; enable them
  from the entity's settings.
- **Diagnostics** — download from the device page (**⋮ → Download diagnostics**);
  credentials, MAC, and location are redacted, so it is safe to attach to issues.

## Architecture

```
custom_components/navien_navilink_wh/
├── __init__.py        # setup/unload, runtime_data, platform forwarding
├── coordinator.py     # DataUpdateCoordinator[NavienData]; push client → typed snapshot
├── entity.py          # NavienChannelEntity base (CoordinatorEntity, device_info, availability)
├── config_flow.py     # user + gateway steps, reauth, options flow
├── water_heater.py    # WaterHeaterEntity (primary entity) per channel
├── switch.py          # power + on-demand switches (EntityDescription + value_fn)
├── sensor.py          # temp / flow / gas / diagnostics sensors (EntityDescription)
├── binary_sensor.py   # fault (problem) + freeze-protection
├── diagnostics.py     # redacted diagnostics
├── strings.json       # config + entity translations
├── icons.json         # entity icon translations
└── navien_api.py      # NaviLink AWS IoT client (vendored; root CA via certifi)
```

Targeting Home Assistant [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) **gold** — see `docs/_research/2026-06-23_quality-scale-upgrade.md`.

## Credits

- Original integration and NaviLink protocol work by
  [@nikshriv](https://github.com/nikshriv).

## License

[MIT](LICENSE)
