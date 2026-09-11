from __future__ import annotations
from datetime import datetime
from math import isfinite


def _n(v, d=0.0):
    try:
        x = float(v)
        return x if isfinite(x) else d
    except Exception:
        return d


def _present(v):
    if v is None or v == "":
        return False
    try:
        return isfinite(float(v))
    except Exception:
        return False


def _clamp(v, a=0.0, b=100.0):
    return max(a, min(b, v))


def _weighted_center(factors):
    """Return 0..100 score with missing factors excluded, not treated as zero."""
    valid = [(float(value), float(weight)) for value, weight, ok in factors if ok and weight > 0]
    if not valid:
        return None
    den = sum(w for _, w in valid)
    return 50 + sum(v * w for v, w in valid) / den


def _build_up(price_pct, delta_oi, delta_ok):
    """Classify price/OI relationship. This is a market-structure label, not a trade call."""
    if not delta_ok or not _present(price_pct):
        return "N/A"
    p = _n(price_pct)
    d = _n(delta_oi)
    # Small changes are treated as noise to avoid false precision.
    if abs(p) < 0.08 or abs(d) < 0.01:
        return "NEUTRAL"
    if p > 0 and d > 0:
        return "LONG BUILDUP"
    if p < 0 and d > 0:
        return "SHORT BUILDUP"
    if p > 0 and d < 0:
        return "SHORT COVERING"
    if p < 0 and d < 0:
        return "LONG UNWINDING"
    return "NEUTRAL"


def _quality_grade(score):
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "INSUFFICIENT"


def analyse_smart_money(snapshot: dict) -> dict:
    """Read-only market-footprint intelligence from anonymous exchange data.

    v12 retains and extends:
    - explicit data-quality scoring and missing-data semantics,
    - option price + ΔOI build-up classification,
    - strike-battle map for ATM-area contracts,
    - premium response diagnostics,
    - cross-index alignment context,
    while preserving the rule that anonymous data cannot identify a specific FII/DII.
    """
    rows = snapshot.get("option_data") or []
    active = str(snapshot.get("active_underlying") or "NIFTY").upper()
    spot = _n(snapshot.get("spot"))

    call_vol = sum(_n(r.get("cvol")) for r in rows)
    put_vol = sum(_n(r.get("pvol")) for r in rows)
    call_oi = sum(_n(r.get("coi")) for r in rows)
    put_oi = sum(_n(r.get("poi")) for r in rows)

    cdoi_vals, pdoi_vals = [], []
    for r in rows:
        cv = r.get("cchg") if _present(r.get("cchg")) else r.get("cdoi")
        pv = r.get("pchg") if _present(r.get("pchg")) else r.get("pdoi")
        if _present(cv): cdoi_vals.append(_n(cv))
        if _present(pv): pdoi_vals.append(_n(pv))
    delta_available = bool(rows) and len(cdoi_vals) >= max(1, len(rows)//3) and len(pdoi_vals) >= max(1, len(rows)//3)
    call_doi, put_doi = sum(cdoi_vals), sum(pdoi_vals)

    vol_available = (call_vol + put_vol) > 0
    oi_available = (call_oi + put_oi) > 0
    vol_bias = (put_vol - call_vol) / max(put_vol + call_vol, 1) if vol_available else 0.0
    oi_bias = (put_oi - call_oi) / max(put_oi + call_oi, 1) if oi_available else 0.0
    doi_den = abs(put_doi) + abs(call_doi)
    doi_bias = (put_doi - call_doi) / doi_den if delta_available and doi_den > 0 else 0.0

    ib = snapshot.get("index_brain") or {}
    brain = ib.get(active) or {}
    heavy_available = bool(brain) and _n(brain.get("coverage_pct")) >= 20
    heavy_dir = _clamp(_n(brain.get("direction_score")), -1, 1) if heavy_available else 0.0
    divergence = _n(brain.get("divergence_risk")) if heavy_available else max(
        _n((ib.get("NIFTY") or {}).get("divergence_risk")),
        _n((ib.get("BANKNIFTY") or {}).get("divergence_risk")),
    )

    score = _weighted_center([
        (vol_bias * 100, 22, vol_available),
        (oi_bias * 100, 18, oi_available),
        (doi_bias * 100, 15, delta_available),
        (heavy_dir * 100, 25, heavy_available),
    ])
    factor_count = sum([vol_available, oi_available, delta_available, heavy_available])
    coverage = round(factor_count / 4 * 100, 1)
    if score is None or factor_count < 2:
        direction, score = "INSUFFICIENT DATA", 50.0
    elif score >= 60:
        direction = "BULLISH FOOTPRINT"
    elif score <= 40:
        direction = "BEARISH FOOTPRINT"
    else:
        direction = "MIXED / ABSORPTION"
    score = _clamp(score)

    # Contract-level classifications and strike battle map.
    contracts = []
    premium_up = premium_down = premium_valid = 0
    for r in rows:
        strike = _n(r.get("s"))
        for side, vol, oi, doi_key, ltp_key, pp_key in (
            ("CE", "cvol", "coi", "cchg", "cltp", "cp"),
            ("PE", "pvol", "poi", "pchg", "pltp", "pp"),
        ):
            doi_ok = _present(r.get(doi_key))
            pp_ok = _present(r.get(pp_key))
            price_pct = _n(r.get(pp_key)) if pp_ok else None
            doi = _n(r.get(doi_key)) if doi_ok else None
            buildup = _build_up(price_pct, doi, doi_ok)
            if pp_ok:
                premium_valid += 1
                if price_pct > .08: premium_up += 1
                elif price_pct < -.08: premium_down += 1
            activity = (max(_n(r.get(vol)), 0) ** .5) + (max(_n(r.get(oi)), 0) ** .5) + ((abs(_n(doi)) ** .5) if doi_ok else 0)
            contracts.append({
                "strike": strike, "side": side, "volume": _n(r.get(vol)), "oi": _n(r.get(oi)),
                "delta_oi": doi if doi_ok else None, "ltp": _n(r.get(ltp_key)),
                "price_change_pct": price_pct, "buildup": buildup, "activity_score": activity,
            })

    whale = sorted(contracts, key=lambda x: x["activity_score"], reverse=True)[:8]
    # ATM-area battle: nearest 7 strikes, each CE and PE.
    strike_rows = sorted(rows, key=lambda r: abs(_n(r.get("s")) - spot))[:7] if spot else rows[:7]
    battle = []
    for r in sorted(strike_rows, key=lambda r: _n(r.get("s"))):
        battle.append({
            "strike": _n(r.get("s")),
            "ce": {"oi": _n(r.get("coi")), "delta_oi": _n(r.get("cchg")) if _present(r.get("cchg")) else None,
                   "price_change_pct": _n(r.get("cp")) if _present(r.get("cp")) else None,
                   "buildup": _build_up(r.get("cp"), r.get("cchg"), _present(r.get("cchg")))},
            "pe": {"oi": _n(r.get("poi")), "delta_oi": _n(r.get("pchg")) if _present(r.get("pchg")) else None,
                   "price_change_pct": _n(r.get("pp")) if _present(r.get("pp")) else None,
                   "buildup": _build_up(r.get("pp"), r.get("pchg"), _present(r.get("pchg")))},
        })

    call_wall = max(rows, key=lambda r: _n(r.get("coi")), default={})
    put_wall = max(rows, key=lambda r: _n(r.get("poi")), default={})
    call_wall_s = _n(call_wall.get("s")) or None
    put_wall_s = _n(put_wall.get("s")) or None

    activity = call_vol + put_vol
    absorption = _clamp((100 - abs(score - 50) * 2) * 0.55 + min(45, activity / 250000)) if rows else 0
    trap = _clamp(divergence * 0.65 + absorption * 0.35)

    # Data integrity: completeness is independent of bullish/bearish direction.
    nrows = max(len(rows), 1)
    ltp_cov = sum(1 for r in rows if _present(r.get("cltp")) and _present(r.get("pltp"))) / nrows
    greek_cov = sum(1 for r in rows if _present(r.get("c_delta")) and _present(r.get("p_delta"))) / nrows
    premium_cov = sum(1 for r in rows if _present(r.get("cp")) and _present(r.get("pp"))) / nrows
    core = (25 if rows else 0) + (20 if vol_available else 0) + (20 if oi_available else 0) + (15 if delta_available else 0)
    quality = _clamp(core + 8 * ltp_cov + 6 * greek_cov + 6 * premium_cov)
    quality_grade = _quality_grade(quality)

    # Cross-index context from configured Index Brain universes only.
    cross = {}
    signed = []
    for code in ("NIFTY", "BANKNIFTY", "SENSEX"):
        b = ib.get(code) or {}
        avail = bool(b) and _n(b.get("coverage_pct")) >= 20
        ds = _n(b.get("direction_score")) if avail else None
        cross[code] = {
            "available": avail,
            "direction": b.get("direction") if avail else "N/A",
            "confirmation_score": _n(b.get("confirmation_score")) if avail else None,
            "direction_score": ds,
            "coverage_pct": _n(b.get("coverage_pct")) if avail else None,
        }
        if ds is not None:
            signed.append(ds)
    cross_alignment = None
    if len(signed) >= 2:
        same_sign = all(x >= 0 for x in signed) or all(x <= 0 for x in signed)
        cross_alignment = round(_clamp(50 + (sum(abs(x) for x in signed) / len(signed) * 50) * (1 if same_sign else -1)), 1)

    premium_response = None
    if premium_valid:
        premium_response = {
            "up_contracts": premium_up,
            "down_contracts": premium_down,
            "flat_contracts": premium_valid - premium_up - premium_down,
            "coverage_pct": round(premium_valid / max(len(contracts), 1) * 100, 1),
        }

    now = datetime.now()
    mins = now.hour * 60 + now.minute
    if mins < 9 * 60 + 15: phase = "PRE-OPEN"
    elif mins < 10 * 60: phase = "OPENING DISCOVERY"
    elif mins < 13 * 60: phase = "MID-SESSION"
    elif mins < 14 * 60 + 30: phase = "POSITIONING"
    elif mins < 15 * 60 + 30: phase = "CLOSING FLOW"
    else: phase = "AFTER MARKET"

    return {
        "engine": "Big Money Footprints v12",
        "active_underlying": active,
        "direction": direction,
        "footprint_score": round(score, 1),
        "bull_pressure": round(score, 1),
        "bear_pressure": round(100 - score, 1),
        "option_volume_bias": round(vol_bias * 100, 1) if vol_available else None,
        "option_oi_bias": round(oi_bias * 100, 1) if oi_available else None,
        "delta_oi_bias": round(doi_bias * 100, 1) if delta_available else None,
        "delta_oi_available": delta_available,
        "delta_oi_source": "Upstox prev_oi → current OI change" if delta_available else "unavailable",
        "heavyweight_confirmation": round(_clamp(50 + heavy_dir * 50), 1) if heavy_available else None,
        "heavyweight_available": heavy_available,
        "input_coverage": coverage,
        "data_quality": round(quality, 1),
        "data_quality_grade": quality_grade,
        "data_integrity": {
            "rows": len(rows), "ltp_coverage_pct": round(ltp_cov * 100, 1),
            "greeks_coverage_pct": round(greek_cov * 100, 1), "premium_change_coverage_pct": round(premium_cov * 100, 1),
        },
        "input_status": {"volume": vol_available, "oi": oi_available, "delta_oi": delta_available, "active_index_heavyweights": heavy_available},
        "divergence_risk": round(divergence, 1),
        "absorption_risk": round(absorption, 1),
        "trap_risk": round(trap, 1),
        "call_wall": call_wall_s,
        "put_wall": put_wall_s,
        "whale_strikes": whale,
        "strike_battle": battle,
        "premium_response": premium_response,
        "cross_index": cross,
        "cross_index_alignment": cross_alignment,
        "session_phase": phase,
        "data_scope": "LIVE MARKET FOOTPRINT PROXY",
        "identity_warning": "Anonymous exchange activity cannot identify a specific FII/DII. NSE published OI Spurts is shown separately as an official market-data layer.",
        "official_fii_dii": "NOT CLAIMED AS REAL-TIME FII/DII IDENTITY",
    }
