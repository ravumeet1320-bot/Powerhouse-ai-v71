from opportunity_engine import build_opportunity_radar

def test_policy_shape():
    r=build_opportunity_radar({"sector_heatmap":[]}, {"side":"WAIT"}, {})
    assert r["decision"]["action"]=="WAIT"
    assert r["policy"]["execution_enabled"] is False
    assert r["policy"]["orders_enabled"] is False

if __name__ == "__main__":
    test_policy_shape()
    print("TEST_V71_5 PASS")
