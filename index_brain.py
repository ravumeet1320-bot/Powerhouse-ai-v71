from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple


def sf(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def pct_change(ltp: float, close: float) -> float:
    return ((ltp - close) / close * 100.0) if ltp and close else 0.0


# High-impact constituents used by the live "Index Brain".  We intentionally
# track the biggest weights rather than pretending to recreate the entire index.
# Weights are data, not trading rules, and can be refreshed without changing the
# AI engine.  They are labelled with their source/as-of date in the UI/API.
INDEX_UNIVERSES: Dict[str, Dict[str, Any]] = {
    "NIFTY": {
        "label": "NIFTY 50",
        "index_key": "NSE_INDEX|Nifty 50",
        "weights_as_of": "2026-05-29",
        "weights_source": "NSE Indices NIFTY 50 factsheet",
        "stocks": [
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "weight": 10.56, "sector": "Financials"},
            {"symbol": "ICICIBANK", "name": "ICICI Bank", "weight": 8.32, "sector": "Financials"},
            {"symbol": "RELIANCE", "name": "Reliance", "weight": 8.27, "sector": "Energy"},
            {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "weight": 5.20, "sector": "Telecom"},
            {"symbol": "LT", "name": "L&T", "weight": 4.43, "sector": "Industrials"},
            {"symbol": "INFY", "name": "Infosys", "weight": 3.77, "sector": "IT"},
            {"symbol": "SBIN", "name": "SBI", "weight": 3.71, "sector": "Financials"},
            {"symbol": "AXISBANK", "name": "Axis Bank", "weight": 3.42, "sector": "Financials"},
            {"symbol": "KOTAKBANK", "name": "Kotak Bank", "weight": 2.62, "sector": "Financials"},
            {"symbol": "ITC", "name": "ITC", "weight": 2.56, "sector": "FMCG"},
        ],
    },
    "BANKNIFTY": {
        "label": "BANK NIFTY",
        "index_key": "NSE_INDEX|Nifty Bank",
        "weights_as_of": "2026-08-31",
        "weights_source": "NSE Indices NIFTY Bank factsheet",
        "stocks": [
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "weight": 17.02, "sector": "Private Bank"},
            {"symbol": "ICICIBANK", "name": "ICICI Bank", "weight": 14.86, "sector": "Private Bank"},
            {"symbol": "SBIN", "name": "SBI", "weight": 10.27, "sector": "PSU Bank"},
            {"symbol": "KOTAKBANK", "name": "Kotak Bank", "weight": 9.88, "sector": "Private Bank"},
            {"symbol": "AXISBANK", "name": "Axis Bank", "weight": 9.20, "sector": "Private Bank"},
            {"symbol": "FEDERALBNK", "name": "Federal Bank", "weight": 7.15, "sector": "Private Bank"},
            {"symbol": "INDUSINDBK", "name": "IndusInd Bank", "weight": 5.45, "sector": "Private Bank"},
            {"symbol": "AUBANK", "name": "AU Small Finance", "weight": 4.82, "sector": "Small Finance Bank"},
            {"symbol": "IDFCFIRSTB", "name": "IDFC First Bank", "weight": 4.68, "sector": "Private Bank"},
            {"symbol": "BANKBARODA", "name": "Bank of Baroda", "weight": 3.48, "sector": "PSU Bank"},
        ],
    },
    "SENSEX": {
        "label": "S&P BSE SENSEX",
        "index_key": "BSE_INDEX|SENSEX",
        "weights_as_of": "2026-04-30",
        "weights_source": "BSE Indices SENSEX factsheet (30 Apr 2026)",
        "stocks": [
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "weight": 12.91, "sector": "Financial Services"},
            {"symbol": "RELIANCE", "name": "Reliance Industries", "weight": 10.64, "sector": "Energy"},
            {"symbol": "ICICIBANK", "name": "ICICI Bank", "weight": 9.93, "sector": "Financial Services"},
            {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "weight": 5.91, "sector": "Telecommunication"},
            {"symbol": "LT", "name": "L&T", "weight": 5.16, "sector": "Industrials"},
            {"symbol": "SBIN", "name": "SBI", "weight": 4.87, "sector": "Financial Services"},
            {"symbol": "INFY", "name": "Infosys", "weight": 4.53, "sector": "Information Technology"},
            {"symbol": "AXISBANK", "name": "Axis Bank", "weight": 3.98, "sector": "Financial Services"},
            {"symbol": "ITC", "name": "ITC", "weight": 3.34, "sector": "FMCG"},
            {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank", "weight": 3.09, "sector": "Financial Services"},
        ],
    },
}


def all_symbols() -> List[str]:
    out: List[str] = []
    seen = set()
    for cfg in INDEX_UNIVERSES.values():
        for s in cfg["stocks"]:
            sym = str(s["symbol"])
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def _sector_pulse(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, float]] = {}
    for s in stocks:
        if not s.get("live"):
            continue
        sec = str(s.get("sector") or "Other")
        b = buckets.setdefault(sec, {"weight": 0.0, "weighted": 0.0, "impact": 0.0})
        w, ch = sf(s.get("weight")), sf(s.get("change_pct"))
        b["weight"] += w
        b["weighted"] += w * ch
        b["impact"] += sf(s.get("contribution_pct"))
    rows = []
    for sec, b in buckets.items():
        move = b["weighted"] / b["weight"] if b["weight"] else 0.0
        rows.append({
            "sector": sec,
            "tracked_weight": round(b["weight"], 2),
            "weighted_move_pct": round(move, 3),
            "contribution_pct": round(b["impact"], 4),
            "state": "BULL" if move > 0.08 else "BEAR" if move < -0.08 else "NEUTRAL",
        })
    rows.sort(key=lambda x: abs(sf(x.get("contribution_pct"))), reverse=True)
    return rows


def analyse_index_brains(
    runtime_by_symbol: Dict[str, Dict[str, Any]],
    index_levels: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for code, cfg in INDEX_UNIVERSES.items():
        level = index_levels.get(code) or {}
        idx_ltp = sf(level.get("ltp"))
        idx_cp = sf(level.get("cp"))
        idx_change = pct_change(idx_ltp, idx_cp)
        stocks: List[Dict[str, Any]] = []
        tracked_weight = sum(sf(x.get("weight")) for x in cfg["stocks"])
        live_weight = bull_w = bear_w = neutral_w = 0.0
        weighted_sum = 0.0
        contribution = 0.0

        for spec in cfg["stocks"]:
            rt = runtime_by_symbol.get(spec["symbol"]) or {}
            ltp, cp = sf(rt.get("ltp")), sf(rt.get("cp"))
            live = bool(ltp and cp)
            ch = pct_change(ltp, cp) if live else 0.0
            w = sf(spec.get("weight"))
            impact = (w / 100.0) * ch if live else 0.0
            state = "BULL" if ch > 0.08 else "BEAR" if ch < -0.08 else "NEUTRAL"
            if live:
                live_weight += w
                weighted_sum += w * ch
                contribution += impact
                if state == "BULL": bull_w += w
                elif state == "BEAR": bear_w += w
                else: neutral_w += w
            stocks.append({
                "symbol": spec["symbol"], "name": spec["name"], "sector": spec["sector"],
                "weight": round(w, 2), "ltp": round(ltp, 2) if ltp else None,
                "close": round(cp, 2) if cp else None, "change_pct": round(ch, 3),
                "contribution_pct": round(impact, 4),
                "approx_points": round(idx_ltp * impact / 100.0, 2) if idx_ltp else None,
                "state": state, "live": live,
                "momentum_score": round(clamp(50 + 50 * math.tanh(ch / 0.55), 0, 100), 1) if live else 50.0,
            })

        weighted_move = weighted_sum / live_weight if live_weight else 0.0
        coverage = 100 * live_weight / tracked_weight if tracked_weight else 0.0
        directional_weight = bull_w + bear_w
        agreement = 100 * max(bull_w, bear_w) / directional_weight if directional_weight else 50.0
        direction_score = math.tanh(weighted_move / 0.34) if live_weight else 0.0
        direction_score *= (0.62 + 0.38 * agreement / 100.0)
        direction_score = clamp(direction_score, -1, 1)
        direction = "BULL" if direction_score > 0.16 else "BEAR" if direction_score < -0.16 else "NEUTRAL"

        # A first-order contribution proxy: weight × constituent return.  It is
        # deliberately labelled approximate because the untracked remainder is
        # assumed flat and no index divisor reconstruction is attempted.
        approx_points = idx_ltp * contribution / 100.0 if idx_ltp else 0.0
        sign_conflict = bool(idx_change and weighted_move and (idx_change > 0) != (weighted_move > 0))
        divergence_gap = abs(idx_change - weighted_move) if idx_change else 0.0
        divergence = clamp((45 if sign_conflict else 0) + 55 * clamp(divergence_gap / 0.85, 0, 1), 0, 100)
        strength = clamp(abs(direction_score) * 100, 0, 100)
        confirmation = clamp(
            .48 * strength + .30 * agreement + .22 * coverage - .25 * divergence,
            0, 100,
        )
        fragility = clamp(100 - confirmation + .35 * divergence, 0, 100)

        by_impact = sorted([s for s in stocks if s["live"]], key=lambda x: sf(x.get("contribution_pct")), reverse=True)
        leaders = by_impact[:3]
        drags = list(reversed(by_impact[-3:])) if by_impact else []
        top3 = sorted([s for s in stocks if s["live"]], key=lambda x: sf(x.get("weight")), reverse=True)[:3]
        top3_bull = sum(1 for s in top3 if s["state"] == "BULL")
        top3_bear = sum(1 for s in top3 if s["state"] == "BEAR")

        if sign_conflict:
            divergence_label = "INDEX / HEAVYWEIGHT DIVERGENCE"
        elif divergence > 48:
            divergence_label = "WEAK CONFIRMATION"
        else:
            divergence_label = "ALIGNED"

        result[code] = {
            "code": code, "label": cfg["label"],
            "weights_as_of": cfg["weights_as_of"], "weights_source": cfg["weights_source"],
            "tracked_weight_pct": round(tracked_weight, 2), "live_weight_pct": round(live_weight, 2),
            "coverage_pct": round(coverage, 1),
            "index_ltp": round(idx_ltp, 2) if idx_ltp else None,
            "index_change_pct": round(idx_change, 3),
            "weighted_heavy_move_pct": round(weighted_move, 3),
            "tracked_contribution_pct": round(contribution, 4),
            "approx_contribution_points": round(approx_points, 2) if idx_ltp else None,
            "bull_weight_pct": round(bull_w, 2), "bear_weight_pct": round(bear_w, 2), "neutral_weight_pct": round(neutral_w, 2),
            "agreement_pct": round(agreement, 1), "direction_score": round(direction_score, 4),
            "direction": direction, "confirmation_score": round(confirmation, 1),
            "fragility_risk": round(fragility, 1), "divergence_risk": round(divergence, 1),
            "divergence_label": divergence_label,
            "top3_consensus": {"bull": top3_bull, "bear": top3_bear, "tracked": len(top3)},
            "leaders": leaders, "drags": drags,
            "sectors": _sector_pulse(stocks), "stocks": stocks,
        }
    return result
