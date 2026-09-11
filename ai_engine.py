from __future__ import annotations

import math
import json
import os
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple


def sf(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def squash(x: float, scale: float = 1.0) -> float:
    if scale <= 0:
        return 0.0
    return math.tanh(x / scale)


def pct_rank(v: float, arr: Iterable[float]) -> float:
    xs = [sf(x) for x in arr]
    if not xs:
        return 0.0
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return 0.5
    return clamp((v - lo) / (hi - lo), 0.0, 1.0)


def median_or(xs: Iterable[float], default: float) -> float:
    vals = [sf(x) for x in xs if sf(x) > 0]
    return statistics.median(vals) if vals else default


def weighted_mean(items: Iterable[Tuple[float, float]]) -> float:
    vals = [(sf(v), max(sf(w), 0.0)) for v, w in items]
    den = sum(w for _, w in vals)
    if den <= 0:
        return 0.0
    return sum(v * w for v, w in vals) / den


@dataclass
class AgentVote:
    name: str
    score: float  # -1 bearish .. +1 bullish
    reliability: float
    evidence: List[str]

    def as_dict(self) -> Dict[str, Any]:
        s = clamp(self.score, -1, 1)
        return {
            "name": self.name,
            "score": round(s, 4),
            "reliability": round(clamp(self.reliability, 0, 1) * 100, 1),
            "vote": "BULL" if s > 0.12 else "BEAR" if s < -0.12 else "NEUTRAL",
            "evidence": self.evidence[:4],
        }


class AIFusionEngine:
    """Explainable, regime-aware signal fusion for a read-only options scanner.

    This is intentionally *not* an order engine. It never places trades and it does
    not calculate P&L, targets or stop-losses. It consumes Upstox market-data only.

    The engine behaves like a small mixture-of-experts model:
      - trend expert
      - OI/positioning expert
      - volume/premium-flow expert
      - microstructure/liquidity expert
      - weighted Index Brain expert (NIFTY/BANKNIFTY constituents)
      - breadth expert
      - volatility/Greeks expert
      - market-structure expert

    Regime detection changes expert weights. A confidence gate, conflict detector,
    data-quality gate and trap-risk gate can force WAIT even when raw direction is
    non-zero. A short rolling memory labels signals NEW / CONFIRMED / WEAKENING /
    REVERSAL without storing user identity or account information.
    """

    MODES = {
        "strict": {"direction_gate": 0.23, "confidence_gate": 68, "contract_gate": 70, "trap_gate": 58},
        "balanced": {"direction_gate": 0.19, "confidence_gate": 61, "contract_gate": 65, "trap_gate": 66},
        "fast": {"direction_gate": 0.15, "confidence_gate": 55, "contract_gate": 60, "trap_gate": 72},
    }

    WEIGHTS = {
        # v5 gives the weighted constituent engine a first-class vote instead of
        # treating heavyweight breadth as a decorative dashboard metric.
        "TREND": {"Trend": .22, "Flow": .19, "Index Brain": .18, "OI": .13, "Microstructure": .10, "Breadth": .08, "Structure": .06, "Greeks/Vol": .04},
        "BREAKOUT_WATCH": {"Flow": .24, "Microstructure": .18, "Trend": .17, "Index Brain": .17, "OI": .09, "Breadth": .07, "Structure": .05, "Greeks/Vol": .03},
        "RANGE": {"Structure": .21, "OI": .20, "Flow": .15, "Index Brain": .13, "Microstructure": .11, "Trend": .09, "Breadth": .06, "Greeks/Vol": .05},
        "VOLATILE": {"Microstructure": .18, "Flow": .16, "Index Brain": .16, "Trend": .12, "OI": .11, "Structure": .10, "Greeks/Vol": .09, "Breadth": .08},
    }

    LEARNING_HORIZON_SECONDS = 300
    LEARNING_MIN_MOVE_PCT = 0.025
    CALIBRATION_MIN = 0.78
    CALIBRATION_MAX = 1.22

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.history: Deque[Dict[str, Any]] = deque(maxlen=24)
        self.last_history_ts = 0.0
        self.pending_predictions: Deque[Dict[str, Any]] = deque(maxlen=120)
        self.calibration_path = Path(os.getenv("AI_CALIBRATION_FILE") or Path(__file__).with_name("ai_calibration.json"))
        self.calibration = self._load_calibration()

    def _default_calibration(self) -> Dict[str, Any]:
        names = ["Trend", "OI", "Flow", "Microstructure", "Index Brain", "Breadth", "Greeks/Vol", "Structure"]
        return {
            "agent_multiplier": {name: 1.0 for name in names},
            "agent_stats": {name: {"wins": 0, "losses": 0, "neutral": 0} for name in names},
            "resolved_predictions": 0,
            "direction_hits": 0,
            "last_updated": None,
        }

    def _load_calibration(self) -> Dict[str, Any]:
        base = self._default_calibration()
        try:
            if self.calibration_path.exists():
                raw = json.loads(self.calibration_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for name in base["agent_multiplier"]:
                        base["agent_multiplier"][name] = clamp(sf((raw.get("agent_multiplier") or {}).get(name), 1.0), self.CALIBRATION_MIN, self.CALIBRATION_MAX)
                        st = (raw.get("agent_stats") or {}).get(name) or {}
                        base["agent_stats"][name] = {
                            "wins": int(sf(st.get("wins"))),
                            "losses": int(sf(st.get("losses"))),
                            "neutral": int(sf(st.get("neutral"))),
                        }
                    base["resolved_predictions"] = int(sf(raw.get("resolved_predictions")))
                    base["direction_hits"] = int(sf(raw.get("direction_hits")))
                    base["last_updated"] = raw.get("last_updated")
        except Exception:
            pass
        return base

    def _save_calibration(self) -> None:
        try:
            tmp = self.calibration_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.calibration, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.calibration_path)
        except Exception:
            # Calibration is an optional enhancement; never block live analytics.
            pass

    def _resolve_learning(self, spot: float) -> None:
        """Resolve old predictions against a short realized price move.

        The learner never places trades. It only nudges the relative influence of
        the explainable experts within tight bounds. Flat/noisy moves are ignored.
        """
        now = time.time()
        changed = False
        with self.lock:
            keep: Deque[Dict[str, Any]] = deque(maxlen=self.pending_predictions.maxlen)
            while self.pending_predictions:
                p = self.pending_predictions.popleft()
                age = now - sf(p.get("ts"))
                if age < self.LEARNING_HORIZON_SECONDS:
                    keep.append(p)
                    continue
                base_spot = sf(p.get("spot"))
                if base_spot <= 0:
                    continue
                move_pct = (spot - base_spot) / base_spot * 100.0
                if abs(move_pct) < self.LEARNING_MIN_MOVE_PCT:
                    for name in (p.get("agents") or {}):
                        if name in self.calibration["agent_stats"]:
                            self.calibration["agent_stats"][name]["neutral"] += 1
                    continue
                outcome = 1 if move_pct > 0 else -1
                overall = 1 if sf(p.get("fusion")) > 0 else -1
                self.calibration["resolved_predictions"] += 1
                if overall == outcome:
                    self.calibration["direction_hits"] += 1
                for name, score in (p.get("agents") or {}).items():
                    if name not in self.calibration["agent_multiplier"]:
                        continue
                    s = sf(score)
                    if abs(s) < .12:
                        self.calibration["agent_stats"][name]["neutral"] += 1
                        continue
                    vote = 1 if s > 0 else -1
                    strength = clamp(abs(s), .15, 1.0)
                    if vote == outcome:
                        self.calibration["agent_stats"][name]["wins"] += 1
                        self.calibration["agent_multiplier"][name] = clamp(
                            self.calibration["agent_multiplier"][name] + .008 * strength,
                            self.CALIBRATION_MIN,
                            self.CALIBRATION_MAX,
                        )
                    else:
                        self.calibration["agent_stats"][name]["losses"] += 1
                        self.calibration["agent_multiplier"][name] = clamp(
                            self.calibration["agent_multiplier"][name] - .010 * strength,
                            self.CALIBRATION_MIN,
                            self.CALIBRATION_MAX,
                        )
                changed = True
            self.pending_predictions = keep
            if changed:
                self.calibration["last_updated"] = int(now)
                self._save_calibration()

    def _queue_learning(self, spot: float, fusion: float, agents: List[AgentVote], data_quality: float) -> None:
        if spot <= 0 or data_quality < 58 or abs(fusion) < .10:
            return
        now = time.time()
        with self.lock:
            if self.pending_predictions and now - sf(self.pending_predictions[-1].get("ts")) < 45:
                return
            self.pending_predictions.append({
                "ts": now,
                "spot": spot,
                "fusion": fusion,
                "agents": {a.name: a.score for a in agents},
            })

    def _learning_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            resolved = int(sf(self.calibration.get("resolved_predictions")))
            hits = int(sf(self.calibration.get("direction_hits")))
            accuracy = (hits / resolved * 100.0) if resolved else None
            agents = []
            for name, mult in (self.calibration.get("agent_multiplier") or {}).items():
                st = (self.calibration.get("agent_stats") or {}).get(name) or {}
                w, l = int(sf(st.get("wins"))), int(sf(st.get("losses")))
                samples = w + l
                agents.append({
                    "name": name,
                    "multiplier": round(sf(mult, 1.0), 3),
                    "wins": w,
                    "losses": l,
                    "samples": samples,
                    "hit_rate": round(w / samples * 100.0, 1) if samples else None,
                })
            agents.sort(key=lambda x: x["multiplier"], reverse=True)
            return {
                "enabled": True,
                "horizon_seconds": self.LEARNING_HORIZON_SECONDS,
                "resolved_predictions": resolved,
                "direction_hits": hits,
                "observed_hit_rate": round(accuracy, 1) if accuracy is not None else None,
                "pending": len(self.pending_predictions),
                "agents": agents,
                "last_updated": self.calibration.get("last_updated"),
                "note": "Online calibration uses short realized market moves only; it is not a guarantee of future accuracy.",
            }

    def _totals(self, rows: List[Dict[str, Any]]) -> Dict[str, float]:
        out = {"coi": 0.0, "poi": 0.0, "cchg": 0.0, "pchg": 0.0, "cvol": 0.0, "pvol": 0.0}
        for r in rows:
            for k in out:
                out[k] += sf(r.get(k))
        return out

    def _max_pain(self, rows: List[Dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        best_s, best_pain = 0.0, None
        # OI scale cancels out for the argmin; no lot-size assumption is required.
        for k in rows:
            strike = sf(k.get("s"))
            pain = 0.0
            for r in rows:
                rs = sf(r.get("s"))
                pain += max(0.0, strike - rs) * sf(r.get("coi"))
                pain += max(0.0, rs - strike) * sf(r.get("poi"))
            if best_pain is None or pain < best_pain:
                best_s, best_pain = strike, pain
        return best_s

    def _weighted_breadth(self, pitch: List[Dict[str, Any]]) -> Tuple[float, int]:
        live = [x for x in pitch if x.get("live") and sf(x.get("w"), 0) > 0]
        if not live:
            return 0.0, 0
        return weighted_mean((sf(x.get("f")), sf(x.get("w"), 1)) for x in live), len(live)

    def _series_slope(self, series: List[float]) -> float:
        vals = [sf(x) for x in series if sf(x) > 0]
        if len(vals) < 2:
            return 0.0
        n = min(len(vals), 12)
        a, b = vals[-n], vals[-1]
        return (b - a) / max(a, 1e-9) * 100.0

    def _near_rows(self, rows: List[Dict[str, Any]], spot: float, n: int = 7) -> List[Dict[str, Any]]:
        return sorted(rows, key=lambda r: abs(sf(r.get("s")) - spot))[: min(n, len(rows))]

    def _data_quality(self, snap: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[float, List[str], float]:
        now = time.time()
        tick = sf(snap.get("last_tick_epoch"))
        age = max(0.0, now - tick) if tick > 0 else 9999.0
        ws = bool(snap.get("websocket_connected"))
        n = len(rows)
        priced = sum(1 for r in rows if sf(r.get("cltp")) > 0 and sf(r.get("pltp")) > 0)
        depth = sum(1 for r in rows if sf(r.get("cbid")) > 0 and sf(r.get("cask")) > 0 and sf(r.get("pbid")) > 0 and sf(r.get("pask")) > 0)
        greeks = sum(1 for r in rows if abs(sf(r.get("c_delta"))) > .01 and abs(sf(r.get("p_delta"))) > .01)
        completeness = (priced / max(n, 1)) * .35 + (depth / max(n, 1)) * .35 + (greeks / max(n, 1)) * .30
        freshness = 1.0 if age <= 6 else .88 if age <= 15 else .60 if age <= 45 else .25
        row_q = clamp(n / 17.0, 0.35, 1.0)
        feed_q = 1.0 if ws else .78
        q = 100 * (.40 * completeness + .25 * freshness + .20 * row_q + .15 * feed_q)
        notes = [
            f"{'WebSocket' if ws else 'REST fallback'} feed",
            f"data age {age:.0f}s" if age < 9999 else "tick freshness unavailable",
            f"{n} strikes in AI window",
        ]
        return clamp(q, 0, 100), notes, age

    def _build_agents(self, snap: Dict[str, Any], rows: List[Dict[str, Any]], t: Dict[str, float], metrics: Dict[str, Any]) -> List[AgentVote]:
        spot, vwap = metrics["spot"], metrics["vwap"]
        pcr, dpcr, vr = metrics["pcr"], metrics["dpcr"], metrics["vr"]
        breadth, breadth_n = metrics["breadth"], metrics["breadth_n"]
        near = self._near_rows(rows, spot, 7)

        # Trend expert: spot-vwap + multi-horizon price slope.
        gap = metrics["gap_pct"]
        ps = snap.get("price_series") or {}
        s3 = self._series_slope(list(ps.get("3") or []))
        s5 = self._series_slope(list(ps.get("5") or []))
        s15 = self._series_slope(list(ps.get("15") or []))
        trend_score = clamp(.55 * squash(gap, .055) + .22 * squash(s3, .06) + .15 * squash(s5, .09) + .08 * squash(s15, .14), -1, 1)
        trend_e = [f"spot {gap:+.3f}% vs VWAP", f"3m {s3:+.3f}%", f"5m {s5:+.3f}%"]
        trend_rel = .86 if vwap and spot else .45

        # OI expert: positioning + near-ATM change balance.
        pcr_sig = squash(pcr - 1.0, .20) if pcr > 0 else 0.0
        if t["cchg"] or t["pchg"]:
            doi_balance = (t["pchg"] - t["cchg"]) / max(abs(t["pchg"]) + abs(t["cchg"]), .01)
        else:
            doi_balance = 0.0
        near_cchg = sum(sf(r.get("cchg")) for r in near)
        near_pchg = sum(sf(r.get("pchg")) for r in near)
        near_bal = (near_pchg - near_cchg) / max(abs(near_pchg) + abs(near_cchg), .01) if (near_pchg or near_cchg) else 0.0
        oi_score = clamp(.42 * pcr_sig + .34 * doi_balance + .24 * near_bal, -1, 1)
        oi_e = [f"PCR {pcr:.2f}" if pcr else "PCR unavailable", f"ΔOI balance {doi_balance:+.2f}", f"ATM ΔOI {near_bal:+.2f}"]
        oi_rel = .84 if t["coi"] > 0 and t["poi"] > 0 else .45

        # Flow expert: option premium acceleration + volume acceleration. CE rising is bullish, PE rising is bearish.
        def leg_flow(r: Dict[str, Any], side: str) -> float:
            if side == "C":
                v1, v3, v5, prem, vol = sf(r.get("cv1"), 1), sf(r.get("cv3"), 1), sf(r.get("cv5"), 1), sf(r.get("cprem")), sf(r.get("cvol"))
            else:
                v1, v3, v5, prem, vol = sf(r.get("pv1"), 1), sf(r.get("pv3"), 1), sf(r.get("pv5"), 1), sf(r.get("pprem")), sf(r.get("pvol"))
            accel = .55 * (v1 - 1) + .30 * (v3 - 1) + .15 * (v5 - 1)
            return squash(prem, 3.0) * (.55 + .45 * clamp(1 + accel / 2.0, .25, 2.0)) * max(math.log1p(vol), 1.0)
        cflows = [leg_flow(r, "C") for r in near]
        pflows = [leg_flow(r, "P") for r in near]
        cflow = statistics.mean(cflows) if cflows else 0.0
        pflow = statistics.mean(pflows) if pflows else 0.0
        flow_den = max(abs(cflow) + abs(pflow), 1.0)
        premium_flow = clamp((cflow - pflow) / flow_den, -1, 1)
        vol_ratio_sig = -squash(vr - 1.0, .30) if vr > 0 else 0.0  # volume alone has small contrarian weight
        flow_score = clamp(.82 * premium_flow + .18 * vol_ratio_sig, -1, 1)
        max_v1 = max([sf(r.get("cv1"), 1) for r in near] + [sf(r.get("pv1"), 1) for r in near] + [1])
        flow_e = [f"premium-flow {premium_flow:+.2f}", f"max 1m volume spike {max_v1:.1f}×", f"PE/CE volume {vr:.2f}" if vr else "volume ratio unavailable"]
        flow_rel = clamp(.52 + min(max_v1, 4) * .09, .52, .90)

        # Microstructure expert: compare spread quality and bid-depth support across ATM legs.
        def micro_leg(r: Dict[str, Any], side: str) -> Tuple[float, float]:
            if side == "C":
                bid, ask, bq, aq = sf(r.get("cbid")), sf(r.get("cask")), sf(r.get("cbidq")), sf(r.get("caskq"))
            else:
                bid, ask, bq, aq = sf(r.get("pbid")), sf(r.get("pask")), sf(r.get("pbidq")), sf(r.get("paskq"))
            mid = max((bid + ask) / 2, .01)
            spread = (ask - bid) / mid if ask > 0 and bid > 0 and ask >= bid else .08
            spread_q = clamp(1 - spread / .055, 0, 1)
            depth_imb = (bq - aq) / max(bq + aq, 1.0)
            return spread_q, depth_imb
        cm, pm = zip(*[micro_leg(r, "C") for r in near]) if near else ([], [])
        pmix = [micro_leg(r, "P") for r in near]
        psq = [x[0] for x in pmix]
        pdi = [x[1] for x in pmix]
        c_sq = statistics.mean(cm) if cm else 0
        c_di = statistics.mean(pm) if pm else 0
        p_sq = statistics.mean(psq) if psq else 0
        p_di = statistics.mean(pdi) if pdi else 0
        micro_score = clamp(.55 * (c_di - p_di) + .45 * (c_sq - p_sq), -1, 1)
        micro_e = [f"CE spread quality {c_sq*100:.0f}%", f"PE spread quality {p_sq*100:.0f}%", f"depth edge {(c_di-p_di):+.2f}"]
        micro_rel = clamp((c_sq + p_sq) / 2, .35, .92)

        # Weighted Index Brain expert: high-impact NIFTY constituents are
        # analysed using their index weights, leader/drag contribution and
        # divergence against the live index.  This is separate from the simpler
        # breadth vote below so the fusion can distinguish "many green stocks"
        # from "the stocks that actually matter are green".
        active_code = str(snap.get("active_underlying") or "NIFTY").upper()
        brain = ((snap.get("index_brain") or {}).get(active_code) or {})
        brain_score = clamp(sf(brain.get("direction_score")), -1, 1)
        brain_coverage = sf(brain.get("coverage_pct"))
        brain_agreement = sf(brain.get("agreement_pct"), 50)
        brain_div = sf(brain.get("divergence_risk"))
        brain_conf = sf(brain.get("confirmation_score"))
        brain_rel = clamp(.25 + .45 * brain_coverage / 100 + .30 * brain_agreement / 100, .22, .97) if brain_coverage else .20
        brain_rel *= (1 - .35 * clamp(brain_div / 100, 0, 1))
        lead = (brain.get("leaders") or [{}])[0]
        drag = (brain.get("drags") or [{}])[0]
        brain_e = [
            f"weighted heavy move {sf(brain.get('weighted_heavy_move_pct')):+.2f}%",
            f"index confirmation {brain_conf:.0f}/100",
            f"leader {lead.get('symbol','—')} {sf(lead.get('change_pct')):+.2f}% / drag {drag.get('symbol','—')} {sf(drag.get('change_pct')):+.2f}%",
        ] if brain_coverage else ["weighted constituent feed unavailable"]

        # Breadth expert.
        breadth_score = squash(breadth, .22) if breadth_n else 0.0
        breadth_e = [f"weighted {active_code} breadth {breadth:+.2f}%", f"{breadth_n} heavyweight futures live"] if breadth_n else ["heavyweight breadth unavailable"]
        breadth_rel = clamp(breadth_n / 8.0, .25, .95) if breadth_n else .20

        # Greeks/Vol expert: IV skew is weak directional evidence; use low weight by design.
        civs = [sf(r.get("civ")) for r in near if sf(r.get("civ")) > 0]
        pivs = [sf(r.get("piv")) for r in near if sf(r.get("piv")) > 0]
        civ, piv = median_or(civs, 0), median_or(pivs, 0)
        skew = (civ - piv) / max((civ + piv) / 2, 1) if civ and piv else 0.0
        iv_proxy = sf(snap.get("iv_proxy"), median_or(civs + pivs, 20))
        greek_score = clamp(squash(skew, .08) * .65 + squash(flow_score, .8) * .35, -1, 1)
        greek_e = [f"CE IV {civ:.1f}" if civ else "CE IV unavailable", f"PE IV {piv:.1f}" if piv else "PE IV unavailable", f"IV proxy {iv_proxy:.1f}"]
        greek_rel = .68 if civ and piv else .35

        # Structure expert: walls, max-pain magnet and location.
        cw, pw = metrics.get("call_wall"), metrics.get("put_wall")
        max_pain = metrics.get("max_pain") or 0
        structure = 0.0
        evid = []
        if cw:
            cws = sf(cw.get("s"))
            if cws > spot:
                structure -= .28 * clamp((spot / max(cws - spot, 1)) * .003, 0, 1)
            evid.append(f"call wall {cws:.0f}")
        if pw:
            pws = sf(pw.get("s"))
            if pws < spot:
                structure += .28 * clamp((spot / max(spot - pws, 1)) * .003, 0, 1)
            evid.append(f"put wall {pws:.0f}")
        if max_pain:
            mp_delta = (spot - max_pain) / max(spot, 1) * 100
            structure += .30 * squash(mp_delta, .20)
            evid.append(f"max pain {max_pain:.0f}")
        structure_score = clamp(structure, -1, 1)
        structure_rel = .78 if cw and pw else .48

        return [
            AgentVote("Trend", trend_score, trend_rel, trend_e),
            AgentVote("OI", oi_score, oi_rel, oi_e),
            AgentVote("Flow", flow_score, flow_rel, flow_e),
            AgentVote("Microstructure", micro_score, micro_rel, micro_e),
            AgentVote("Index Brain", brain_score, brain_rel, brain_e),
            AgentVote("Breadth", breadth_score, breadth_rel, breadth_e),
            AgentVote("Greeks/Vol", greek_score, greek_rel, greek_e),
            AgentVote("Structure", structure_score, structure_rel, evid or ["structure incomplete"]),
        ]

    def _regime(self, gap: float, breadth: float, flow: float, iv_proxy: float, conflict: float, max_v1: float) -> str:
        aligned = (gap > .05 and breadth > .05) or (gap < -.05 and breadth < -.05)
        if iv_proxy >= 30 and conflict > .45:
            return "VOLATILE"
        if max_v1 >= 2.0 and abs(gap) <= .055:
            return "BREAKOUT_WATCH"
        if abs(gap) >= .065 and aligned:
            return "TREND"
        return "RANGE"

    def _contract(self, side: str, r: Dict[str, Any], rows: List[Dict[str, Any]], spot: float, iv_median: float) -> Dict[str, Any]:
        is_c = side == "CE"
        p = "c" if is_c else "p"
        vol = sf(r.get(p + "vol"))
        oi = sf(r.get(p + "oi"))
        chg = sf(r.get(p + "chg"))
        ltp = sf(r.get(p + "ltp"))
        iv = sf(r.get(p + "iv"))
        bid = sf(r.get(p + "bid"))
        ask = sf(r.get(p + "ask"))
        bidq = sf(r.get(p + "bidq"))
        askq = sf(r.get(p + "askq"))
        v1 = sf(r.get(p + "v1"), 1)
        v3 = sf(r.get(p + "v3"), 1)
        v5 = sf(r.get(p + "v5"), 1)
        oivel = sf(r.get(p + "oivel"))
        prem = sf(r.get(p + "prem"))
        delta = sf(r.get(p + "_delta"))
        theta = sf(r.get(p + "_theta"))
        gamma = sf(r.get(p + "_gamma"))
        if not delta:
            d = (spot - sf(r.get("s"))) / max(spot * .008, 1)
            call_delta = clamp(.5 + d * .22, .08, .92)
            delta = call_delta if is_c else -(1 - call_delta)

        vols = [sf(x.get(p + "vol")) for x in rows]
        ois = [sf(x.get(p + "oi")) for x in rows]
        spread = (ask - bid) / max((ask + bid) / 2, .01) if ask > 0 and bid > 0 and ask >= bid else .09
        spread_q = clamp(1 - spread / .05, 0, 1)
        liquidity = .58 * pct_rank(vol, vols) + .42 * pct_rank(oi, ois)
        delta_q = 1 - clamp(abs(abs(delta) - .54) / .34, 0, 1)
        dist_pct = abs(sf(r.get("s")) - spot) / max(spot, 1) * 100
        distance_q = clamp(1 - dist_pct / 1.75, 0, 1)
        accel = .52 * (v1 - 1) + .30 * (v3 - 1) + .18 * (v5 - 1)
        accel_q = clamp(.48 + accel / 2.4, 0, 1)
        prem_q = clamp(.50 + squash(prem, 3.2) * .42, 0, 1)
        depth_imb = (bidq - askq) / max(bidq + askq, 1.0)
        depth_q = clamp(.5 + depth_imb * .5, 0, 1)
        iv_q = 1.0 if not iv else clamp(1 - max(iv - max(iv_median * 1.25, 24), 0) / 32, .25, 1)
        theta_drag = abs(theta) / max(ltp, 1) if theta else 0.0
        theta_q = clamp(1 - theta_drag / .12, .30, 1)
        flow_class = "LONG BUILDUP" if oivel > .01 and prem > .05 else "SHORT COVER" if oivel < -.01 and prem > .05 else "WRITING" if oivel > .01 and prem < -.05 else "MIXED"
        score = 100 * (
            .22 * liquidity + .16 * spread_q + .15 * delta_q + .10 * distance_q +
            .13 * accel_q + .12 * prem_q + .05 * depth_q + .04 * iv_q + .03 * theta_q
        )
        if ltp <= 0:
            score -= 35
        if spread > .06:
            score -= 15
        if abs(delta) < .18:
            score -= 9
        return {
            "side": side,
            "strike": sf(r.get("s")),
            "ltp": ltp,
            "score": round(clamp(score, 0, 100), 1),
            "volume": vol,
            "oi": oi,
            "oi_change": chg,
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "iv": round(iv, 2),
            "bid": bid,
            "ask": ask,
            "spread_pct": round(spread * 100, 3),
            "volume_spike_1m": round(v1, 2),
            "volume_spike_3m": round(v3, 2),
            "volume_spike_5m": round(v5, 2),
            "oi_velocity": round(oivel, 3),
            "premium_momentum": round(prem, 3),
            "flow_class": flow_class,
            "distance_pct": round(dist_pct, 3),
            "depth_imbalance": round(depth_imb, 3),
        }

    def _lifecycle(self, side: str, confidence: float, fusion: float) -> Tuple[str, str]:
        with self.lock:
            hist = list(self.history)
            prev = hist[-1] if hist else None
            if side == "WAIT":
                if prev and prev.get("side") in {"CE", "PE"}:
                    return "WEAKENING", "Directional edge fell below the AI gate."
                return "FILTERED", "AI risk gate is keeping the market in WAIT."
            if not prev:
                return "NEW", "First qualified directional signal in current AI memory."
            if prev.get("side") in {"CE", "PE"} and prev.get("side") != side:
                return "REVERSAL", f"AI direction flipped from {prev.get('side')} to {side}."
            same = [x for x in hist[-4:] if x.get("side") == side]
            if len(same) >= 3 and confidence >= 68:
                return "CONFIRMED", "Same direction survived multiple AI refreshes."
            if prev.get("side") == side and confidence + 10 < sf(prev.get("confidence")):
                return "WEAKENING", "Direction remains, but confidence is falling."
            return "BUILDING", "Direction is consistent but still building confirmation."

    def _remember(self, side: str, confidence: float, fusion: float, strike: float) -> None:
        now = time.time()
        with self.lock:
            if now - self.last_history_ts < 6.0:
                return
            self.history.append({"ts": now, "side": side, "confidence": confidence, "fusion": fusion, "strike": strike})
            self.last_history_ts = now


    def _advanced_intelligence(
        self,
        snap: Dict[str, Any],
        rows: List[Dict[str, Any]],
        agents: List[AgentVote],
        metrics: Dict[str, Any],
        fusion: float,
        confidence: float,
        trap: float,
        data_quality: float,
        regime: str,
        side: str,
        top_contract: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build a second-stage AI interpretation layer.

        This layer does not create orders, targets, stops or P&L. It turns the
        explainable expert votes into multi-horizon directional maps, stability,
        anomaly/false-signal risk, consensus and explicit watch conditions.
        """
        amap = {a.name: a for a in agents}
        def av(name: str) -> float:
            return sf(amap.get(name).score if amap.get(name) else 0.0)

        trend, oi, flow = av("Trend"), av("OI"), av("Flow")
        micro, breadth = av("Microstructure"), av("Breadth")
        index_brain = av("Index Brain")
        greeks, structure = av("Greeks/Vol"), av("Structure")
        ps = snap.get("price_series") or {}
        s3 = self._series_slope(list(ps.get("3") or []))
        s5 = self._series_slope(list(ps.get("5") or []))
        s15 = self._series_slope(list(ps.get("15") or []))

        # Different horizons intentionally use different expert mixes.
        h_micro = clamp(.27 * flow + .23 * micro + .20 * trend + .13 * index_brain + .10 * oi + .07 * squash(s3, .07), -1, 1)
        h_momo = clamp(.24 * trend + .20 * flow + .18 * index_brain + .14 * oi + .10 * breadth + .08 * micro + .06 * squash(s5, .11), -1, 1)
        h_trend = clamp(.28 * trend + .22 * index_brain + .15 * breadth + .16 * oi + .10 * structure + .05 * greeks + .04 * squash(s15, .16), -1, 1)

        def horizon(label: str, minutes: str, score: float) -> Dict[str, Any]:
            gate = .14 if label == "MICRO" else .12
            direction = "CE" if score > gate else "PE" if score < -gate else "WAIT"
            strength = clamp(abs(score) * 100 * (.72 + .28 * data_quality / 100), 0, 100)
            return {
                "label": label, "minutes": minutes, "direction": direction,
                "score": round(score * 100, 1), "strength": round(strength, 1),
            }

        forecasts = [
            horizon("MICRO", "1–3m", h_micro),
            horizon("MOMENTUM", "5–15m", h_momo),
            horizon("TREND", "15–30m", h_trend),
        ]

        bulls = sum(1 for a in agents if a.score > .12)
        bears = sum(1 for a in agents if a.score < -.12)
        neutral = max(0, len(agents) - bulls - bears)
        directional = bulls + bears
        consensus_pct = 100 * max(bulls, bears) / max(directional, 1) if directional else 50.0

        # Stability comes from recent qualified state persistence, not from P&L.
        with self.lock:
            recent = list(self.history)[-6:]
        if side in {"CE", "PE"} and recent:
            same = sum(1 for x in recent if x.get("side") == side)
            stability = 100 * same / len(recent)
        elif side == "WAIT":
            same = sum(1 for x in recent if x.get("side") == "WAIT")
            stability = 100 * same / len(recent) if recent else 50.0
        else:
            stability = 50.0

        near = self._near_rows(rows, sf(metrics.get("spot")), 7)
        vspikes = [sf(r.get(k), 1) for r in near for k in ("cv1", "pv1")]
        max_v1 = max(vspikes + [1.0])
        spreads = []
        for r in near:
            for pref in ("c", "p"):
                bid, ask = sf(r.get(pref + "bid")), sf(r.get(pref + "ask"))
                if bid > 0 and ask >= bid:
                    spreads.append((ask - bid) / max((ask + bid) / 2, .01) * 100)
        median_spread = statistics.median(spreads) if spreads else 6.0
        iv_proxy = sf(snap.get("iv_proxy"), 20)
        conflict_pct = clamp((1.0 - abs(weighted_mean((a.score, a.reliability) for a in agents))) * 100, 0, 100)
        anomaly = 100 * (
            .34 * clamp((max_v1 - 1.8) / 3.5, 0, 1) +
            .24 * clamp((median_spread - 2.0) / 5.0, 0, 1) +
            .22 * clamp((iv_proxy - 24) / 22, 0, 1) +
            .20 * (conflict_pct / 100)
        )
        anomaly = clamp(anomaly, 0, 100)

        contract_q = sf(top_contract.get("score"), 50) if top_contract else 50.0
        active_code = str(snap.get("active_underlying") or "NIFTY").upper()
        active_brain = ((snap.get("index_brain") or {}).get(active_code) or {})
        index_div = sf(active_brain.get("divergence_risk"))
        index_fragility = sf(active_brain.get("fragility_risk"))
        false_signal = clamp(
            .29 * trap + .19 * conflict_pct + .15 * (100 - data_quality) +
            .13 * anomaly + .10 * (100 - contract_q) + .08 * index_div + .06 * index_fragility, 0, 100
        )

        if side == "WAIT":
            grade = "FILTERED"
        else:
            quality = .38 * confidence + .22 * data_quality + .18 * (100 - trap) + .12 * stability + .10 * contract_q
            grade = "A+" if quality >= 82 else "A" if quality >= 75 else "B+" if quality >= 69 else "B" if quality >= 63 else "C"

        # Human-readable conditions describe what the scanner is waiting for; they
        # are analytics conditions, not executable order instructions.
        watch: List[str] = []
        if side == "WAIT":
            if confidence < 68:
                watch.append("AI confidence needs stronger expert alignment")
            if trap > 58:
                watch.append("Trap risk must cool before a clean signal")
            if data_quality < 65:
                watch.append("Wait for fresher/deeper market data")
            if abs(fusion) < .23:
                watch.append("Directional fusion is still inside the noise zone")
            if max_v1 < 1.5:
                watch.append("No meaningful near-ATM volume acceleration yet")
        else:
            watch.append(f"Protect signal quality while AI remains {side}-aligned")
            if stability < 60:
                watch.append("Signal is fresh; wait for persistence across refreshes")
            if false_signal > 45:
                watch.append("False-signal risk is elevated despite directional bias")
            if regime == "VOLATILE":
                watch.append("Volatile regime: expect faster signal flips")
        if index_div > 55:
            watch.append(f"{active_code} index and heavyweight contribution are diverging")
        if sf(active_brain.get("confirmation_score")) and sf(active_brain.get("confirmation_score")) < 45:
            watch.append("High-weight stocks are not confirming the index move")
        if not watch:
            watch.append("No major AI warning condition detected")

        return {
            "brain": "ADAPTIVE FUSION v5 • INDEX BRAIN",
            "signal_grade": grade,
            "consensus": {
                "bull": bulls, "bear": bears, "neutral": neutral,
                "dominant_pct": round(consensus_pct, 1),
            },
            "stability_score": round(clamp(stability, 0, 100), 1),
            "false_signal_risk": round(false_signal, 1),
            "anomaly_score": round(anomaly, 1),
            "forecast": forecasts,
            "watch_conditions": watch[:5],
            "market_state": {
                "regime": regime,
                "median_near_atm_spread_pct": round(median_spread, 2),
                "max_near_atm_volume_spike_1m": round(max_v1, 2),
                "price_slope_3m_pct": round(s3, 4),
                "price_slope_5m_pct": round(s5, 4),
                "price_slope_15m_pct": round(s15, 4),
            },
        }

    def analyse(self, snap: Dict[str, Any], mode: str = "strict") -> Dict[str, Any]:
        mode = mode if mode in self.MODES else "strict"
        gates = self.MODES[mode]
        rows = [dict(r) for r in (snap.get("option_data") or [])]
        rows = [r for r in rows if sf(r.get("s")) > 0]
        rows.sort(key=lambda r: sf(r.get("s")))
        spot = sf(snap.get("spot"))
        vwap = sf(snap.get("vwap"), spot)
        if not rows or spot <= 0:
            return {
                "ok": True, "mode": mode, "signal": "WAIT", "side": "WAIT", "confidence": 0,
                "fusion_score": 0, "regime": "NO_DATA", "lifecycle": "FILTERED",
                "data_quality": 0, "trap_risk": 100, "agents": [], "top_contract": None,
                "backups": [], "radar": [], "summary": "Waiting for a valid live option-chain snapshot.",
                "metrics": {}, "source": snap.get("source", ""), "orders_enabled": False,
                "learning": self._learning_snapshot(),
            }

        self._resolve_learning(spot)

        t = self._totals(rows)
        pcr = t["poi"] / t["coi"] if t["coi"] > 0 else 0.0
        # Signed ΔOI is more informative as a normalized balance than a raw ratio; expose both.
        dpcr = t["pchg"] / t["cchg"] if abs(t["cchg"]) > 1e-9 else 0.0
        vr = t["pvol"] / t["cvol"] if t["cvol"] > 0 else 0.0
        breadth, breadth_n = self._weighted_breadth(list(snap.get("pitch") or []))
        if str(snap.get("active_underlying") or "NIFTY").upper() == "SENSEX":
            # v9 does not pretend NIFTY/BANKNIFTY heavyweight futures are SENSEX breadth.
            breadth, breadth_n = 0.0, 0
        gap = (spot - vwap) / max(spot, 1) * 100.0 if vwap else 0.0
        call_wall = max(rows, key=lambda r: sf(r.get("coi"))) if rows else None
        put_wall = max(rows, key=lambda r: sf(r.get("poi"))) if rows else None
        max_pain = sf(snap.get("official_max_pain")) or self._max_pain(rows)
        magnet_pts = abs(spot - max_pain) if max_pain else 0.0
        metrics = {
            "spot": spot, "vwap": vwap, "gap_pct": gap, "pcr": pcr, "dpcr": dpcr, "vr": vr,
            "breadth": breadth, "breadth_n": breadth_n, "call_wall": call_wall, "put_wall": put_wall,
            "max_pain": max_pain, "magnet_pts": magnet_pts,
        }
        agents = self._build_agents(snap, rows, t, metrics)
        amap = {a.name: a for a in agents}
        conflict = 1.0 - abs(weighted_mean((a.score, a.reliability) for a in agents))
        near = self._near_rows(rows, spot, 7)
        max_v1 = max([sf(r.get("cv1"), 1) for r in near] + [sf(r.get("pv1"), 1) for r in near] + [1.0])
        iv_proxy = sf(snap.get("iv_proxy"), 20)
        regime = self._regime(gap, breadth, amap["Flow"].score, iv_proxy, conflict, max_v1)
        weights = self.WEIGHTS[regime]

        numer, denom = 0.0, 0.0
        for a in agents:
            learned = sf((self.calibration.get("agent_multiplier") or {}).get(a.name), 1.0)
            w = sf(weights.get(a.name)) * a.reliability * learned
            numer += a.score * w
            denom += w
        fusion = clamp(numer / max(denom, 1e-9), -1, 1)
        agreement = weighted_mean((1.0 if (a.score >= 0) == (fusion >= 0) else 0.0, a.reliability * sf(weights.get(a.name))) for a in agents) if abs(fusion) > .03 else .5
        data_quality, dq_notes, data_age = self._data_quality(snap, rows)
        raw_conf = abs(fusion) * 100.0
        confidence = clamp(raw_conf * (.60 + .40 * agreement) * (.68 + .32 * data_quality / 100), 0, 100)

        iv_median = median_or([r.get("civ") for r in rows] + [r.get("piv") for r in rows], max(iv_proxy, 18))
        radar = []
        for r in rows:
            radar.append(self._contract("CE", r, rows, spot, iv_median))
            radar.append(self._contract("PE", r, rows, spot, iv_median))
        radar.sort(key=lambda x: x["score"], reverse=True)

        raw_side = "CE" if fusion > gates["direction_gate"] else "PE" if fusion < -gates["direction_gate"] else "WAIT"
        side_candidates = [x for x in radar if x["side"] == raw_side] if raw_side != "WAIT" else []
        best = side_candidates[0] if side_candidates else None

        # Trap risk is deliberately conservative: conflict, max-pain magnet, weak data, spread, IV stress.
        magnet_q = clamp(1 - magnet_pts / max(spot * .004, 80), 0, 1) if max_pain else .3
        spread_pen = clamp((sf(best.get("spread_pct")) - 2.5) / 4.0, 0, 1) if best else .5
        contract_pen = clamp((70 - sf(best.get("score"))) / 25, 0, 1) if best else .8
        iv_stress = clamp((iv_proxy - 27) / 18, 0, 1)
        trap = 100 * (.34 * conflict + .18 * magnet_q + .18 * (1 - data_quality / 100) + .14 * spread_pen + .10 * contract_pen + .06 * iv_stress)
        trap = clamp(trap, 0, 100)

        reasons: List[Dict[str, str]] = []
        for a in sorted(agents, key=lambda x: abs(x.score) * x.reliability, reverse=True)[:5]:
            tone = "good" if a.score > .12 else "bad" if a.score < -.12 else "warn"
            direction = "bullish" if a.score > .12 else "bearish" if a.score < -.12 else "neutral"
            reasons.append({"tone": tone, "text": f"{a.name}: {direction} ({abs(a.score)*100:.0f})"})
        if magnet_q > .65:
            reasons.append({"tone": "warn", "text": "Spot is close to max-pain magnet"})
        if data_quality < 65:
            reasons.append({"tone": "warn", "text": "Market-data quality is below preferred level"})

        side = raw_side
        reject_reasons: List[str] = []
        if confidence < gates["confidence_gate"]:
            reject_reasons.append(f"confidence {confidence:.0f} < {gates['confidence_gate']}")
        if data_quality < 58:
            reject_reasons.append(f"data quality {data_quality:.0f} < 58")
        if trap > gates["trap_gate"]:
            reject_reasons.append(f"trap risk {trap:.0f} > {gates['trap_gate']}")
        if best and best["score"] < gates["contract_gate"]:
            reject_reasons.append(f"best contract {best['score']:.0f} < {gates['contract_gate']}")
        if raw_side == "WAIT" or not best:
            reject_reasons.append("directional fusion below gate")
        if reject_reasons:
            side = "WAIT"

        lifecycle, lifecycle_note = self._lifecycle(side, confidence, fusion)
        signal = "BUY CE" if side == "CE" else "BUY PE" if side == "PE" else "WAIT"

        # Backups are only from the qualified directional side. Radar still shows both sides for transparency.
        backups = [x for x in side_candidates[1:4]] if side != "WAIT" else []
        top_contract = best if side != "WAIT" else None

        dominant = sorted(agents, key=lambda a: abs(a.score) * a.reliability, reverse=True)[:3]
        dom_text = ", ".join(f"{a.name} {'+' if a.score > 0 else '-'}{abs(a.score)*100:.0f}" for a in dominant)
        if side == "WAIT":
            summary = f"AI WAIT — {regime.replace('_',' ')} regime. " + ("; ".join(reject_reasons[:3]) if reject_reasons else "no clean edge") + "."
        else:
            summary = f"{signal} {top_contract['strike']:.0f} — confidence {confidence:.0f}/100, contract {top_contract['score']:.0f}/100. Dominant experts: {dom_text}."

        prev = self.history[-1] if self.history else None
        what_changed = []
        if prev:
            dc = confidence - sf(prev.get("confidence"))
            what_changed.append(f"confidence {'+' if dc >= 0 else ''}{dc:.0f}")
            if prev.get("side") != side:
                what_changed.append(f"state {prev.get('side')} → {side}")
            if top_contract and sf(prev.get("strike")) and sf(prev.get("strike")) != top_contract["strike"]:
                what_changed.append(f"best strike {sf(prev.get('strike')):.0f} → {top_contract['strike']:.0f}")
        if not what_changed:
            what_changed = ["initial AI snapshot"]

        self._remember(side, confidence, fusion, sf(top_contract.get("strike")) if top_contract else 0)
        self._queue_learning(spot, fusion, agents, data_quality)
        intelligence = self._advanced_intelligence(
            snap=snap, rows=rows, agents=agents, metrics=metrics, fusion=fusion,
            confidence=confidence, trap=trap, data_quality=data_quality, regime=regime,
            side=side, top_contract=top_contract,
        )

        return {
            "ok": True,
            "mode": mode,
            "signal": signal,
            "side": side,
            "raw_side": raw_side,
            "confidence": round(confidence, 1),
            "fusion_score": round(fusion * 100, 1),
            "agreement": round(agreement * 100, 1),
            "conflict": round(conflict * 100, 1),
            "regime": regime,
            "lifecycle": lifecycle,
            "lifecycle_note": lifecycle_note,
            "data_quality": round(data_quality, 1),
            "data_age_seconds": round(data_age, 1) if data_age < 9999 else None,
            "data_quality_notes": dq_notes,
            "trap_risk": round(trap, 1),
            "agents": [a.as_dict() for a in agents],
            "top_contract": top_contract,
            "backups": backups,
            "radar": radar[:12],
            "summary": summary,
            "reject_reasons": reject_reasons,
            "reasons": reasons,
            "what_changed": what_changed,
            "metrics": {
                "spot": round(spot, 2),
                "vwap": round(vwap, 2),
                "gap_pct": round(gap, 4),
                "pcr_oi": round(pcr, 3),
                "delta_oi_ratio": round(dpcr, 3),
                "pe_ce_volume_ratio": round(vr, 3),
                "breadth_pct": round(breadth, 3),
                "breadth_live": breadth_n,
                "call_wall": round(sf(call_wall.get("s")), 2) if call_wall else None,
                "put_wall": round(sf(put_wall.get("s")), 2) if put_wall else None,
                "max_pain": round(max_pain, 2) if max_pain else None,
                "max_pain_distance": round(magnet_pts, 2) if max_pain else None,
                "iv_proxy": round(iv_proxy, 2),
            },
            "feed": {
                "source": snap.get("source", ""),
                "websocket_connected": bool(snap.get("websocket_connected")),
                "server_time": snap.get("server_time"),
                "expiry": snap.get("expiry"),
            },
            "gates": gates,
            "learning": self._learning_snapshot(),
            "intelligence": intelligence,
            "signal_grade": intelligence.get("signal_grade"),
            "false_signal_risk": intelligence.get("false_signal_risk"),
            "anomaly_score": intelligence.get("anomaly_score"),
            "stability_score": intelligence.get("stability_score"),
            "forecast": intelligence.get("forecast"),
            "watch_conditions": intelligence.get("watch_conditions"),
            "active_underlying": str(snap.get("active_underlying") or "NIFTY").upper(),
            "index_confirmation": ((snap.get("index_brain") or {}).get(str(snap.get("active_underlying") or "NIFTY").upper()) or {}),
            "banknifty_brain": ((snap.get("index_brain") or {}).get("BANKNIFTY") or {}),
            "orders_enabled": False,
            "pnl_enabled": False,
            "execution_enabled": False,
        }
