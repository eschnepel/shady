"""Zero-mocking tests for `cache.py`'s `ServiceResponseCache` (ADR-007 §1a,
`TASK-0036`) — the service-call counterpart of the storage core's injected
`fetch_fn` path (`test_cache_core.py`), covering `Cache` itself.

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module. No `hass`
anywhere in this file: `ServiceResponseCache` never imports
`homeassistant.*`, taking an injected async `call_fn` (mirroring
`Cache`'s `fetch_fn`) and an optional, duck-typed `store` object
(`attach_store`) instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from tests.support import _load, _run

# Same multi-module load order `test_cache_core.py` already establishes:
# `cache.py` does `from .regression.base import FittedModel`.
_load("regression/base.py", "shady.regression.base")
cache_mod = _load("cache.py", "shady.cache")

ServiceResponseCache = cache_mod.ServiceResponseCache
service_call_key = cache_mod.service_call_key
SERVICE_RESPONSE_MAX_AGE = cache_mod.SERVICE_RESPONSE_MAX_AGE

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)


class _FakeStore:
    """Real (non-`Mock`) stand-in for `homeassistant.helpers.storage
    .Store` — just `async_load`/`async_save`, backed by a plain dict so
    a second `ServiceResponseCache` constructed against the same
    `_FakeStore.backing` (a simulated restart) actually observes a
    prior `attach_store` + successful call."""

    def __init__(self, backing: dict[str, Any] | None = None) -> None:
        self.backing: dict[str, Any] = backing if backing is not None else {}
        self.load_calls = 0
        self.save_calls = 0

    async def async_load(self) -> Any:
        self.load_calls += 1
        return self.backing.get("data")

    async def async_save(self, data: Any) -> None:
        self.save_calls += 1
        self.backing["data"] = data


class _RaisingStore:
    """A store whose `async_load`/`async_save` always raise — proving a
    storage failure degrades gracefully (ADR-000 §8) rather than
    breaking `async_call`."""

    async def async_load(self) -> Any:
        raise RuntimeError("synthetic load failure")

    async def async_save(self, data: Any) -> None:
        raise RuntimeError("synthetic save failure")


def _key(config_entry: str = "fs_entry_1") -> Any:
    return service_call_key("forecast_solar", "get_forecast", {"config_entry": config_entry})


class TestServiceCallKey:
    """`service_call_key` — the cache key one service call is remembered
    under. Must distinguish the things that change the answer (domain,
    service, service data, target) and nothing else."""

    def test_key_is_independent_of_data_key_order(self) -> None:
        first = service_call_key("weather", "get_forecasts", {"type": "hourly", "x": 1})
        second = service_call_key("weather", "get_forecasts", {"x": 1, "type": "hourly"})
        assert first == second

    def test_key_is_a_stable_string(self) -> None:
        key = _key()
        assert isinstance(key, str)
        assert key == _key()

    def test_different_calls_get_different_keys(self) -> None:
        keys = {
            _key("fs_entry_1"),
            _key("fs_entry_2"),
            service_call_key("forecast_solar", "other_service", {"config_entry": "fs_entry_1"}),
            service_call_key("other_domain", "get_forecast", {"config_entry": "fs_entry_1"}),
            service_call_key(
                "weather", "get_forecasts", {"type": "hourly"}, target={"entity_id": "weather.a"}
            ),
            service_call_key(
                "weather", "get_forecasts", {"type": "hourly"}, target={"entity_id": "weather.b"}
            ),
        }
        assert len(keys) == 6

    def test_target_is_part_of_the_key_not_folded_into_data(self) -> None:
        with_target = service_call_key(
            "weather", "get_forecasts", {"type": "hourly"}, target={"entity_id": "weather.a"}
        )
        without_target = service_call_key("weather", "get_forecasts", {"type": "hourly"})
        assert with_target != without_target


class TestRecallOnFailure:
    """The core contract: a successful, usable call is remembered; a
    failing or unusable one is answered from what was remembered last."""

    def test_successful_call_returns_and_remembers_the_live_response(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"t": 1.0}}

        result = _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert result == {"wh_period": {"t": 1.0}}
        assert cache.recall(_key(), now=_NOW) == {"wh_period": {"t": 1.0}}

    def test_raising_call_fn_returns_the_previous_response(self) -> None:
        cache = ServiceResponseCache()
        calls = 0

        async def call_fn() -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"wh_period": {"t": 1.0}}
            raise RuntimeError("synthetic service-call failure")

        _run(cache.async_call(_key(), call_fn, now=_NOW))
        result = _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert result == {"wh_period": {"t": 1.0}}
        # The failing attempt really was invoked — recall is a fallback,
        # never a short-circuit that stops calling at all.
        assert calls == 2

    def test_empty_response_falls_back_to_the_previous_one(self) -> None:
        cache = ServiceResponseCache()
        responses: list[Any] = [{"wh_period": {"t": 1.0}}, None, {}]

        async def call_fn() -> Any:
            return responses.pop(0)

        first = _run(cache.async_call(_key(), call_fn, now=_NOW))
        second = _run(cache.async_call(_key(), call_fn, now=_NOW))
        third = _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert first == {"wh_period": {"t": 1.0}}
        assert second == {"wh_period": {"t": 1.0}}
        assert third == {"wh_period": {"t": 1.0}}

    def test_usable_predicate_decides_what_counts_as_a_good_response(self) -> None:
        """A stricter caller-supplied predicate (e.g. `coordinator.py`'s
        Forecast.Solar poll requiring a non-empty `wh_period`) must not
        be evicted by a response that merely *is* a dict."""
        cache = ServiceResponseCache()
        responses: list[Any] = [{"wh_period": {"t": 1.0}}, {"watts": {}}]

        async def call_fn() -> Any:
            return responses.pop(0)

        def usable(response: Any) -> bool:
            return isinstance(response, dict) and bool(response.get("wh_period"))

        _run(cache.async_call(_key(), call_fn, usable=usable, now=_NOW))
        result = _run(cache.async_call(_key(), call_fn, usable=usable, now=_NOW))

        assert result == {"wh_period": {"t": 1.0}}

    def test_failure_with_nothing_remembered_returns_none(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            raise RuntimeError("synthetic failure")

        result = _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert result is None

    def test_each_key_is_remembered_independently(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn_a() -> Any:
            return {"wh_period": {"a": 1.0}}

        async def call_fn_b() -> Any:
            return {"wh_period": {"b": 2.0}}

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(cache.async_call(_key("fs_entry_1"), call_fn_a, now=_NOW))
        _run(cache.async_call(_key("fs_entry_2"), call_fn_b, now=_NOW))

        first = _run(cache.async_call(_key("fs_entry_1"), failing, now=_NOW))
        second = _run(cache.async_call(_key("fs_entry_2"), failing, now=_NOW))

        assert first == {"wh_period": {"a": 1.0}}
        assert second == {"wh_period": {"b": 2.0}}

    def test_a_later_success_replaces_the_remembered_response(self) -> None:
        cache = ServiceResponseCache()
        responses: list[Any] = [{"wh_period": {"a": 1.0}}, {"wh_period": {"b": 2.0}}]

        async def call_fn() -> Any:
            return responses.pop(0)

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(cache.async_call(_key(), call_fn, now=_NOW))
        _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert _run(cache.async_call(_key(), failing, now=_NOW)) == {"wh_period": {"b": 2.0}}

    def test_remembered_at_records_when_the_response_was_taken(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert cache.remembered_at(_key()) == _NOW
        assert cache.remembered_at(_key("never_called")) is None

    def test_a_failed_call_does_not_move_the_recorded_timestamp(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(cache.async_call(_key(), call_fn, now=_NOW))
        _run(cache.async_call(_key(), failing, now=_NOW + timedelta(hours=1)))

        assert cache.remembered_at(_key()) == _NOW


class TestExpiry:
    """12-hour recall expiry (`SERVICE_RESPONSE_MAX_AGE`) — a remembered
    response older than this is never recalled."""

    def test_an_entry_at_exactly_the_boundary_is_still_recalled(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(cache.async_call(_key(), call_fn, now=_NOW))

        boundary = _NOW + SERVICE_RESPONSE_MAX_AGE
        assert cache.recall(_key(), now=boundary) == {"wh_period": {"a": 1.0}}

    def test_an_entry_past_the_boundary_is_not_recalled(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(cache.async_call(_key(), call_fn, now=_NOW))

        past_boundary = _NOW + SERVICE_RESPONSE_MAX_AGE + timedelta(seconds=1)
        assert cache.recall(_key(), now=past_boundary) is None

    def test_an_expired_entry_falls_back_to_none_via_async_call_too(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(cache.async_call(_key(), call_fn, now=_NOW))
        past_boundary = _NOW + SERVICE_RESPONSE_MAX_AGE + timedelta(seconds=1)

        result = _run(cache.async_call(_key(), failing, now=past_boundary))

        assert result is None

    def test_an_expired_entry_is_pruned_on_the_next_successful_write(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        async def call_fn_other() -> Any:
            return {"wh_period": {"b": 2.0}}

        _run(cache.async_call(_key("fs_entry_1"), call_fn, now=_NOW))
        past_boundary = _NOW + SERVICE_RESPONSE_MAX_AGE + timedelta(seconds=1)
        _run(cache.async_call(_key("fs_entry_2"), call_fn_other, now=past_boundary))

        state = cache.service_response_state()
        assert _key("fs_entry_1") not in state["entries"]
        assert _key("fs_entry_2") in state["entries"]


class TestJsonSafety:
    """Responses are normalized on the way *in* (before being
    remembered), not on the way out — the live response handed back on
    a successful call is untouched, but a later recall is JSON-safe and
    round-trip-stable, exactly like a post-restart recall would be."""

    def test_datetimes_are_normalized_before_being_remembered(self) -> None:
        cache = ServiceResponseCache()
        moment = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)

        async def call_fn() -> Any:
            return {"weather.dwd": {"forecast": [{"datetime": moment, "cloud_coverage": 20}]}}

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        live = _run(cache.async_call(_key(), call_fn, now=_NOW))
        recalled = _run(cache.async_call(_key(), failing, now=_NOW))

        assert live == {"weather.dwd": {"forecast": [{"datetime": moment, "cloud_coverage": 20}]}}
        assert recalled == {
            "weather.dwd": {"forecast": [{"datetime": moment.isoformat(), "cloud_coverage": 20}]}
        }

    def test_tuples_and_non_string_keys_survive_as_json_shapes(self) -> None:
        cache = ServiceResponseCache()

        async def call_fn() -> Any:
            return {"wh_period": {1: 2.0}, "extra": (1, 2)}

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(cache.async_call(_key(), call_fn, now=_NOW))
        recalled = _run(cache.async_call(_key(), failing, now=_NOW))

        assert recalled == {"wh_period": {"1": 2.0}, "extra": [1, 2]}


class TestPersistence:
    """`Store`-backed restart persistence, via an injected duck-typed
    store object (`attach_store`) — the whole point of this cache: the
    first call after a restart is exactly the one most likely to fail,
    and the one with nothing in memory to fall back on."""

    def test_a_successful_call_is_written_to_the_store(self) -> None:
        cache = ServiceResponseCache()
        store = _FakeStore()
        cache.attach_store(store)

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(cache.async_call(_key(), call_fn, now=_NOW))

        entries = store.backing["data"]["entries"]
        assert entries[_key()]["response"] == {"wh_period": {"a": 1.0}}
        assert entries[_key()]["remembered_at"] == _NOW.isoformat()

    def test_a_restart_recalls_the_persisted_response_lazily(self) -> None:
        """No explicit restore call: the second cache loads from its
        store on its own, on first use — what makes a construction-time
        poll (which runs before any explicit restore step) able to fall
        back at all (ADR-007 §1a)."""
        backing: dict[str, Any] = {}
        first = ServiceResponseCache()
        first.attach_store(_FakeStore(backing))

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(first.async_call(_key(), call_fn, now=_NOW))

        second = ServiceResponseCache()
        second.attach_store(_FakeStore(backing))

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        result = _run(second.async_call(_key(), failing, now=_NOW))

        assert result == {"wh_period": {"a": 1.0}}

    def test_a_failing_first_call_never_clobbers_the_persisted_entry(self) -> None:
        backing: dict[str, Any] = {}
        first = ServiceResponseCache()
        first.attach_store(_FakeStore(backing))

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(first.async_call(_key(), call_fn, now=_NOW))
        before = dict(backing["data"]["entries"])

        second = ServiceResponseCache()
        second.attach_store(_FakeStore(backing))

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(second.async_call(_key(), failing, now=_NOW))

        assert backing["data"]["entries"] == before

    def test_entries_from_different_keys_share_one_store_payload(self) -> None:
        cache = ServiceResponseCache()
        store = _FakeStore()
        cache.attach_store(store)

        async def call_fn_a() -> Any:
            return {"wh_period": {"a": 1.0}}

        async def call_fn_b() -> Any:
            return {"weather.dwd": {"forecast": [1]}}

        _run(cache.async_call(_key("fs_entry_1"), call_fn_a, now=_NOW))
        _run(
            cache.async_call(
                service_call_key(
                    "weather", "get_forecasts", {"type": "hourly"}, target={"entity_id": "w"}
                ),
                call_fn_b,
                now=_NOW,
            )
        )

        assert len(store.backing["data"]["entries"]) == 2

    def test_a_corrupt_or_missing_store_payload_is_tolerated(self) -> None:
        """A malformed on-disk payload (hand-edited, or written by a
        future schema) must degrade to "nothing remembered", never
        raise (ADR-000 §8)."""
        cache = ServiceResponseCache()
        cache.attach_store(_FakeStore({"data": {"entries": "not-a-mapping"}}))

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        result = _run(cache.async_call(_key(), failing, now=_NOW))

        assert result is None

    def test_a_store_load_failure_degrades_to_nothing_remembered(self) -> None:
        cache = ServiceResponseCache()
        cache.attach_store(_RaisingStore())

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        result = _run(cache.async_call(_key(), failing, now=_NOW))

        assert result is None

    def test_a_store_save_failure_does_not_break_the_call(self) -> None:
        cache = ServiceResponseCache()
        cache.attach_store(_RaisingStore())

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        result = _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert result == {"wh_period": {"a": 1.0}}

    def test_without_a_store_the_cache_still_works_in_memory(self) -> None:
        cache = ServiceResponseCache()
        responses: list[Any] = [{"weather.dwd": {"forecast": [1]}}]

        async def call_fn() -> Any:
            return responses.pop(0)

        async def failing() -> Any:
            raise RuntimeError("synthetic failure")

        _run(cache.async_call(_key(), call_fn, now=_NOW))
        result = _run(cache.async_call(_key(), failing, now=_NOW))

        assert result == {"weather.dwd": {"forecast": [1]}}

    def test_attaching_a_store_twice_keeps_the_first(self) -> None:
        cache = ServiceResponseCache()
        first_store = _FakeStore()
        cache.attach_store(first_store)
        cache.attach_store(_FakeStore())

        async def call_fn() -> Any:
            return {"wh_period": {"a": 1.0}}

        _run(cache.async_call(_key(), call_fn, now=_NOW))

        assert first_store.save_calls == 1
