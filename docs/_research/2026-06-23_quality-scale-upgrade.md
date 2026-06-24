---
scope:
  topic: quality-scale-upgrade
  source: HA-IQS-rules + core-WH-patterns + self-audit
  date: 2026-06-23
  target_tier: gold
  capabilities:
    - id: entity-description-refactor
      desc: migrate sensor/switch/water_heater to frozen EntityDescription + value_fn; add binary_sensor platform
      effort: M
    - id: entity-translations
      desc: translation_key + strings.json entity.* + icons.json for all entities
      effort: M
    - id: entity-category-device-class
      desc: EntityCategory.DIAGNOSTIC + device_class + entity_registry_enabled_default on all non-primary entities
      effort: S
    - id: coordinator-migration
      desc: wrap push client in DataUpdateCoordinator[NavienData]; typed runtime_data
      effort: M
    - id: silver-completion
      desc: PARALLEL_UPDATES, log-when-unavailable once, docs params
      effort: S
    - id: gold-flows
      desc: reconfigure-flow, repair-issues (token-expiry / unsupported-model), exception-translations
      effort: M
    - id: test-suite
      desc: pytest-homeassistant-custom-component; >95% coverage; 100% config-flow branches; snapshot_platform
      effort: L
    - id: docs-gold
      desc: 11 docs-* rules (data-update, supported-devices/functions, troubleshooting, examples, use-cases, limitations)
      effort: M
    - id: platinum-transport-rewrite
      desc: replace blocking AWSIoTPythonSDK with async MQTT (aiomqtt + SigV4 ws) to satisfy async-dependency
      effort: XL
      risk: high
  counts:
    quality_rules_total: 52
    rules_done_now: 16
    rules_todo_for_gold: 28
    new_platforms: 1
---

# Quality-Scale Upgrade Plan — Navien NaviLink → Gold

**Type:** Architecture Decision + self-audit
**Date:** 2026-06-23
**Inputs:** HA Integration Quality Scale rule set (52 rules, hassfest `quality_scale.py ALL_RULES`); core WH integration patterns (`incomfort` platinum, `sensibo`/`econet` gold); audit of current `custom_components/navien_navilink_wh/`.

## Summary

Current integration sits at solid **bronze**, ~80% of **silver**. Target **gold** (21 rules) is fully attainable and is the right bar — it's the "legit" line for a polished cloud integration. **Platinum is blocked** by one rule: `async-dependency` forbids executor workarounds "no exceptions," but the vendored `navien_api.py` drives the blocking `AWSIoTPythonSDK` via `run_in_executor`. Platinum therefore requires replacing the MQTT transport with a native-async client (`aiomqtt` + manual AWS-IoT SigV4 websocket auth) — a large, higher-risk rewrite. **Recommendation: ship gold now; treat platinum as a separate, optional transport-rewrite epic.**

Biggest single lever for "legit": the **EntityDescription refactor** — replace the per-entity bespoke classes (ported from nikshriv) with frozen `*EntityDescription` dataclasses carrying `value_fn`, `device_class`, `state_class`, `entity_category`, `translation_key`, `entity_registry_enabled_default`. This unlocks `entity-translations`, `entity-category`, `entity-device-class`, `entity-disabled-by-default`, and `icon-translations` in one pass, and is the canonical shape every gold/platinum WH integration uses.

## Research Questions

**Q1: What exactly do gold/platinum require?** 52 rules total: 18 bronze, 10 silver, 21 gold, 3 platinum (see Appendix B for full per-rule audit). Gold is entities + flows + docs + diagnostics. Platinum is async-dependency + inject-websession + strict-typing.

**Q2: How do exemplary WH integrations surface sensors?** Frozen dataclass extending `SensorEntityDescription` + `value_fn: Callable[[Device], StateType]`; a single generic entity class consuming `entity_description`; `_attr_has_entity_name=True`; `translation_key` for naming; `PARALLEL_UPDATES = 0` per platform module; all entities for a device share `identifiers={(DOMAIN, serial)}`. Source: `incomfort/sensor.py`, `sensibo/sensor.py`.

**Q3: Is platinum reachable?** Not without a transport rewrite — `AWSIoTPythonSDK` is synchronous. `incomfort` is platinum because `incomfort-client` is aiohttp-async. See Risk R1.

**Q4: Does HACS enforce any of this?** No — `quality_scale.yaml` + hassfest are core-only; `brands/`, CODEOWNERS, `.strict-typing` registration are core mechanics. For HACS the scale is aspirational, BUT shipping `quality_scale.yaml` + meeting the architectural rules is exactly what makes a custom integration "legit" and core-submittable later.

## Findings

### F1 — Current entity code is pre-EntityDescription (the core gap)
`sensor.py` has bespoke `NavienUnitSensor`/`NavienHeatingPowerSensor` with hardcoded English `name` properties and per-instance conversion. `switch.py`/`water_heater.py` similarly hardcode names. No `translation_key`, no `entity_category`, no `entity_registry_enabled_default`, no `icons.json`. This fails 5 gold entity rules at once. Refactor to descriptions fixes all 5.

### F2 — Canonical gold sensor shape (target)
```python
@dataclass(frozen=True, kw_only=True)
class NavienSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[NavienChannelData], StateType]

SENSORS: tuple[NavienSensorEntityDescription, ...] = (
    NavienSensorEntityDescription(
        key="hot_water_temp", translation_key="hot_water_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.outlet_temp,
    ),
    NavienSensorEntityDescription(
        key="error_code", translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.error_code,
    ),
    # ...water usage, filter, recirc, firmware (DIAGNOSTIC, disabled-by-default)
)
PARALLEL_UPDATES = 0
```
One generic `NavienSensor(NavienChannelEntity, SensorEntity)` consumes `entity_description`; `native_value = self.entity_description.value_fn(data)`. Unit/scaling stays in the data layer (per-`unitType` factors, F4 of the capabilities research) — descriptions hold only HA-facing metadata.

### F3 — Map the unused telemetry (from the capabilities research) onto gold entities
From `2026-06-23_navilink-api-capabilities.md` — surface as:
- **sensor (primary):** hot-water temp, flow, gas instant/accumulated, inlet temp.
- **sensor (DIAGNOSTIC, disabled-by-default):** `swVersion`, `controllerVersion`, `panelVersion`, `wifiRssi`, `daysFilterUsed`, `accumulatedWaterUsage`, `numOfWaterUse`, `currentRecirculationTemp`, `outdoorTemperature`.
- **binary_sensor (new platform):** `errorCode != 0` → `device_class=PROBLEM` + `fault_code` attr; `freezeProtectionStatus`; `filterStatus`; `connected`.
- **water_heater:** keep as primary (`_attr_name=None`); add `translation_key` for operation-mode i18n.
- **climate (combi only, wave 3):** gate on `heatControl==1`.

### F4 — Coordinator migration recommended (not strictly required)
Current push-callback model (entities register on `channel`) satisfies `entity-event-setup` + `runtime-data`. But gold/platinum integrations universally use `DataUpdateCoordinator[T]` with `value_fn` reading a typed snapshot. Migrating to a `DataUpdateCoordinator[NavienData]` that the push client feeds (`async_set_updated_data` on each MQTT status) gives: typed `runtime_data`, free `CoordinatorEntity.available`, `dynamic-devices` hook, and the description pattern's natural home. Recommended as the backbone refactor.

### F5 — strings.json + icons.json are mandatory for gold
`entity.<platform>.<key>.name` for every `translation_key`; `entity.water_heater.<key>.state.<value>` for operation modes; `exceptions.<key>.message` for `exception-translations`; `icons.json` `entity.<platform>.<key>.default = "mdi:..."`. Sensors with a `device_class` and no `translation_key` auto-name — but explicit keys are clearer here.

## Compatibility Analysis

- All architectural rules apply to HACS components; only `brands/`, CODEOWNERS, `.strict-typing` registration, and hassfest enforcement are core-only. Shipping `quality_scale.yaml` is harmless and signals intent.
- Refactor is internal — no manifest requirement changes for gold. `bump quality_scale: bronze → gold` only after the rules are met (don't claim early).
- Test stack: `pytest-homeassistant-custom-component` (provides `hass` fixture, `snapshot_platform`, `MockConfigEntry`). Add `requirements_test.txt`.
- Existing `diagnostics.py`, reauth flow, `runtime_data`, `DeviceInfo`, `unique_id`, `_abort_if_unique_id_configured` already satisfy several gold/silver rules — good foundation.

## Recommendation

**Go for gold in 4 dependency-ordered waves; defer platinum.**

| Wave | Rules closed | Scope |
|---|---|---|
| A — Backbone | runtime-data(✓), entity refactor groundwork | `DataUpdateCoordinator[NavienData]` + typed `NavienConfigEntry`; typed data snapshot dataclass |
| B — Entities (the "legit" core) | `entity-translations`, `entity-category`, `entity-device-class`, `entity-disabled-by-default`, `icon-translations`, new `binary_sensor` | EntityDescription refactor across sensor/switch/binary_sensor/water_heater; `strings.json` entity+exceptions; `icons.json` |
| C — Flows + silver | `parallel-updates`, `log-when-unavailable`, `reconfiguration-flow`, `repair-issues`, `exception-translations` | `PARALLEL_UPDATES=0`; once-only unavailable logging; `async_step_reconfigure`; repair issue for token-expiry + unsupported-model |
| D — Tests + docs | `test-coverage`(>95%), `config-flow-test-coverage`(100%), all `docs-*` | pytest suite w/ snapshots; README sections (data-update, supported-devices/functions, troubleshooting, examples, use-cases, limitations) |

Then bump `manifest.json quality_scale: gold` and add `quality_scale.yaml` self-assessment.

**Platinum** = separate epic: rewrite transport to `aiomqtt` + AWS-IoT SigV4 websocket (async-dependency), inject `async_get_clientsession(hass)` into the REST login (inject-websession), extract `navien_api.py` to a typed PyPI lib with `py.typed` (strict-typing). High effort, real regression risk on a working transport. Only pursue if targeting core submission.

## Implementation Sketch

- **New file `binary_sensor.py`** — add `Platform.BINARY_SENSOR` to `__init__.py:PLATFORMS`; `BinarySensorDeviceClass.PROBLEM` for faults; `EntityCategory.DIAGNOSTIC`.
- **`coordinator.py`** — introduce `@dataclass NavienData` snapshot; `class NavienDataUpdateCoordinator(DataUpdateCoordinator[NavienData])` with `config_entry: NavienConfigEntry`; push client calls `async_set_updated_data(snapshot)` from its MQTT callback; keep `certifi` root CA.
- **`entity.py`** — `NavienChannelEntity(CoordinatorEntity[NavienDataUpdateCoordinator])`; drop manual callback register/deregister (CoordinatorEntity handles it); keep `DeviceInfo`.
- **`sensor.py`/`switch.py`/`water_heater.py`** — collapse to generic entity + description tuples; `value_fn` reads `coordinator.data`.
- **`strings.json` + new `icons.json` + `translations/en.json`** — entity names, operation-mode states, exception messages, mdi icons.
- **`quality_scale.yaml`** (new) — all 52 rules with `done`/`exempt`/`todo` + comments (Appendix B is the seed).
- **`tests/`** (new) — `conftest.py` with `MockConfigEntry` + mocked `NavilinkConnect`; `test_config_flow.py` (100% branches incl. reauth/reconfigure); `test_sensor.py` snapshot via `snapshot_platform`; `requirements_test.txt`.
- **`.github/brands` note** — logo/icon PR to `home-assistant/brands` only if pursuing core; exempt for HACS.

## Dissent / Trade-offs

- **Coordinator migration vs keep-push:** migrating risks regressing the working push transport for cleanliness. Mitigation: the push client can feed a coordinator without changing transport — `async_set_updated_data` on each MQTT message preserves push semantics while gaining the typed-snapshot ergonomics. Low risk if done as a thin adapter.
- **Disabled-by-default scope:** over-disabling hides useful sensors; under-disabling clutters. Gold wants noisy/rarely-needed entities disabled — apply to firmware/RSSI/diagnostic counts, keep temps/flow/usage enabled.

## Risks

- **R1 — Platinum is unreachable without a transport rewrite.** `async-dependency` is absolute ("no exceptions to this rule"); `AWSIoTPythonSDK` + `run_in_executor` violates it. Rewriting AWS-IoT MQTT auth (SigV4-signed websocket URL) by hand is subtle and easy to get wrong; the current SDK path is proven against the live unit. Do not start the rewrite to chase a badge unless core submission is the goal — gold is the honest, safe ceiling for the SDK-based transport.
- **R2 — Test coverage on a cloud/MQTT integration is the long pole.** >95% requires mocking `NavilinkConnect` and the MQTT callback flow thoroughly. Budget wave D accordingly; it's the rule most likely to stall the gold claim.
- **R3 — Claiming a tier you don't meet is worse than a lower honest tier.** Keep `manifest.json quality_scale` truthful; bump only after the wave's rules verifiably pass. hassfest would reject mismatches on core; reviewers notice on HACS.
- **R4 — Single-device validation.** `dynamic-devices`/`stale-devices` can be `exempt` (one device per config entry) — but confirm against a multi-channel/cascade unit before claiming exempt; capability-gate rather than assume.

## Open Questions

1. Pursue core submission (justifies platinum rewrite + brands PR) or stay HACS-only (gold is the ceiling)?
2. Migrate to `DataUpdateCoordinator` (recommended) or keep the push-callback model and bolt descriptions on directly?
3. Operation-mode taxonomy for `water_heater` `translation_key` states — needs the real `operationMode`/`heatStatus` enum maps (open question from the capabilities research).

## References

- HA Integration Quality Scale — https://developers.home-assistant.io/docs/core/integration-quality-scale/ and `.../rules/<rule>/`
- `ALL_RULES` — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/quality_scale.py
- `incomfort` (platinum, cloud-polling WH) — https://github.com/home-assistant/core/tree/dev/homeassistant/components/incomfort
- `sensibo` (gold, EntityDescription+value_fn) — https://github.com/home-assistant/core/tree/dev/homeassistant/components/sensibo
- `econet` (Rheem WH) , `aquanta` (WH controller) — core components
- `quality_scale.yaml` example (co2signal) — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/co2signal/quality_scale.yaml
- Companion research: `docs/_research/2026-06-23_navilink-api-capabilities.md` (field inventory feeding F3).

## Appendix B — Per-rule self-audit (seed for quality_scale.yaml)

**BRONZE (18):** action-setup `exempt`(no actions) · appropriate-polling `todo`(move to coordinator update_interval) · brands `exempt`(HACS) · common-modules `done` · config-flow `done` · config-flow-test-coverage `todo` · dependency-transparency `done`(AWSIoTPythonSDK pinned, PyPI) · docs-high-level-description `todo` · docs-installation-instructions `done`(README) · docs-removal-instructions `todo` · entity-event-setup `done` · entity-unique-id `done` · has-entity-name `done` · runtime-data `done` · test-before-configure `done`(login in flow) · test-before-setup `done`(ConfigEntryNotReady) · unique-config-entry `done`

**SILVER (10):** action-exceptions `exempt` · config-entry-unloading `done` · docs-configuration-parameters `todo` · docs-installation-parameters `todo` · entity-unavailable `done` · integration-owner `done`(@lasswellt) · log-when-unavailable `todo` · parallel-updates `todo` · reauthentication-flow `done` · test-coverage `todo`

**GOLD (21):** devices `done` · diagnostics `done` · discovery `exempt`(cloud account, undiscoverable) · discovery-update-info `exempt` · docs-data-update `todo` · docs-examples `todo` · docs-known-limitations `todo` · docs-supported-devices `todo` · docs-supported-functions `todo` · docs-troubleshooting `todo` · docs-use-cases `todo` · dynamic-devices `exempt`(single device/entry — verify R4) · entity-category `todo` · entity-device-class `todo`(partial in sensors) · entity-disabled-by-default `todo` · entity-translations `todo` · exception-translations `todo` · icon-translations `todo` · reconfiguration-flow `todo` · repair-issues `todo`(token-expiry, unsupported-model) · stale-devices `exempt`(single device — verify R4)

**PLATINUM (3):** async-dependency `todo`→**blocked**(AWSIoTPythonSDK blocking; R1) · inject-websession `todo`(REST login creates own session) · strict-typing `todo`(vendored client untyped; core-only registration)

**Tally:** done=16, exempt=7, todo=29. Gold reachable by closing the 21 gold `todo`/`partial` (minus 4 already exempt).
