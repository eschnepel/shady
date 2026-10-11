# Shady

A Home Assistant integration that corrects a solar (PV) yield forecast for the
shading of one specific roof, by learning from the history of the forecast and
of the actual yield.

## Language

### Slots

**Slot**: A five-minute interval of time, always labelled and entered in the
local timezone.

**Current slot**: The slot the present moment falls in. It has not finished yet.

**Last completed slot**: The most recently finished slot. It is never the
current slot. _Avoid_: Last complete slot

**Pinned slot**: A slot a person has fixed in order to inspect it, instead of
following.

**Following**: The state in which the diagnosed slot is always the last
completed slot, as opposed to pinned. _Avoid_: Auto-tracking

**Diagnosed slot**: The slot the diagnostics analyse: the last completed slot
while following, the pinned slot while pinned.

**Analysed slot**: The slot the forecast sensors analyse: always the last
completed slot, because they only ever follow.

**Reference timestamp**: The instant a window of days is measured from: the
analysed slot for the forecast sensors, the diagnosed slot for the diagnostics.

### Days and windows

**Day**: A span of exactly 24 hours: its start is always 24 hours before its
end, regardless of daylight saving time.

**Reference day**: The day that ends at the local midnight closing the date of
the reference timestamp. The only day placed using the daylight-saving setting
of the local timezone; every earlier day lies exactly 24 hours before the next.

**Window**: The configured number of days immediately before the reference day.
The reference day itself is not part of it.

**Pool**: For one slot, its samples on each day of the window, together with
those of its neighbor slots.

**Neighbor slot**: A slot a whole number of five-minute steps before or after
another slot, crossing midnight like any other time.
