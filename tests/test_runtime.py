"""#12 runtime posture — RuntimeConfig, offline scope, and the source egress filter."""

import foley
from foley.runtime import (
    EXTERNAL,
    LOCAL,
    RuntimeConfig,
    current_runtime,
    is_offline,
    offline_scope,
)
from foley.sources import registry


def test_runtime_config_postures():
    assert RuntimeConfig.default().data_egress_allow == frozenset({LOCAL, EXTERNAL})
    off = RuntimeConfig.offline_local()
    assert off.offline and off.data_egress_allow == frozenset({LOCAL})
    assert off.telemetry is False and off.redaction_mode == "hash"
    assert off.allows(LOCAL) and not off.allows(EXTERNAL)
    assert not off.allows(None)  # fail-closed on an undeclared egress


def test_from_env_offline(monkeypatch):
    monkeypatch.setenv("FOLEY_OFFLINE", "1")
    assert RuntimeConfig.from_env().offline is True
    monkeypatch.setenv("FOLEY_OFFLINE", "no")
    assert RuntimeConfig.from_env().offline is False


def test_offline_scope_disables_and_restores_telemetry():
    foley.obs.enable()
    try:
        assert foley.obs.is_enabled() and not is_offline()
        with offline_scope() as cfg:
            assert cfg.offline and is_offline()
            assert not foley.obs.is_enabled()  # telemetry off inside the scope
        assert foley.obs.is_enabled()  # restored on exit
        assert not is_offline()
        assert current_runtime().offline is False
    finally:
        foley.obs.disable()


def test_offline_scope_restores_when_telemetry_was_off():
    foley.obs.disable()
    assert not foley.obs.is_enabled()
    with offline_scope():
        assert not foley.obs.is_enabled()
    assert not foley.obs.is_enabled()  # stays off (prior state restored)


def test_offline_scope_dominates_foley_obs_env(monkeypatch):
    """Offline telemetry-off must beat $FOLEY_OBS (nothing leaves the device)."""
    foley.obs.disable()
    monkeypatch.setenv("FOLEY_OBS", "1")
    assert foley.obs.is_enabled()  # the env var turns obs on...
    with offline_scope():
        assert not foley.obs.is_enabled()  # ...but offline force-disables it, dominating the env
    assert foley.obs.is_enabled()  # restored on exit (env var still set)
    monkeypatch.delenv("FOLEY_OBS", raising=False)


def test_offline_scope_restores_prior_redaction_mode():
    from foley.obs import recorder
    from foley.obs.redact import RedactionMode

    prior = recorder._CONFIG.redaction_mode
    foley.obs.configure(redaction_mode=RedactionMode.off)
    try:
        with offline_scope():
            assert recorder._CONFIG.redaction_mode == RedactionMode.hash  # scope's mode
        assert recorder._CONFIG.redaction_mode == RedactionMode.off  # restored
    finally:
        foley.obs.configure(redaction_mode=prior)


def test_source_egress_filter():
    all_names = registry.list_sources()
    assert {"freesound", "elevenlabs", "stable_audio"} <= set(all_names)
    local = registry.list_sources(egress_allow=frozenset({LOCAL}))
    assert "stable_audio" in local
    assert "freesound" not in local and "elevenlabs" not in local
    assert registry.local_sources() == local
    assert registry.source_egress("freesound") == "external"
    assert registry.source_egress("stable_audio") == "local"


def test_validate_egress_passes_for_real_configs_and_fails_closed():
    registry._validate_egress()  # the three real configs all declare a valid egress
    # a source with a missing/invalid data_egress is a configuration error
    registry.register_source("_bad_egress", {"kind": "retrieve"})  # no data_egress
    try:
        import pytest

        with pytest.raises(ValueError):
            registry._validate_egress()
    finally:
        registry.SOURCE_REGISTRY.pop("_bad_egress", None)
