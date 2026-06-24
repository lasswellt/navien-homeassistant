---
scope:
  topic: navilink-api-capabilities
  source: live-probe + web-research
  date: 2026-06-23
  capabilities:
    - id: extra-telemetry-sensors
      desc: Expose unused per-unit + channel telemetry as sensor/binary_sensor/diagnostic entities
      effort: M
    - id: space-heating-channel
      desc: climate entity for combi/boiler heatSettingTemp (heatControl=1 units)
      effort: M
    - id: fault-entities
      desc: errorCode/subErrorCode → problem binary_sensor + diagnostic sensor
      effort: S
    - id: maintenance-entities
      desc: descaling window, daysFilterUsed, filterStatus, CIP descaling state
      effort: S
    - id: recirculation-sensor
      desc: currentRecirculationTemp + recirculationSettingTemp + recirculationUse capability
      effort: S
    - id: connection-stability
      desc: handle ~1h AWS session-token expiry; harden KeyError 'channel'; wifiRssi diag
      effort: M
    - id: trend-schedule-reverse-eng
      desc: reverse-engineer weeklyschedule/simple/hourly/daily/monthly trend command codes
      effort: L
      risk: high
  counts:
    rest_endpoints: 2
    mqtt_command_codes_known: 5
    telemetry_fields_total: 84
    telemetry_fields_used: 6
---

# Research: NaviLink API Capabilities — What We Can Get From the Unit

**Type:** Feature Investigation + live validation
**Date:** 2026-06-23
**Validated against:** live NaviLink account, 1 device (`unitType=11` NPE-2 tankless, `temperatureType=2` °F, `swVersion=4352`), read-only probe — no control commands issued.

## Summary

NaviLink cloud exposes **~84 distinct telemetry fields** per device (29 `channelInfo` capability flags + 21 channel-level status + 34 per-unit status + device-level). The integration's initial scope consumed **~6** of them: power, on-demand, DHW setpoint, `gasInstantUsage`, `accumulatedGasUsage`, `DHWFlowRate`, inlet/outlet temp, `avgCalorie`. Everything else — fault codes, water usage, filter/maintenance, recirculation temps, freeze protection, space-heating setpoint, firmware versions, descaling window, Wi-Fi RSSI — is fetched on every poll and discarded.

API surface is small and stable: **2 REST endpoints** (`/user/sign-in`, `/device/list`) + AWS-IoT MQTT (websocket, IAM creds from sign-in). **5 MQTT command codes** are known; **schedule + 5 trend topics are subscribed but never requested** (no request command codes reverse-engineered — they existed in the archived v1 `PyNavienSmartControl` but were never ported).

**Recommendation:** Build the integration in waves — (1) ship the current entities + a connection-stability fix, (2) expand to the unused per-unit telemetry (biggest value, zero protocol risk — data already in hand), (3) add space-heating/recirculation for combi units, (4) treat trends/schedule as a separate reverse-engineering spike (high risk, codes unknown). Live probe proves waves 1-3 need no new protocol work — only field mapping.

## Research Questions

**Q1: What REST endpoints does NaviLink v2 expose?**
Only two confirmed in every public implementation: `POST https://nlus.naviensmartcontrol.com/api/v2/user/sign-in` and `POST .../device/list`. No token-refresh, schedule, trend, or firmware REST endpoint exists. Token (`accessToken` + AWS `accessKeyId`/`secretKey`/`sessionToken`) returns from sign-in; all live data flows over MQTT. Regional hosts (EU/KR) unconfirmed — only `nlus` (US) seen.

**Q2: What MQTT command codes / schemas are known?**
Known (decimal → hex → fn): `16777217`→`0x01000001`→channelinfo; `16777220`→`0x01000004`→channelstatus; `33554433`→`0x02000001`→power; `33554435`→`0x02000003`→DHWtemp; `33554437`→`0x02000005`→onDemand. Pattern: **status reads = `0x01xxxxxx`, control writes = `0x02xxxxxx`**. Trend/schedule request codes: **unknown** (gap — see Q5).

**Q3: What other implementations exist, and what do they expose beyond the basic field set?**
`eman/ha_nwp500` (NWP500 heat-pump WH) — leak/scald/freeze alerts, Heat-Pump/Eco/High-Demand/Electric modes, `set_reservation` scheduling — **different MQTT topic structure** (per-product fragmentation). `htumanyan/navien` + `dacarson/NavienManager` — RS-485-direct (bypass cloud), field-level protocol docs but not cloud-applicable. Archived `PyNavienSmartControl` (v1, Apr 2023) — had `-schedule/-modifyschedule/-trendsample/-trendmonth/-trendyear` CLI flags.

**Q4: Known issues (rate limit, token expiry, 2FA, lockouts, regional)?**
AWS session token TTL ~1h with **no refresh endpoint** → forced full re-login/reconnect hourly. Reported breakage: `KeyError: 'channel'` on NPE2-240A2 ~every 90s (model-specific); HA 2025.5.1 break (issue #49); 90s second-entry setup (#53); 504s on setup (#22). No 2FA, no documented rate limit, no documented concurrent-session lockout found. Daily forced reconnect at 02:00 local is self-imposed by the client, not the server.

**Q5: What does the app show that maps to unit telemetry we're not using?**
Live probe confirms the unit already returns: per-unit `errorCode`/`subErrorCode`, `operationMode`, `accumulatedWaterUsage`, `numOfWaterUse`/`numOfShortWaterUse`, `daysFilterUsed`/`filterStatus`, `currentRecirculationTemp`, `freezeProtectionStatus`, `waterLevel`, `controllerVersion`/`panelVersion`, `currentDHWTankTemp`, CIP (clean-in-place / descaling) fields; channel-level `heatStatus`/`heatSettingTemp`, `avgSupplyTemp`/`avgReturnTemp`, `recirculationSettingTemp`, `outdoorTemperature`; device-level `error{errorCode,errorOccuredTime}`, `descaling{start,end}`, `wifiRssi`, `connected`, `swVersion`. Trend history (energy/usage over time) is the **only** app feature NOT obtainable without new command codes.

## Findings

### F1 — Live field inventory (primary source)
Captured raw `channelInfo` + `channelStatus` from the live unit (secrets/address redacted; full tables in Appendix A). Field counts: `channelInfo.channel` = 29; `channelStatus.channel` (channel-level) = 21; `unitStatusList[]` (per-unit) = 34. Integration currently maps 6 status fields → 9 entities (1 water_heater, 2 switch, 6 sensor incl. avgCalorie).

### F2 — High-value unused telemetry (no protocol work needed)
Already in every poll response, just needs entity mapping:
- **Faults:** `errorCode`, `subErrorCode` (live=0) → `binary_sensor` (problem) + diagnostic sensor. Device-level `error.errorOccuredTime`.
- **Water usage:** `accumulatedWaterUsage`, `numOfWaterUse`, `numOfShortWaterUse` → `TOTAL_INCREASING` sensors.
- **Maintenance:** `daysFilterUsed`, `filterStatus`, `descaling.descalingStartTime`/`EndTime` (live: 2026-06-01 → 2027-06-01), CIP fields (`CIPStatus`, `CIPSolutionRemained`, `CIPOperationTimeHour/Min`).
- **Recirculation:** `currentRecirculationTemp`, `recirculationSettingTemp`, capability `recirculationUse` / `highTempDHWUse`.
- **Thermal detail:** `avgSupplyTemp`/`avgReturnTemp`, `currentSupplyTemp`/`currentReturnTemp`, `outdoorTemperature`, `currentDHWTankTemp`.
- **Diagnostics:** `swVersion`, `controllerVersion`, `panelVersion`, `wifiRssi`, `connected`, `freezeProtectionStatus`, `operationMode`.

### F3 — Space heating is a distinct, unmodeled capability
`channelInfo` carries `heatControl=1`, `setupHeatTempMin/Max`, and status carries `heatStatus`, `heatSettingTemp`. On combi units (`NCB`, `NCB_H`, `NFB`, `NFC`, `NHB`) this is a second controllable loop → warrants a `climate` entity. (Live NPE-2 is DHW-only: `heatSettingTemp=0`, `setupHeatTempMin=Max=32` placeholder.) Capability-gate entity creation on `heatControl`/`setupHeatTempMax>setupHeatTempMin`.

### F4 — Field scaling is unitType- and temperatureType-dependent
Confirmed in `convert_channel_status`: Celsius mode divides temps & setpoint by 2.0; `avgCalorie`÷2.0→%; `gasInstantUsage` GIUFactor = 100 for `NFC/NCB_H/NFB/NVW` else 10; `accumulatedGasUsage`÷10; `DHWFlowRate`÷10. Fahrenheit mode applies different factors (gas ×3.968, accumulated ×35.314667/10, flow ÷37.85). **Any new gas/flow/temp sensor must route through the same per-unitType scaling** — raw values are not directly usable.

### F5 — Trend/schedule: subscribed, never requested (confirmed gap)
`weeklyschedule`, `simpletrend`, `hourlytrend`, `dailytrend`, `monthlytrend` have `_sub`/`_res`/`_req` topic builders, but handlers are **log-only stubs** and there are **no `Messages` request methods and no command codes**. Live probe with `subscribe_all_topics=True` received **zero** trend/schedule pushes in ~20s — these are pull-only and require a request publish we cannot construct yet. v1 `PyNavienSmartControl` had the feature → codes exist historically, never ported to the v2 MQTT shape.

### F5.1 — Live MQTT listen (2026-06-24): weekly schedule reachable, trends still dark
Wildcard-subscribed (`req+#`, `res+#`, `cmd/{deviceType}/{homeSeq}/#`) and fired best-effort request publishes (channel_status envelope) at the trend/schedule `status/*` topics with candidate command codes `16777222`–`16777226` (`0x01000006`–`0x0100000A`). Results (320 msgs, ~75s):
- **Weekly schedule IS requestable.** Those codes returned a `weeklySchedule` object on `res/weeklyschedule` + `res/simpletrend`. Schema: `response.weeklySchedule.channel = { weeklyControl, totalDayCount, weeklySchdList[] }`. On the live unit it is **empty** — `weeklyControl=2` (schedule off), `weeklySchdList: []`, `totalDayCount=0`. So the topic is reachable; nothing to surface until a schedule is configured.
- **Energy trends still return no data.** Every response to the `simpletrend`/`hourlytrend`/`dailytrend`/`monthlytrend` requests carried the `weeklySchedule` shape, never a trend array (no `gasUsage`/history keys anywhere in the capture). The trend command codes are still unknown — needs a NaviLink-app packet capture.
- **Concurrent sessions coexist (resolves prior open question).** Observed `channelStatus` from two *other* client IDs on the same account (the mobile app) alongside this session — no lockout, no forced disconnect.
- **Retained messages:** 262 `weeklySchedule` deliveries from 25 publishes → the broker retains + redelivers schedule/trend responses on (re)subscribe.

### F6 — `additionalValue` opaque token
Present in every request payload (`request.additionalValue`), sourced from `device/list` `deviceInfo.additionalValue`. Purpose undocumented in all sources; must be echoed verbatim — treat as opaque.

## Dissent / Contradictory Evidence
- Field **meaning** for several keys is single-source / inferred, not cross-confirmed: `avgCalorie` as "heating %" (live=0 on an idle DHW unit is consistent but not proof), `currentOutputTDSValue`, `waterLevel`, `PoEStatus`, `thermostatStatus`. Treat units/labels as provisional until observed under load.
- `operationMode` enum values undocumented; live=0 (idle). Do not hardcode a mapping yet.
- Web research claims NWP500 has richer modes — but that is a *different product family with a different topic tree*; do not assume tankless gains those by analogy.

## Compatibility Analysis

- **Stack:** HACS custom integration, HA `2024.11.0`+ floor, single Python package, `requirements: AWSIoTPythonSDK>=1.5.4`. Root CA via `certifi` (already wired in `coordinator.py`).
- **Live validation:** a venv reproduced full login → MQTT → channelinfo/channelstatus against production. The NaviLink client works against the live account.
- **No new dependencies** required for waves 1-3 (all data already parsed into `channel.channel_status`).
- **Integration today** uses the legacy push-callback model (entities register on `channel`); coordinator owns lifecycle. New entities slot into the existing `NavienChannelEntity` base with zero protocol changes — only new `@property` reads + `async_setup_entry` rows.

## Recommendation

Build in dependency-ordered waves:

| Wave | Scope | Protocol risk | Value |
|---|---|---|---|
| 1 | Current entities + connection-stability fix (token expiry, `KeyError: 'channel'` guard) | none | correctness |
| 2 | Map unused per-unit/channel telemetry → sensors/binary_sensors/diagnostics (F2) | none (data in hand) | **highest** |
| 3 | `climate` for combi heating (F3) + recirculation entities, capability-gated | none | high (combi owners) |
| 4 | Trend/schedule reverse-engineering spike (F5) | **high** (unknown codes) | medium |

Wave 2 is the core answer to "everything we can get from the unit" and is pure HA-side work. Wave 4 is research, not implementation — scope it separately; do not block the integration on it.

## Implementation Sketch

- **New entities** extend existing `custom_components/navien_navilink_wh/entity.py:NavienChannelEntity`. Per-unit sensors follow the existing `sensor.py:NavienUnitSensor` pattern (iterate `unitInfo.unitStatusList`).
- **binary_sensor.py** (new platform): `errorCode != 0` → `BinarySensorDeviceClass.PROBLEM`; `freezeProtectionStatus`, `filterStatus`. Add `Platform.BINARY_SENSOR` to `__init__.py:PLATFORMS`.
- **Diagnostic sensors:** `EntityCategory.DIAGNOSTIC` for `swVersion`, `controllerVersion`, `panelVersion`, `wifiRssi`, `daysFilterUsed`, `connected`.
- **climate.py** (new, wave 3): gate on `channel_info.heatControl == 1`; target temp via a new `messages.temperature`-style control with `mode="heatTemperature"` (**code unverified — needs validation before write path; read-only `heatSettingTemp`/`heatStatus` first**).
- **Scaling:** reuse `sensor.py:get_description` conversion approach; extend for water-usage (`accumulatedWaterUsage`) and supply/return temps. Do not bypass per-`unitType` factors (F4).
- **Connection stability (wave 1):** wrap `convert_channel_status` access in `.get()` guards (the `KeyError: 'channel'` is a hard `channel_status["powerStatus"]` index); add a re-login path on AWS-session-token expiry instead of relying on the 02:00 daily reconnect.
- **Probe harness:** `scratchpad/probe.py` is a reusable read-only field-discovery tool (redacts secrets) — keep for validating new models. Do **not** commit it (contains creds path + writes raw payloads with home address).

## Risks

- **Trend/schedule codes are unknown and may not be recoverable** without a man-in-the-middle capture of the NaviLink Android app's MQTT traffic. Treat wave 4 as time-boxed research with an explicit "abandon if no codes in N hours" exit. Do not promise trend history to users.
- **Write paths for heating/recirculation are unvalidated.** The `power`/`DHWTemperature`/`onDemand` control codes are confirmed by live use; a `heatTemperature` mode is inferred, not observed. Any new control command must be validated on a real combi unit before shipping — a wrong `command` code could be rejected (`controlfail` topic) or, worst case, mis-set a parameter. Ship read-only first.
- **Field semantics are partly provisional** (F-Dissent). Mislabeling a diagnostic sensor is low-harm and reversible; gate user-facing energy/usage sensors on observed-under-load validation to avoid wrong dashboards.
- **AWS session-token expiry (~1h)** makes long-lived connections fragile; without a refresh fix, every wave inherits the reconnect churn. Address in wave 1 or accept hourly blips.
- **Single-device validation.** All live data is from one NPE-2 (°F, DHW-only, single channel). Multi-channel, cascade (`CAS_*`), combi, and Celsius units are unverified — capability-gate everything on `channelInfo` flags rather than assuming this unit's shape.

## Open Questions

1. Exact `operationMode` enum and `heatStatus`/`thermostatStatus`/`filterStatus` value maps — need observation under varying unit states.
2. `heatTemperature` (or equivalent) control command code for combi space-heating setpoint — unverified.
3. ~~Trend/schedule request command codes~~ — **partially resolved (F5.1):** weekly-schedule reachable via codes `16777222`–`16777226`; **energy-trend** codes still unknown (responses returned schedule, not trend data) — needs NaviLink-app packet capture.
4. Whether EU/KR accounts use a different REST host / topic tree.
5. `additionalValue` semantics and whether it can change mid-session.
6. Weekly-schedule write/edit codes + populated `weeklySchdList[]` entry shape (live unit had schedule disabled, so the list was empty).

## References

- Live read-only probe, 2026-06-23 — `scratchpad/probe-raw-channel-info.json`, `probe-raw-channel-status.json` (primary source; not committed).
- Live MQTT wildcard listen, 2026-06-24 — `scratchpad/mqtt-capture.json` (320 msgs; weekly-schedule schema + concurrent-session evidence; redacted, not committed).
- `nikshriv/hass_navien_water_heater` — https://github.com/nikshriv/hass_navien_water_heater (prior NaviLink protocol work).
- `eman/ha_nwp500` — https://github.com/eman/ha_nwp500 (NWP500 heat-pump WH; richer modes, different topics).
- `htumanyan/navien` — https://github.com/htumanyan/navien (RS-485 ESPHome; field-level `/doc/`).
- `dacarson/NavienManager` — https://github.com/dacarson/NavienManager (RS-485 HomeKit).
- `PyNavienSmartControl` (archived) — v1 schedule/trend CLI flags, never ported to v2.
- NaviLink endpoints: REST `https://nlus.naviensmartcontrol.com/api/v2`; MQTT `a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com:443` (websocket/IAM), MQTT username `?SDK=Android&Version=2.16.12`.
- Issue references (nikshriv repo): #22 (504 setup), #49 (HA 2025.5.1 break), #53 (90s second-entry setup).

## Appendix A — Live field inventory (redacted)

**`channelInfo.channel` (29) — capability descriptor:** `unitType=11, unitCount=1, temperatureType=2, setupDHWTempMin=97, setupDHWTempMax=185, setupHeatTempMin=32, setupHeatTempMax=32, onDemandUse=2, heatControl=1, wwsd=2, commercialLock=2, recirculationUse=2, highTempDHWUse=1, reCirculationSetupTempMin=32, reCirculationSetupTempMax=32, panelDipSwitchInfo=0, mainDipSwitchInfo=8192, presumeHeatTempUse=2, airSupplyReturnType=0, setupDHWTankTempMin=0, setupDHWTankTempMax=0, setupAirTempMin=0, setupAirTempMax=0, setupFanAirFlowMin=0, setupFanAirFlowMax=0, freezeProtectionUse=0, DHWTankSensorUse=2, DHWUse=2, DHWTankUse=2`

**`channelStatus.channel` channel-level (21):** `channelNumber=1, unitCount=1, unitType=11, operationUnitCount=0, weeklyControl=2, totalDayCount=0, avgCalorie=0, heatSettingTemp=0, powerStatus=1, heatStatus=2, onDemandUseFlag=2, avgOutletTemp=87, avgInletTemp=83, avgSupplyTemp=32, avgReturnTemp=32, recirculationSettingTemp=0, outdoorTemperature=0, airSettingTemp=0, fanSettingAirFlow=0, DHWSettingTemp=120, DHWTankSettingTemp=0`

**`unitStatusList[0]` per-unit (34):** `unitNumber=1, controllerVersion=3079, panelVersion=6912, errorCode=0, subErrorCode=0, operationMode=0, gasInstantUsage=0, accumulatedGasUsage=33, currentOutletTemp=87, currentInletTemp=83, currentSupplyTemp=32, currentReturnTemp=32, currentRecirculationTemp=0, currentSupplyAirTemp=0, currentReturnAirTemp=0, currentHeatFlowRate=0, blowerCFM=0, waterLevel=0, thermostatStatus=0, currentOutputTDSValue=0, accumulatedWaterUsage=0, daysFilterUsed=0, filterStatus=0, numOfWaterUse=0, numOfShortWaterUse=0, currentDHWTankTemp=0, freezeProtectionStatus=0, DHWFlowRate=0, PoEStatus=0, CIPSolutionRemained=0, CIPStatus=0, CIPOperationTimeHour=0, CIPOperationTimeMin=0, CIPSolutionSupplement=0`

**Device-level:** `deviceType=1, swVersion=4352, wifiRssi=0, countryCode=1, connected=2, error{errorCode=null, errorOccuredTime=null}, descaling{descalingStartTime=2026-06-01T00:00:00, descalingEndTime=2027-06-01T00:00:00}`

**MQTT topic tree (observed):** req prefix `cmd/1/navilink-<mac>/` → `status/start`, `status/channelstatus`, `status/channelinfo`, `control`, `res/*`; trend/schedule `status/{weekly,simple,hourly,daily,monthly}*` (builders exist, codes unknown).
