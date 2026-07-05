#!/usr/bin/env python3
"""Estimate energy/CO2 impact of a cloud LLM call using EcoLogits, and log it
into the same SQLite database that CodeCarbon writes to (carbon_run.py), so
carbonboard can show measured (local) and estimated (cloud) rows side by side
once exported to CSV (see storage.export_to_csv).

Usage:
    cloud_impact.py --label claude-cloud --provider anthropic \
        --model claude-sonnet-5 --output-tokens 842 --latency 6.4

Cloud rows are tagged tracking_mode=estimated, on_cloud=N, cloud_provider=<provider>,
codecarbon_version=ecologits, so they're distinguishable from real CodeCarbon rows.
"""

import argparse
import os
import re
import sys
import uuid
from datetime import datetime, timezone

from ecologits.tracers.utils import llm_impacts

# PROVIDER_CONFIG_MAP is an EcoLogits internal (not part of its documented public
# API) that we reach into for datacenter location/PUE/WUE enrichment. Import
# defensively so a future EcoLogits release renaming/removing it degrades to the
# existing "unspecified" fallback below instead of crashing every log_estimate()
# call (including the Stop hook, which runs on every turn).
try:
    from ecologits.tracers.utils import PROVIDER_CONFIG_MAP
except ImportError:
    PROVIDER_CONFIG_MAP = {}

# Also not documented public API - same defensive treatment. Used only for the
# auto-alias fallback in resolve_model(); if unavailable, that fallback simply
# never fires (still have the exact-match and manual MODEL_ALIASES paths).
try:
    from ecologits.model_repository import models as _model_registry
except ImportError:
    _model_registry = None

from storage import FIELDNAMES, insert_row

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ISO 3166-1 alpha-3 -> readable name, for the datacenter locations that show
# up in ecologits.tracers.utils.PROVIDER_CONFIG_MAP.
ISO3_TO_NAME = {
    "USA": "United States",
    "SWE": "Sweden",
}

# Manual override/pin for specific live model IDs, checked before auto-derivation
# below - only needed if the auto-derived choice isn't the one you want. Not
# required for every new model anymore (see resolve_model()).
MODEL_ALIASES = {}

_FAMILY_PATTERN = re.compile(r"claude-(opus|sonnet|haiku|fable)")
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def _version_key(name: str) -> tuple:
    """(4,8) for 'claude-opus-4-8', (4,5) for 'claude-opus-4-5-20251101' (date
    suffix stripped first - not every entry has one, e.g. 'claude-opus-4-6').
    Verified against the real registry: naively preferring larger parameter
    counts gets this backwards (EcoLogits' newer Opus snapshots are estimated
    *smaller* than older ones), so this compares version numbers instead.
    """
    # A name with no trailing digits at all (e.g. a hypothetical
    # "claude-opus-latest") returns (), which sorts as the lowest possible
    # tuple - it would silently lose to any versioned sibling in
    # max(candidates, key=_version_key), not necessarily correctly. No such
    # name exists in the registry today; rather than guess at ordering for a
    # naming pattern that doesn't exist, _auto_alias() below surfaces this
    # case as a stderr warning if it ever occurs.
    name = _DATE_SUFFIX.sub("", name)
    nums = []
    for segment in reversed(name.split("-")):
        if segment.isdigit():
            nums.insert(0, int(segment))
        else:
            break
    return tuple(nums)


def _is_registered(provider: str, model: str) -> bool:
    if _model_registry is None:
        return False
    try:
        return (
            _model_registry.find_model(provider=provider, model_name=model) is not None
        )
    except Exception:
        return False


def _auto_alias(provider: str, model: str) -> str | None:
    if _model_registry is None:
        return None
    match = _FAMILY_PATTERN.search(model)
    if not match:
        return None
    family_prefix = f"claude-{match.group(1)}"
    try:
        candidates = [
            m.name
            for m in _model_registry.list_models()
            if m.provider.value == provider and family_prefix in m.name
        ]
    except Exception:
        return None
    if not candidates:
        return None
    unversioned = [c for c in candidates if _version_key(c) == ()]
    if unversioned:
        print(
            f"Warning: {', '.join(unversioned)} has no parseable version "
            "suffix; _version_key() treats it as the lowest-versioned "
            "candidate, so it will never be auto-selected by max(). If it "
            "should take priority, add a manual entry to MODEL_ALIASES.",
            file=sys.stderr,
        )
    return max(candidates, key=_version_key)


def resolve_model(provider: str, model: str) -> str:
    """Resolve a live model id to one EcoLogits has registered.

    Order: exact name (works with zero maintenance once EcoLogits' registry
    catches up) -> manual MODEL_ALIASES pin -> auto-derived same-family
    fallback (highest version-numbered registered sibling). Returns the input
    unchanged if nothing resolves - the caller's llm_impacts() call surfaces
    the real "not registered" error in that case.
    """
    if _is_registered(provider, model):
        return model
    if model in MODEL_ALIASES:
        print(
            f"Note: {model} not in EcoLogits registry, using pinned alias "
            f"{MODEL_ALIASES[model]}",
            file=sys.stderr,
        )
        return MODEL_ALIASES[model]
    auto = _auto_alias(provider, model)
    if auto:
        print(
            f"Note: {model} not in EcoLogits registry, auto-resolved to "
            f"same-family match {auto}",
            file=sys.stderr,
        )
        return auto
    return model


def mean_range(range_value) -> float:
    return (range_value.min + range_value.max) / 2


def to_scalar(value) -> float:
    """PROVIDER_CONFIG_MAP gives some providers a RangeValue, others a plain float."""
    return mean_range(value) if hasattr(value, "min") else float(value)


class NoEstimateAvailable(Exception):
    pass


def log_estimate(
    label: str, provider: str, model: str, output_tokens: int, latency: float
) -> dict:
    """Compute an EcoLogits impact estimate and insert it into the emissions DB.

    Raises NoEstimateAvailable if the (possibly aliased) model isn't in
    EcoLogits' registry. Returns the row that was written.
    """
    resolved_model = resolve_model(provider, model)
    result = llm_impacts(
        provider=provider,
        model_name=resolved_model,
        output_token_count=output_tokens,
        request_latency=latency,
    )

    if result.errors:
        raise NoEstimateAvailable(
            f"No estimate available for {provider}/{model} (resolved: {resolved_model}): {result.errors}"
        )

    energy_kwh = to_scalar(result.energy.value)
    emissions_kg = to_scalar(result.gwp.value)

    iso3 = country_name = "unspecified"
    pue = wue = 0
    provider_config = (
        PROVIDER_CONFIG_MAP.get(provider)
        if hasattr(PROVIDER_CONFIG_MAP, "get")
        else None
    )
    if provider_config is not None:
        try:
            iso3 = provider_config.datacenter_location
            country_name = ISO3_TO_NAME.get(iso3, iso3)
            pue = to_scalar(provider_config.datacenter_pue)
            wue = to_scalar(provider_config.datacenter_wue)
        except AttributeError:
            print(
                "Note: EcoLogits' internal PROVIDER_CONFIG_MAP structure changed; "
                "falling back to unspecified location/PUE/WUE",
                file=sys.stderr,
            )
            iso3 = country_name = "unspecified"
            pue = wue = 0

    row = {name: "" for name in FIELDNAMES}
    row.update(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_name": f"{label}:estimated",
            "run_id": str(uuid.uuid4()),
            "experiment_id": "ecologits-estimate",
            "duration": latency,
            "emissions": emissions_kg,
            "emissions_rate": emissions_kg / latency if latency else 0,
            "cpu_power": 0,
            "gpu_power": 0,
            "ram_power": 0,
            "cpu_energy": 0,
            "gpu_energy": 0,
            "ram_energy": 0,
            "energy_consumed": energy_kwh,
            "water_consumed": 0,
            "country_name": country_name,
            "country_iso_code": iso3,
            "region": "unspecified",
            "cloud_provider": provider,
            "codecarbon_version": "ecologits",
            "cpu_count": 0,
            "gpu_count": 0,
            "ram_total_size": 0,
            "tracking_mode": "estimated",
            "cpu_utilization_percent": 0,
            "gpu_utilization_percent": 0,
            "ram_utilization_percent": 0,
            "ram_used_gb": 0,
            # "Y" would route this into carbonboard's GCP-only Cloud Emissions
            # Comparison widget, which crashes for any other provider.
            "on_cloud": "N",
            "pue": pue,
            "wue": wue,
        }
    )

    insert_row(row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--label", required=True, help="project_name prefix, e.g. 'claude-cloud'"
    )
    parser.add_argument("--provider", required=True, help="e.g. anthropic, openai")
    parser.add_argument(
        "--model", required=True, help="live model id, e.g. claude-sonnet-5"
    )
    parser.add_argument("--output-tokens", type=int, required=True)
    parser.add_argument(
        "--latency", type=float, required=True, help="request latency in seconds"
    )
    args = parser.parse_args()

    try:
        row = log_estimate(
            args.label, args.provider, args.model, args.output_tokens, args.latency
        )
    except NoEstimateAvailable as e:
        print(str(e), file=sys.stderr)
        return 1

    print(
        f"Logged estimate: {args.label} model={args.model} "
        f"energy={float(row['energy_consumed']):.6f}kWh emissions={float(row['emissions']):.6f}kgCO2eq"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
