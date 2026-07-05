import pytest

import cloud_impact


class _RangeValue:
    def __init__(self, min_, max_):
        self.min = min_
        self.max = max_


def test_mean_range():
    assert cloud_impact.mean_range(_RangeValue(2.0, 4.0)) == 3.0


def test_to_scalar_with_range_value():
    assert cloud_impact.to_scalar(_RangeValue(1.0, 3.0)) == 2.0


def test_to_scalar_with_plain_float():
    assert cloud_impact.to_scalar(1.09) == 1.09


# Pins the Opus-family ordering _version_key must preserve.
@pytest.mark.parametrize(
    "name,expected_key",
    [
        ("claude-opus-4-20250514", (4,)),
        ("claude-opus-4-0", (4, 0)),
        ("claude-opus-4-1-20250805", (4, 1)),
        ("claude-opus-4-1", (4, 1)),
        ("claude-opus-4-5-20251101", (4, 5)),
        ("claude-opus-4-5", (4, 5)),
        ("claude-opus-4-6", (4, 6)),
        ("claude-opus-4-7", (4, 7)),
        ("claude-opus-4-8", (4, 8)),
    ],
)
def test_version_key(name, expected_key):
    assert cloud_impact._version_key(name) == expected_key


def test_version_key_orders_opus_family_with_4_8_last():
    names = [
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-opus-4-5-20251101",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
    ]
    assert max(names, key=cloud_impact._version_key) == "claude-opus-4-8"


def test_version_key_no_digits_returns_empty_tuple():
    assert cloud_impact._version_key("claude-opus-latest") == ()


class _FakeProvider:
    def __init__(self, value):
        self.value = value


class _FakeModel:
    def __init__(self, provider, name):
        self.provider = _FakeProvider(provider)
        self.name = name


class _FakeRegistry:
    def __init__(self, models):
        self._models = models

    def list_models(self):
        return self._models

    def find_model(self, provider, model_name):
        return None


def test_auto_alias_warns_on_unversioned_candidate(monkeypatch, capsys):
    fake_registry = _FakeRegistry(
        [
            _FakeModel("anthropic", "claude-opus-latest"),
            _FakeModel("anthropic", "claude-opus-4-8"),
        ]
    )
    monkeypatch.setattr(cloud_impact, "_model_registry", fake_registry)
    resolved = cloud_impact._auto_alias("anthropic", "claude-opus-4-9")
    assert resolved == "claude-opus-4-8"
    err = capsys.readouterr().err
    assert "has no parseable version suffix" in err
    assert "claude-opus-latest" in err


def test_resolve_model_exact_registered_passthrough(capsys):
    resolved = cloud_impact.resolve_model("anthropic", "claude-opus-4-8")
    assert resolved == "claude-opus-4-8"
    assert (
        capsys.readouterr().err == ""
    )  # no "Note:" - exact match, no fallback consulted


def test_resolve_model_manual_pin_override(monkeypatch, capsys):
    monkeypatch.setitem(
        cloud_impact.MODEL_ALIASES, "claude-test-pin", "claude-opus-4-8"
    )
    resolved = cloud_impact.resolve_model("anthropic", "claude-test-pin")
    assert resolved == "claude-opus-4-8"
    assert "pinned alias" in capsys.readouterr().err


def test_resolve_model_auto_derives_family_fallback(capsys):
    # claude-opus-4-9 has never existed - proves this isn't just reproducing a
    # hardcoded case, it generalizes to genuinely new models.
    resolved = cloud_impact.resolve_model("anthropic", "claude-opus-4-9")
    assert resolved == "claude-opus-4-8"
    assert "auto-resolved" in capsys.readouterr().err


def test_resolve_model_no_family_match_passthrough():
    # zero claude-fable-* entries exist in the registry - nothing to extrapolate from
    resolved = cloud_impact.resolve_model("anthropic", "claude-fable-5")
    assert resolved == "claude-fable-5"


def test_resolve_model_falls_through_when_registry_unavailable(monkeypatch):
    monkeypatch.setattr(cloud_impact, "_model_registry", None)
    resolved = cloud_impact.resolve_model("anthropic", "claude-opus-4-9")
    assert resolved == "claude-opus-4-9"  # no registry to check or auto-derive from


class TestProviderConfigMapDefensiveFallback:
    """A broken/removed PROVIDER_CONFIG_MAP must degrade gracefully, not crash
    log_estimate() (and, by extension, the Stop hook, which calls it every turn)."""

    def test_empty_map_simulates_import_failure(self, monkeypatch, temp_db):
        monkeypatch.setattr(cloud_impact, "PROVIDER_CONFIG_MAP", {})
        row = cloud_impact.log_estimate(
            "test", "anthropic", "claude-opus-4-8", 100, 2.0
        )
        assert row["country_name"] == "unspecified"
        assert row["pue"] == 0
        assert row["wue"] == 0

    def test_broken_attributes_caught_gracefully(self, monkeypatch, temp_db, capsys):
        monkeypatch.setattr(
            cloud_impact, "PROVIDER_CONFIG_MAP", {"anthropic": object()}
        )
        row = cloud_impact.log_estimate(
            "test", "anthropic", "claude-opus-4-8", 100, 2.0
        )
        assert row["country_name"] == "unspecified"
        assert "structure changed" in capsys.readouterr().err

    def test_normal_path_unaffected_by_the_defensive_wrapping(self, temp_db):
        row = cloud_impact.log_estimate(
            "test", "anthropic", "claude-opus-4-8", 100, 2.0
        )
        assert row["country_name"] == "United States"
        assert row["pue"] > 0


def test_log_estimate_writes_non_fabricated_markers(temp_db):
    row = cloud_impact.log_estimate(
        "test-label", "anthropic", "claude-opus-4-8", 100, 2.0
    )
    assert row["on_cloud"] == "N"
    assert row["tracking_mode"] == "estimated"
    assert row["codecarbon_version"] == "ecologits"
    assert row["project_name"] == "test-label:estimated"


def test_log_estimate_raises_for_truly_unresolvable_model(temp_db):
    with pytest.raises(cloud_impact.NoEstimateAvailable):
        cloud_impact.log_estimate("test", "anthropic", "claude-fable-5", 100, 2.0)


def test_log_estimate_handles_providers_returning_plain_floats(temp_db):
    # mistralai/cohere return plain floats for energy/gwp, not RangeValue -
    # mean_range() alone crashes on these; log_estimate must use to_scalar().
    row = cloud_impact.log_estimate("test", "mistralai", "codestral-2405", 100, 2.0)
    assert row["energy_consumed"] > 0
    assert row["emissions"] > 0
