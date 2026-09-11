from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from index_brain import analyse_index_brains


def demo_snapshot() -> Dict[str, Any]:
    """Deterministic market-like snapshot for UI preview only.

    Values are synthetic and deliberately labelled demo by the API/UI.
    """
    spot = 25242.35
    vwap = 25219.80
    strikes = list(range(24950, 25551, 50))
    rows: List[Dict[str, Any]] = []
    for i, s in enumerate(strikes):
        dist = (s - spot) / 50.0
        atm = math.exp(-abs(dist) / 3.2)
        call_delta = max(.08, min(.92, .52 - dist * .075))
        put_delta = -(1 - call_delta)
        base_vol = 85000 + 240000 * atm
        call_vol = base_vol * (1.08 + max(-dist, 0) * .03)
        put_vol = base_vol * (.86 + max(dist, 0) * .025)
        call_oi = 9.5 + (9 - abs(dist - 3)) * .65 if abs(dist - 3) < 9 else 7.5
        put_oi = 10.0 + (9 - abs(dist + 2)) * .72 if abs(dist + 2) < 9 else 7.8
        call_oi = max(call_oi, 4.2)
        put_oi = max(put_oi, 4.2)
        intrinsic_c = max(spot - s, 0)
        intrinsic_p = max(s - spot, 0)
        time_val = max(20, 116 - abs(dist) * 13)
        cltp = intrinsic_c + time_val
        pltp = intrinsic_p + time_val * .94
        spread_c = max(.25, cltp * .0045)
        spread_p = max(.25, pltp * .0048)
        cv1 = 1.0 + atm * .85 + (0.30 if -1 <= dist <= 1 else 0)
        pv1 = 1.0 + atm * .42
        cprem = 1.35 + atm * 1.7 - max(dist, 0) * .10
        pprem = -0.75 + max(dist, 0) * .08
        rows.append({
            "s": float(s),
            "coi": round(call_oi, 2), "cchg": round(0.18 + atm * .12 - max(-dist, 0) * .02, 3),
            "cvol": int(call_vol), "cltp": round(cltp, 2), "cp": round(0.35 - dist * .08, 3), "civ": round(17.8 + abs(dist) * .42, 2),
            "poi": round(put_oi, 2), "pchg": round(0.42 + atm * .30 + max(-dist, 0) * .03, 3),
            "pvol": int(put_vol), "pltp": round(pltp, 2), "pp": round(-0.18 + dist * .07, 3), "piv": round(18.4 + abs(dist) * .47, 2),
            "cbid": round(cltp - spread_c / 2, 2), "cask": round(cltp + spread_c / 2, 2), "cbidq": 4200 + i * 90, "caskq": 3600 + i * 70,
            "pbid": round(pltp - spread_p / 2, 2), "pask": round(pltp + spread_p / 2, 2), "pbidq": 3300 + i * 60, "paskq": 3900 + i * 65,
            "cv1": round(cv1, 2), "cv3": round(1.0 + atm * .62, 2), "cv5": round(1.0 + atm * .40, 2),
            "coivel": round(.035 + atm * .04, 3), "cprem": round(cprem, 3),
            "pv1": round(pv1, 2), "pv3": round(1.0 + atm * .26, 2), "pv5": round(1.0 + atm * .18, 2),
            "poivel": round(.012 + atm * .015, 3), "pprem": round(pprem, 3),
            "c_delta": round(call_delta, 4), "c_gamma": .0018, "c_theta": -4.1, "c_vega": 8.4,
            "p_delta": round(put_delta, 4), "p_gamma": .0017, "p_theta": -3.9, "p_vega": 8.1,
        })
    runtime = {
        "HDFCBANK": {"ltp": 1827.40, "cp": 1818.20},
        "ICICIBANK": {"ltp": 1432.10, "cp": 1422.60},
        "RELIANCE": {"ltp": 1511.80, "cp": 1502.30},
        "BHARTIARTL": {"ltp": 2018.50, "cp": 2004.40},
        "LT": {"ltp": 3698.10, "cp": 3684.50},
        "INFY": {"ltp": 1519.20, "cp": 1523.80},
        "SBIN": {"ltp": 927.60, "cp": 921.40},
        "AXISBANK": {"ltp": 1298.30, "cp": 1291.20},
        "KOTAKBANK": {"ltp": 2132.10, "cp": 2126.60},
        "ITC": {"ltp": 422.40, "cp": 421.10},
        "FEDERALBNK": {"ltp": 228.10, "cp": 226.80},
        "INDUSINDBK": {"ltp": 914.50, "cp": 918.90},
        "AUBANK": {"ltp": 781.20, "cp": 776.40},
        "IDFCFIRSTB": {"ltp": 79.35, "cp": 79.02},
        "BANKBARODA": {"ltp": 262.80, "cp": 260.60},
    }
    levels = {
        "NIFTY": {"ltp": spot, "cp": 25174.80},
        "BANKNIFTY": {"ltp": 55284.20, "cp": 55041.70},
        "SENSEX": {"ltp": 77125.40, "cp": 76515.43},
    }
    index_brain = analyse_index_brains(runtime, levels)

    return {
        "ok": True,
        "source": "synthetic_demo_only",
        "active_underlying": "NIFTY",
        "active_label": "NIFTY 50",
        "spot": spot,
        "vwap": vwap,
        "vwap_source": "synthetic demo reference",
        "expiry": "DEMO",
        "option_data": rows,
        "price_series": {
            "3": [25208, 25213, 25219, 25225, 25231, 25242],
            "5": [25194, 25201, 25208, 25216, 25229, 25242],
            "15": [25168, 25179, 25192, 25205, 25221, 25242],
        },
        "official_max_pain": 25200,
        "official_pcr": 1.11,
        "iv_proxy": 19.3,
        "session_context": {"day_open":25186.0,"day_high":25258.0,"day_low":25170.0,"last_close":25242.35,"opening_range_high":25212.0,"opening_range_low":25178.0,"opening_range_minutes":15,"candles_seen":42},
        "pitch": [
            {"n": "HDFC Bank", "w": 10.56, "f": .51, "live": True},
            {"n": "ICICI Bank", "w": 8.32, "f": .67, "live": True},
            {"n": "Reliance", "w": 8.27, "f": .63, "live": True},
            {"n": "Bharti Airtel", "w": 5.20, "f": .70, "live": True},
            {"n": "L&T", "w": 4.43, "f": .37, "live": True},
            {"n": "Infosys", "w": 3.77, "f": -.30, "live": True},
            {"n": "SBI", "w": 3.71, "f": .67, "live": True},
            {"n": "Axis Bank", "w": 3.42, "f": .55, "live": True},
            {"n": "Kotak Bank", "w": 2.62, "f": .26, "live": True},
            {"n": "ITC", "w": 2.56, "f": .31, "live": True},
        ],
        "index_brain": index_brain,
        "websocket_connected": True,
        "websocket_error": None,
        "last_tick_epoch": time.time(),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "analytics_note": "Synthetic demo data — not a live market feed.",
        "demo": True,
    }
