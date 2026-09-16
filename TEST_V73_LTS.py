from fastapi.testclient import TestClient

from app import app
from v73_lts_engine import TAB_ARCHITECTURE, circuit_candidate, depth_dom_intelligence, hero_execution_plan


def main():
    assert len(TAB_ARCHITECTURE) == 8

    row = {
        "symbol": "DEMO",
        "ltp": 99.2,
        "upper_circuit_limit": 100.0,
        "lower_circuit_limit": 80.0,
        "change_pct": 4.4,
        "volume": 8_000_000,
        "rvol": 3.8,
        "total_buy_qty": 900_000,
        "total_sell_qty": 85_000,
        "depth_levels": [
            {"bid":99.15,"bid_qty":250000,"bid_orders":120,"ask":99.25,"ask_qty":22000,"ask_orders":19},
            {"bid":99.10,"bid_qty":180000,"bid_orders":95,"ask":99.30,"ask_qty":18000,"ask_orders":14},
        ],
    }
    d = depth_dom_intelligence(row)
    assert d["status"] == "READY" and (d["pressure"] or 0) > 80
    c = circuit_candidate(row)
    assert c["status"] == "READY" and c["state"] in {"LOCK IMMINENT", "PRE-CIRCUIT", "ARMING"}

    underlying = {
        "symbol":"TATASTEEL","ltp":170.0,"v72_side":"CE","pre_move_score":88,
        "trigger_price":170.2,"vwap":168.7,"prev_day_low":166.5,
        "depth_intelligence":{"pressure":72},
    }
    strike_pack = {
        "hero_state":"HERO CALL","expiry":"2026-09-24","multi_strike_confirmation":True,
        "winner":{
            "strike":170,"side":"CE","premium":62.0,"score":90,"liquidity":94,"spread_pct":0.8,
            "scores":{"liquidity":94,"premium_response":88,"oi_flow":86,"gamma":80,"theta_risk":24},
        },
    }
    plan = hero_execution_plan("TATASTEEL", underlying, strike_pack, {"status":"READY","stage":"TRIGGER READY","score":84,"side":"CE","leading_evidence":["compression release"]})
    assert plan["status"] == "READY"
    assert plan["targets"]["t1"] > plan["entry"]["ideal"]
    assert plan["risk"]["premium_sl"] < plan["entry"]["ideal"]
    assert plan["targets"]["extended"] is not None

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json().get("version") == "73.0"
    r = client.get("/api/v73/tabs")
    assert r.status_code == 200 and len(r.json().get("tabs") or []) == 8
    r = client.get("/api/v73/status")
    assert r.status_code == 200 and r.json().get("version") == "73.0"
    r = client.get("/")
    assert r.status_code == 200 and "/static/v73-lts.js" in r.text and "/static/v73-lts.css" in r.text
    print("TEST_V73_LTS PASS")


if __name__ == "__main__":
    main()
