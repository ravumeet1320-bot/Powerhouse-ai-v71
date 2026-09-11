from __future__ import annotations
from typing import Any
from v62_engine import _f, _symbol_rows
from v65_engine import deal_timeline


def _sym(r: dict) -> str:
    return str(r.get('symbol') or r.get('tradingsymbol') or r.get('name') or '').upper().strip()


def _levels(row: dict) -> list[dict]:
    vals = row.get('depth_levels') or row.get('depth') or []
    if isinstance(vals, dict):
        buys = vals.get('buy') or [] ; sells = vals.get('sell') or []
        out=[]
        for i in range(max(len(buys),len(sells))):
            b=buys[i] if i<len(buys) else {}; s=sells[i] if i<len(sells) else {}
            out.append({'bid':_f(b.get('price') or b.get('bid') or b.get('bid_price')),
                        'bid_qty':_f(b.get('quantity') or b.get('qty') or b.get('bid_qty')),
                        'bid_orders':_f(b.get('orders') or b.get('order_count')),
                        'ask':_f(s.get('price') or s.get('ask') or s.get('ask_price')),
                        'ask_qty':_f(s.get('quantity') or s.get('qty') or s.get('ask_qty')),
                        'ask_orders':_f(s.get('orders') or s.get('order_count'))})
        return out
    out=[]
    for x in vals[:30]:
        if not isinstance(x,dict): continue
        out.append({'bid':_f(x.get('bid') or x.get('bidP') or x.get('bid_price')),
                    'bid_qty':_f(x.get('bid_qty') or x.get('bidQ') or x.get('bid_quantity')),
                    'bid_orders':_f(x.get('bid_orders') or x.get('bidNo') or x.get('bid_order_count')),
                    'ask':_f(x.get('ask') or x.get('askP') or x.get('ask_price')),
                    'ask_qty':_f(x.get('ask_qty') or x.get('askQ') or x.get('ask_quantity')),
                    'ask_orders':_f(x.get('ask_orders') or x.get('askNo') or x.get('ask_order_count'))})
    return out


def depth_intelligence(market: dict[str,Any], symbol: str|None=None) -> dict[str,Any]:
    rows=[r for r in _symbol_rows(market) if isinstance(r,dict)]
    if symbol:
        want=symbol.upper().strip(); rows=[r for r in rows if _sym(r)==want or want in _sym(r)]
    scored=[]
    for r in rows:
        lv=_levels(r)
        if not lv: continue
        bidq=sum((_f(x.get('bid_qty'),0) or 0) for x in lv); askq=sum((_f(x.get('ask_qty'),0) or 0) for x in lv)
        total=bidq+askq
        imbalance=((bidq-askq)/total*100) if total else 0
        bids=[x for x in lv if _f(x.get('bid')) and _f(x.get('bid_qty'))]
        asks=[x for x in lv if _f(x.get('ask')) and _f(x.get('ask_qty'))]
        maxb=max(bids,key=lambda x:_f(x.get('bid_qty'),0) or 0) if bids else None
        maxa=max(asks,key=lambda x:_f(x.get('ask_qty'),0) or 0) if asks else None
        bestb=_f(lv[0].get('bid')) if lv else None; besta=_f(lv[0].get('ask')) if lv else None
        spread=(besta-bestb) if bestb and besta else None
        mid=((besta+bestb)/2) if bestb and besta else None
        spread_bps=(spread/mid*10000) if spread is not None and mid else None
        state='BUY PRESSURE' if imbalance>=18 else 'SELL PRESSURE' if imbalance<=-18 else 'BALANCED'
        quality='STRONG' if len(lv)>=20 else 'PARTIAL' if len(lv)>=5 else 'THIN'
        scored.append({'symbol':_sym(r),'levels':len(lv),'state':state,'depth_quality':quality,
                       'bid_qty_total':round(bidq,2),'ask_qty_total':round(askq,2),'imbalance_pct':round(imbalance,1),
                       'best_bid':bestb,'best_ask':besta,'spread':round(spread,4) if spread is not None else None,
                       'spread_bps':round(spread_bps,2) if spread_bps is not None else None,
                       'largest_bid_wall':maxb,'largest_ask_wall':maxa,'book':lv[:30],
                       'score':round(max(0,min(100,50+imbalance/2)),1),
                       'truth_note':'Anonymous order-book pressure only; it does not identify institutions.'})
    scored.sort(key=lambda x:abs(x['imbalance_pct']),reverse=True)
    return {'status':'READY' if scored else 'UNAVAILABLE','requested_symbol':symbol,'rows':scored[:100],
            'policy':'Uses available Upstox market-depth levels. 30-level mode is requested when supported; otherwise available levels are shown without fabrication.'}


def bulk_block_intelligence(limit:int=200) -> dict[str,Any]:
    raw=deal_timeline(limit).get('rows') or []
    rows=[]
    for d in raw:
        side=str(d.get('side') or '').upper(); val=_f(d.get('value'))
        if val is None:
            q=_f(d.get('quantity')); p=_f(d.get('price')); val=(q*p) if q is not None and p is not None else None
        impact='ACCUMULATION' if side.startswith('B') else 'DISTRIBUTION' if side.startswith('S') else 'TRANSFER/UNKNOWN'
        size_score=0 if val is None else min(40, max(0, __import__('math').log10(abs(val)+1)*5))
        rows.append({'trade_date':d.get('trade_date'),'symbol':d.get('symbol'),'entity':d.get('entity') or d.get('parent_entity'),
                     'deal_type':d.get('deal_type') or 'BULK/BLOCK','side':side or None,'quantity':_f(d.get('quantity')),
                     'price':_f(d.get('price')),'value':val,'category':d.get('category'),'source_url':d.get('source_url'),
                     'verified':bool(d.get('verified')),'interpretation':impact,'impact_score':round(50+size_score if impact=='ACCUMULATION' else 50-size_score if impact=='DISTRIBUTION' else 50,1)})
    return {'status':'READY' if rows else 'UNAVAILABLE','rows':rows,
            'policy':'Only verified deal records from the trusted source registry are surfaced. Deal direction is evidence, not proof of future price direction.'}


def build_v69(market:dict[str,Any]) -> dict[str,Any]:
    depth=depth_intelligence(market)
    deals=bulk_block_intelligence(200)
    return {'version':'69.0','name':'Market Depth + Bulk/Block Smart Money OS','read_only':True,
            'market_depth':depth,'bulk_block':deals,
            'implemented_now':['Up to 30-level normalized market depth','Bid/ask imbalance','Largest bid/ask walls','Spread and spread-bps quality','Depth pressure score','Truth-safe anonymous order-book policy','Verified bulk/block deal timeline','Deal accumulation/distribution interpretation','Deal impact score','Smart-money evidence feed without institution inference from anonymous depth'],
            'feed_truth':{'depth':'LIVE/PARTIAL according to connected Upstox market-data entitlement and payload','deals':'Official/trusted ingested records only; unavailable when no verified source data is present'}}
