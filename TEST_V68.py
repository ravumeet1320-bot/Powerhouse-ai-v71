from v63_engine import global_markets_dashboard

m={"upstox_global_markets":{"markets":[
    {"market":"GIFT NIFTY","price":25123.5,"change_pct":0.22,"status":"LIVE","verified":True,"source":"Upstox Global Instruments","provider_latency":"120 Seconds","epoch":9999999999},
    {"market":"DOW JONES","price":45000,"change_pct":0.11,"status":"LIVE","verified":True,"source":"Upstox Global Instruments","epoch":9999999999},
]}}
r=global_markets_dashboard(m)
by={x["market"]:x for x in r["markets"]}
assert by["GIFT NIFTY"]["price"]==25123.5
assert by["DOW JONES"]["price"]==45000
assert "DOW FUTURES" in by and by["DOW FUTURES"]["market"]=="DOW FUTURES"
assert by["DOW JONES"].get("truth_label")!="FUTURES"
assert "yield_curve_10y_2y_bps" in r
print("TEST_V68 PASS — verified global indices, separate futures truth labels, macro yield layer")
