# ADR-010 – Config Flow Shape

**Date:** 2026-08-14 **Status:** Accepted **Split from:** ADR-001 §6. Originally
part of the shading-model ADR; extracted because it is a cross-cutting
specification that collects fields introduced by several other ADRs, and was
already being referenced externally (ADR-003a/ADR-003b, ADR-005, ADR-006) as if
it were its own document. No behavior changed by this split. **Last updated:**
2026-09-17 (`TASK-0035`: reconfigure-flow migration and per-string-settings
reshape integrated into this main text — see the Decision section's own
provenance notes for what changed and why).

This ADR is kept current in place as the single authoritative field list — every
field below is live in the shipped config/reconfigure flow. Fields added after
the original split: ADR-003c's weather-forecast entity and temperature
regression method (2026-08-18); the ambient-to-cell max uplift and rated DC
capacity fields ADR-003b §1a's formula needs (2026-08-20); `recency_decay_max`
for ADR-001 §4a's day-recency weighting (2026-08-25); `baseline_manual_shape`
for ADR-009 §3's manual-entry baseline fallback (implemented earlier, documented
here 2026-09-10 per `AUDIT-0010`). The flow's own *shape* — step ordering, the
string-selection mechanism, and how reconfiguration works — was reworked in full
by `TASK-0035` (2026-09-17); that reshape is the Decision below, not a layer on
top of an older one.

______________________________________________________________________

## Context

Shady's config flow collects settings introduced across several ADRs: the
regression model and its granularity/smoothing/window (ADR-001 §2/§3/§4),
baseline sourcing (ADR-009), yield corrections (ADR-003a, ADR-003b, ADR-003c),
and the intraday deviation correction (ADR-006). This ADR is the single,
authoritative specification of the resulting flow's shape and step ordering —
other ADRs that add a config-flow field point here rather than each describing
their own step placement.

The flow shipped in two shapes over time. The original (2026-08-14) design
established every global setting in one crowded `settings` step, then asked for
a string's entire configuration — name, baseline override, actual-yield entity,
advanced corrections — in one cramped, repeated `add_string`/
`add_string_advanced`/`add_another` loop, before a person could see their own
strings laid out together; post-setup editing lived on a separate
`ShadyOptionsFlow`, mirroring the same step shape. `TASK-0035` (2026-09-17)
replaced this after a real-world bug report — reconfiguring an existing
installation had never actually taken effect, since initial release (see "Why
`ShadyOptionsFlow` goes" below) — and, given the flow was being touched either
way, reshaped the rest of it at the same time per explicit human direction. The
design below is that reshape; it is the only flow shape this ADR now describes.

______________________________________________________________________

## Decision

Given ADR-001 §3 (one model per configured string) and ADR-009 (baseline
sourcing), the config flow establishes global settings **first**, before any
string exists — a person configures "how Shady should behave" once, then adds
however many strings share that behavior, rather than being asked global
questions only after already committing to a first string. Global settings are
split across three pages (`baseline`, `regression_tuning`, `advanced_optional`)
rather than one crowded step; strings are defined by a single multi-select
entity field (the mechanism `github.com/eschnepel/effy` uses for its own
multi-sensor fields, adapted here since Effy has no per-item-settings concept at
all) instead of a repeated add-one-at-a-time loop, with each string's own
settings reached via a hub-and-loop rather than crammed into that same repeated
loop:

```
Step "baseline" (first, global):
  - Global default baseline candidate (dropdown, ranked by
    providers/discovery.py per ADR-009 — covering both `sensor.*`
    PV-forecast candidates and `weather.*` sunshine-duration/
    cloud-coverage proxy candidates alike; "None of these" → manual
    entity + attribute path entry, plus a manual shape selector,
    `baseline_manual_shape` (default `"sensor_dict"`, one of
    `"sensor_dict"`/`"sensor_list"`/`"weather_sunshine"`/
    `"weather_cloud"` — ADR-009 §3's shape choice for the manually-
    entered entity/attribute, unused when a discovered candidate is
    selected instead)) — used by any string that does not override it
  - "Does this baseline already account for temperature effects itself?"
    (boolean, default false — ADR-003b §1c; presented right alongside the
    baseline candidate above, since it is a property of *that* choice)

Step "strings":
  - One multi-select `selector.EntitySelector` (`domain: sensor`,
    `device_class: [power, energy]`, `multiple: true`) — every entity
    picked here *is* a string, identified by its own `entity_id`. Adding
    or removing an entity here is the only way a string is added or
    removed; there is no separate "add a string" step.

Step "string_settings_hub" (loop, entered once per string picked above,
  skipped entirely if none were picked):
  - "Which string do you want to configure further?" — a dropdown of every
    entity picked in "strings" (label: its name if already set this
    session, else its entity_id) plus "Done"
  - picking one → "string_settings_edit" for that entity_id, then back to
    this hub; picking "Done" → "regression_tuning" (linear setup) or back
    to the reconfigure menu (see below)

Step "string_settings_edit" (one entity_id at a time, tracked in flow
  state the same way `homeassistant.helpers.schema_config_entry_flow`
  itself already documents this exact pattern — "store the key ... of a
  sub-item that will be edited in the next step"):
  - Name (optional free text, default "" — a string's identity is its
    `entity_id` from "strings" above, not this label)
  - Baseline candidate override (optional; same dropdown as the global
    default; a distinct "use the global default" sentinel, not the global
    step's own "None of these" sentinel — the two mean different things.
    A string that *does* override is, by definition, treated as
    temperature-aware — ADR-003b §1c)
  - Temperature source override (optional; leave empty to use the global
    default; "none" disables derating for this string specifically even
    if a global default is set — ADR-003b §1a)
  - Converter/inverter AC power limit (optional number, W — ADR-003a §1)
  - Temperature coefficient in %/°C (default −0.4 — ADR-003b §1)
  - Rated DC capacity, Wp (optional number — ADR-003b §1a/ADR-003c §5)
  - No separate "configure advanced corrections?" gate — every field
    above is on this one page, always shown; the old gate's only point
    was reducing clutter in a *shared, repeated* loop, which no longer
    applies once each string already has a page of its own

Step "regression_tuning" (global):
  - Training window in days (default 28)
  - Regression method: `wls2` (default) / `linear` / `kernel` / `wls3`
    (global — applies to every configured string, see ADR-001 §2;
    chosen manually, no auto-selection based on data volume)
  - Smoothing radius in slots (default 1, global; see ADR-011 §1 — `0`
    disables temporal smoothing)
  - Neighbor-fitting cut-off, `neighbor_fitting_cutoff` (default 25%,
    global; see ADR-011 §2/§3 — the maximum median-ratio deviation a
    neighbor series may have before being excluded from a slot's training
    pool; the sentinel `-1%` switches to always-rescale instead of
    exclude, per ADR-011 §3)
  - Recency decay, `recency_decay_max` (default 50%, global; see
    ADR-001 §4a — the maximum downweight applied to the oldest day in
    the rolling training window, decreasing linearly to `0%` at the most
    recent day; `0%` disables recency weighting entirely, every day in
    the window counting equally)
  - Clipping threshold, % of inverter limit (default 98%, global; see
    ADR-003a §1 — applies to every string that has a converter/inverter AC
    power limit configured in "string_settings_edit"; a string without a
    limit configured is never clipping-excluded, but the threshold
    fraction itself has no per-string override)

Step "advanced_optional" (global; last step of the linear sequence):
  - Default temperature source (optional; entity selector covering
    sensor.* with device_class temperature and weather.* entities;
    leave empty to disable derating correction by default for all
    strings — ADR-003b §1a)
  - Ambient-to-cell max uplift, °C (default 25; global; only relevant
    when the resolved temperature source — global default or a
    per-string override — is the ambient-sensor or weather-integration
    tier, since the module/cell-sensor tier reads cell temperature
    directly and never evaluates this formula at all; see ADR-003b §1a
    for the uplift formula this feeds)
  - Weather forecast entity for temperature prediction (optional; entity
    selector covering weather.* entities; used to forecast the expected
    module/cell or ambient temperature for the module/cell-sensor and
    ambient-sensor tiers above — see ADR-003c §3. Global, not
    per-string, and independent of the baseline candidate above even if
    that candidate also happens to be a weather.* entity. Leave empty to
    disable ADR-003c's forecast mechanism: any string using the
    module/cell or ambient temperature tier then gets no derating
    correction at all, forward or backward — see ADR-003c §5. Not shown
    or relevant if the weather-integration tier is the only temperature
    source in use, since that tier already forecasts natively)
  - Temperature regression method: `wls2` (default) / `linear` /
    `kernel` / `wls3` (global; only relevant if the field above is set —
    see ADR-003c §2. Independent of the shading-model regression method
    above: the two fit unrelated physical relationships and are not
    forced to share one method choice)
  - Intraday deviation-correction mode `intraday_correction_mode`:
    off / ramping / blending (default off; see ADR-006 §1)
  - Intraday deviation-correction cut-off, `intraday_correction_cutoff`
    (default 10%, applies whenever the mode above is not "off"; see
    ADR-006 §2)
  - Intraday deviation-correction rolling window, in slots (default 24 =
    2h; see ADR-006 §3)
  - Intraday deviation-correction ramp/blend duration, in slots (default
    12 = 1h; see ADR-006 §3)
```

Note there is no latitude/longitude/elevation field anywhere in this flow — see
ADR-001 §1 for why.

**Linear for first setup, menu for reconfigure.** `async_step_user` walks the
five steps above in the fixed order shown — `baseline` → `strings` →
`string_settings_hub` (loop) → `regression_tuning` → `advanced_optional` —
finishing with `self.async_create_entry(title="Shady", data=...)`.
`async_step_reconfigure` instead opens on an `async_show_menu` (a small, fixed
set of named branches — the right fit for `async_show_menu`, unlike the dynamic
per-string loop above, which cannot be: menu dispatch works by reflecting on
real `async_step_*` method names, so it cannot fan out to an a-priori-unknown
number of strings) with options "Baseline," "Strings," "Regression Tuning,"
"Advanced & Optional Settings," and "Save & Finish" — every step pre-filled from
the existing config entry's current data. Submitting any one section returns to
this same menu rather than proceeding to the next section linearly —
reconfiguring one setting no longer means re-visiting every other section to get
there, which the original flow forced regardless of what actually needed
changing. "Strings" leads into "strings" (pre-filled with the
currently-configured entity_ids) → "string_settings_hub" loop → back to *this
top-level menu* once "Done" is chosen in the hub, not onward to
"regression_tuning" as the linear path does. "Save & Finish" commits via
`self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=...)`
— HA's own recommended helper, which updates `entry.data` directly, reloads the
entry, and aborts with `reason="reconfigure_successful"` in one call.

**Why `ShadyOptionsFlow` goes.** Its final step returned
`self.async_create_entry(title="", data={...})` — in Home Assistant, an
`OptionsFlow`'s `async_create_entry` writes to `entry.options`, never
`entry.data`. `coordinator.py` reads exclusively from `entry.data` (ADR-002
§1a). No reconfiguration had ever actually taken effect, from initial release
onward — not a race, a standing bug, found (not designed around) when a person
reported "the changed configuration doesn't get written." Nothing ever reloaded
the entry either, since neither an update listener nor `OptionsFlowWithReload`
was ever registered. `ShadyConfigFlow` gains `async_step_reconfigure` instead;
both entry points share one set of step methods (the original module docstring's
stated reason for keeping `ShadyConfigFlow`/`ShadyOptionsFlow` separate — MRO
risk from a shared base alongside two different untyped HA base classes — no
longer applies once both live on the one `ConfigFlow` subclass). No `unique_id`
scheme exists for this integration (one relevant config entry per physical
installation, no external account to mismatch), so the
`async_set_unique_id`/`_abort_if_unique_id_mismatch` pairing HA's
reconfigure-flow guidance recommends for auth-style integrations is deliberately
not added.

**Why the string-adding mechanism changes.** The original `add_string`/
`add_string_advanced`/`add_another` loop asked for a string's full configuration
— name, baseline override, actual-yield entity, advanced corrections — in one
cramped, repeated sequence, immediately on first setup, before a person could
see their own strings laid out together. Effy (`github.com/eschnepel/effy`)
takes a different approach for its own multi-sensor fields: a single
`selector.EntitySelector` with `multiple: true`, letting a person pick several
sensors in one form field rather than looping a form once per sensor. Adopting
that same shape for *which entities are strings* — while keeping each string's
own settings on a page of its own, which Effy has no equivalent of at all, since
every sensor gets identical treatment there — is this design. An initial
proposal to use Home Assistant's native `ConfigSubentries` for the per-string
pages was raised and dropped: subentries manage their own independent add/remove
lifecycle, which doesn't fit a design where the string list is defined by an
earlier step's multi-select rather than each subentry's own flow.
`string_settings_hub`'s per-string dispatch instead uses a `vol.In` dropdown,
not `async_show_menu` — menu dispatch needs a fixed, a-priori-known set of step
names, which a dynamic, per-installation string list can't provide; the
reconfigure top-level menu's own small, fixed section list is the genuine fit
for `async_show_menu`.

**Removing a string discards its settings.** If an entity is removed from the
"strings" multi-select — during either the linear or the menu path — any
per-string settings collected for it (this session, or from the config entry
being reconfigured) are simply dropped from the in-progress result; nothing is
retained for a possible future re-add. As always with any config flow, nothing
is written to the config entry at all unless the flow actually reaches its final
`async_create_entry`/`async_update_reload_and_abort` call — abandoning a
reconfigure session part-way through leaves the existing entry completely
untouched, discarded settings included.

**No migration.** The "strings" shape (a bare list of entity_ids, each string's
own settings keyed by that `entity_id`) is not backward-compatible with the
pre-`TASK-0035` `CONF_STRINGS` list-of-dicts (each with its own required `name`
and `actual_yield_entity_id` fields). No migration path is implemented — a
deliberate choice, not an oversight, since exactly one installation of this
integration existed at the time of this change and reconfiguring it from scratch
cost nothing. A future contributor adding a second real installation before this
changes should re-open this question rather than assume it is still true.

**Actual-yield entity field folded away.** The original `add_string` step's
"Actual-yield entity" field was specified by an earlier version of this document
as a standard HA entity selector (sensor domain, power or energy device_class)
but the shipped schema used a plain required text field instead, asking a person
to type an `entity_id` by hand. That field no longer exists separately at all:
the "strings" step's own multi-select selector (`domain: sensor`,
`device_class: [power, energy]`) *is* that same entity selector, now serving
double duty as both the identity mechanism and the correction to this document's
original, never-actually-implemented spec.

**Config-entry data shape.** Every global field above (from `baseline`,
`regression_tuning`, and `advanced_optional`) is stored flat on `entry.data`,
keyed by its own `CONF_*` constant (`const.py`) — unchanged in meaning or
default from field to field regardless of which page now collects it, only the
page/step changed. `CONF_STRINGS` (`entry.data["strings"]`) holds a dict keyed
by each string's `entity_id`, not a list — the entity_id *is* the string's
identity, so it is never also duplicated as a field inside its own settings
dict. Each value is the `string_settings_edit` fields above, plus the
baseline-override trio (`baseline_entity_id`/`baseline_attribute`/
`baseline_shape`) and its ADR-009 §1c-Amendment `baseline_history_entity_id`
companion, resolved the same way the global baseline candidate resolves theirs.

______________________________________________________________________

## Consequences

- **Pro:** Establishes every global setting before a person configures their
  first string, so string-specific questions (baseline override, converter
  limit, temperature override) are answered with the relevant global defaults
  already visible, rather than the reverse.
- **Pro:** Reconfiguration actually works (writes to `entry.data`, reloads the
  entry) and lets a person jump straight to the one section that needs changing
  instead of re-walking the entire flow.
- **Con:** As the single place every other ADR's config-flow fields converge,
  this document has to be kept in sync whenever a future ADR adds or changes a
  field — a cost concentrated here specifically so it does not have to be paid
  by re-deriving step ordering independently in each of those ADRs.
- **Con:** `string_settings_hub`/`string_settings_edit`'s dynamic per-string
  dispatch cannot use `async_show_menu` (see above), so it carries slightly more
  custom flow-state bookkeeping (`self._editing_entity_id`) than the reconfigure
  top-level menu needs.
