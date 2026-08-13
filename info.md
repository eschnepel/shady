# Shady – Shading-Adjusted PV Forecast

Corrects an existing PV yield forecast for local shading effects (e.g. a
tree or building) by empirically fitting actual yield against the raw
forecast value, per 5-minute slot, from each string's own recent history —
no sun-position calculation and no horizon profile to configure; see the
project's ADRs for the full design.

**Status:** Brainstorming / concept phase – no working version yet.
