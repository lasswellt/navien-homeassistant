# Navien NaviLink Water Heater — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Quality Scale](https://img.shields.io/badge/Quality%20Scale-Gold-FFD700.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)

A custom [Home Assistant](https://www.home-assistant.io/) integration for
**Navien** tankless water heaters and combi-boilers connected through the
**NaviLink** cloud service (AWS IoT).

It ships its own self-contained, asyncio-native NaviLink client — REST
authentication, AWS SigV4 WebSocket signing, and an MQTT transport — with **no
third-party AWS SDK**. The integration surfaces the full NaviLink telemetry
surface, sensibly categorised and capability-gated so each device shows only
what it actually supports.

## Highlights

- **Water heater control** — target temperature, away mode, power, per channel.
- **Switches** — channel power and on-demand (hot-button) recirculation.
- **Full telemetry** — temperatures, flow, gas, heating power as primary
  sensors; combi/tank/recirculation/air sensors created only on units that have
  them; firmware, status/error codes, descaling, Wi-Fi signal, and connectivity
  as diagnostics.
- **UI setup** — config flow with gateway selection, re-authentication,
  reconfiguration, and a polling-interval options flow.
- **Robust** — typed `DataUpdateCoordinator`, automatic reconnect on token
  expiry, a repair issue for unrecognised models, and a redacted diagnostics
  download.
- **Native client** — no `AWSIoTPythonSDK`/`boto3`; `paho-mqtt` driven on the
  event loop with no background network thread.

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
issue is raised and basic controls still work — please
[open an issue](https://github.com/lasswellt/navien-homeassistant/issues) with
your model so support can be confirmed.

**Not supported:** units without a NaviLink gateway (Wi-Fi/cloud), and the
NWP500 heat-pump water heater (different protocol — use a dedicated integration).

## Requirements

- Home Assistant `2024.12.0` or newer.
- A NaviLink account (the same username/password used in the NaviLink mobile app).
- `paho-mqtt` — installed automatically from the manifest (Home Assistant
  already bundles it).

## Installation

### HACS (recommended)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**, add
   `https://github.com/lasswellt/navien-homeassistant` (category: *Integration*).
2. Install **Navien NaviLink Water Heater**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/navien_navilink_wh` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → Navien NaviLink Water
Heater.**

### Setup parameters

| Field | Required | Description |
|---|---|---|
| Username (email) | yes | NaviLink account email |
| Password | yes | NaviLink account password |
| Gateway | yes | Which gateway to add (one config entry per gateway) |

### Options

| Option | Default | Range | Description |
|---|---|---|---|
| Polling interval | `15` s | `10`–`120` s | How often the client requests channel status |

Use **Reconfigure** (entry menu) to update credentials or re-pick the gateway,
and **Configure** to change the polling interval. Credentials that stop working
trigger a re-authentication prompt automatically.

## Entities

| Platform | Entities |
|---|---|
| `water_heater` | Target temperature, away mode, operation mode (on/off), current temperature |
| `switch` | Power; on-demand (hot-button) recirculation (when the unit reports `onDemandUse`) |
| `sensor` — primary *(enabled)* | Hot-water + inlet temperature, hot-water flow, current + cumulative gas usage, heating power |
| `sensor` — capability-gated | Created only on units that report the feature, then enabled: recirculation temp (recirc/on-demand units); supply/return/heating-setpoint temps + heating flow (combi); tank temp (storage units); supply/return air temps (air units) |
| `sensor` — diagnostic | Wi-Fi signal + descaling window start/end *(enabled)*; firmware versions, error + sub-error codes, operation/thermostat/filter/PoE status, water-draw counts, CIP descaling internals, country code *(disabled by default)* |
| `binary_sensor` | Fault (`problem`, with `error_code` / `sub_error_code` attributes); freeze protection, cloud connection *(diagnostic)* |

The integration surfaces the **full** NaviLink MQTT/API telemetry surface.
Temperatures, flow, and gas/water are real measurements (not lumped under
diagnostics); feature-specific sensors are created only on units that support
them, so a DHW-only heater isn't cluttered with placeholder heating/tank
entities. Technical/status fields are diagnostic and mostly disabled by default
— enable any of them from the entity settings. Gas / flow / temperature use the
unit's own measurement system (°F + gal/min, or °C + L/min) and Home Assistant
converts as needed. Device firmware (`sw_version`) and MAC are set on the device
record.

## How it works

The integration is connection-oriented. On setup it signs in over REST, opens an
AWS-IoT MQTT-over-WebSocket connection, discovers channels, and then requests
channel status on the configured polling interval. Each response is pushed into
a typed `DataUpdateCoordinator` snapshot, so entity states update from the live
connection rather than Home Assistant polling each entity.

The AWS session token has no refresh endpoint and expires roughly hourly; the
client reconnects automatically, so brief unavailability around the reconnect is
normal.

## Automations

> Entity IDs are derived from your device name (e.g. a gateway named *Tankless*
> yields `water_heater.tankless_ch1`). Adjust the IDs below to match yours.

Notify on a fault and include the error code:

```yaml
automation:
  - alias: "Navien fault alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.tankless_ch1_fault
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Water heater fault"
          message: >
            Error code {{ state_attr('binary_sensor.tankless_ch1_fault',
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
          entity_id: switch.tankless_ch1_hot_button
```

Common use cases: recirculation on demand from presence/routines, adding
*Cumulative gas usage* to the Energy dashboard, fault notifications, and away
mode for vacations.

## Known limitations

- **Trend / schedule history is not available.** NaviLink exposes weekly-schedule
  and energy-trend MQTT topics; the weekly-schedule topic is reachable but the
  energy-trend request command codes are not yet known, so usage history is not
  surfaced.
- **Cloud dependency.** All data flows through Navien's AWS-IoT service; there is
  no local (LAN) control. NaviLink outages make the device unavailable.
- **Hourly reconnects.** The AWS session token has no refresh endpoint, so the
  client fully reconnects about once an hour; brief unavailability is normal.
- **Space-heating control on combi units** is read-only for now (the heating
  setpoint write path is unverified).
- **Validated on one model (NPE-2).** Other families are capability-gated from
  the device's own descriptors, but field semantics may vary.

## Troubleshooting

- **"Invalid authentication" at setup** — confirm the email/password work in the
  NaviLink mobile app. The integration uses the same account.
- **Entity unavailable** — usually a transient NaviLink/AWS reconnect; it clears
  on the next status push. Persistent unavailability means the gateway is offline
  (check the unit's Wi-Fi).
- **"Unsupported Navien model" repair** — your unit type isn't recognised yet.
  Basic controls still work; open an issue with your model number.
- **Missing sensors** — diagnostic and feature-specific sensors are disabled or
  not created by default; enable them from the entity settings.
- **Diagnostics** — download from the device page (**⋮ → Download diagnostics**);
  credentials, MAC, and location are redacted, so it is safe to attach to issues.

## Removal

**Settings → Devices & Services → Navien NaviLink Water Heater → ⋮ → Delete.**
The MQTT connection is closed and all entities/devices are removed. No external
cleanup is required.

## Architecture

```
custom_components/navien_navilink_wh/
├── __init__.py        # setup/unload, runtime_data, platform forwarding
├── coordinator.py     # DataUpdateCoordinator[NavienData]; push client → typed snapshot
├── entity.py          # NavienChannelEntity base (CoordinatorEntity, device_info, availability)
├── config_flow.py     # user + gateway steps, reauth, reconfigure, options flow
├── water_heater.py    # WaterHeaterEntity (primary entity) per channel
├── switch.py          # power + on-demand switches (EntityDescription + value_fn)
├── sensor.py          # temps / flow / gas / diagnostics (capability-gated EntityDescription)
├── binary_sensor.py   # fault (problem), freeze-protection, cloud connection
├── diagnostics.py     # redacted diagnostics
├── strings.json       # config + entity translations
├── icons.json         # entity icon translations
├── quality_scale.yaml # Integration Quality Scale self-assessment
└── navilink/          # native NaviLink client (no third-party AWS SDK)
    ├── sigv4.py        #   AWS SigV4 presigned-URL signing (stdlib only)
    ├── auth.py         #   REST sign-in + device list (injected aiohttp session)
    ├── protocol.py     #   topics, command codes, message envelopes
    ├── models.py       #   enums, exceptions, value scaling
    ├── transport.py    #   MQTT-over-WebSocket via paho on an asyncio socket-pump
    └── client.py       #   orchestration: channels, control, push updates, reconnect
```

The `navilink/` package is a self-contained, asyncio-native client: it signs the
AWS-IoT WebSocket URL itself (`sigv4.py`, stdlib only) and drives `paho-mqtt` on
the event loop via an `add_reader`/`add_writer` socket-pump with no background
network thread. REST uses Home Assistant's shared aiohttp session
(`async_get_clientsession`).

## Quality

Targets the Home Assistant
[Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
**gold** tier; the platinum `async-dependency` and `inject-websession` rules are
also met (see `quality_scale.yaml`). `strict-typing`'s formal rule is core-only,
but the `navilink/` package ships `py.typed` and is fully typed.

## Development

```bash
pip install -r requirements_test.txt
pytest tests/                 # 45 tests
pytest tests/ --cov           # ~96% coverage
```

Tests use `pytest-homeassistant-custom-component` with a mocked NaviLink client;
`tests/test_navilink.py` unit-tests the native client (SigV4, scaling, protocol,
auth, message handling). The MQTT transport is validated end-to-end against the
live broker rather than in unit tests.

Background and field-level findings live in
[`docs/_research/`](docs/_research/).

## Credits

- Original integration and NaviLink protocol work by
  [@nikshriv](https://github.com/nikshriv).

## License

[MIT](LICENSE)
