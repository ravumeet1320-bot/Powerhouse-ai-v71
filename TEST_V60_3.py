import gzip, json, time
from upstox_service import UpstoxService

class Resp:
    def __init__(self, content): self.content=content
    def raise_for_status(self): return None

svc=UpstoxService()
svc.access_token='x'*40
rows=[
 {"segment":"NSE_FO","instrument_type":"FUT","underlying_type":"EQUITY","underlying_symbol":"ABC","underlying_key":"NSE_EQ|ABC","instrument_key":"NSE_FO|ABCFUT","expiry":int((time.time()+86400*10)*1000),"lot_size":100},
]
svc.client.get=lambda *a,**k: Resp(gzip.compress(json.dumps(rows).encode()))
svc.discover_full_fno_universe(force=True)
assert svc.fno_foundation_status()['universe_count']==1

def fake_get(url, params=None):
    if 'market-quote/quotes' in url:
        return {"data":{
          "NSE_EQ:ABC":{"instrument_token":"NSE_EQ|ABC","last_price":110,"prev_close_price":100,"volume":100000,"average_price":105,"year_high":140,"year_low":70,"ohlc":{"open":101,"high":112,"low":99,"close":100},"depth":{"buy":[{"price":109.9,"quantity":1000}],"sell":[{"price":110.1,"quantity":800}]}},
          "NSE_FO:ABCFUT":{"instrument_token":"NSE_FO|ABCFUT","last_price":111,"oi":120000,"previous_oi":100000,"volume":50000,"ohlc":{}}
        }}
    raise RuntimeError(url)
svc.get=fake_get
svc.sync_full_fno_quotes(force=True)
r=list(svc.fno_equities.values())[0]
assert round(r['change_pct'],2)==10.0
assert round(r['futures_oi_change_pct'],2)==20.0
assert r['high_52w']==140
print('V60.3 TESTS PASS — dynamic F&O universe, V3 quote enrichment, 52W, futures OI change')
