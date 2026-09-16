from __future__ import annotations

import json
import math
import gzip
import io
import os
import secrets
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlencode

import httpx

from index_brain import INDEX_UNIVERSES, all_symbols, analyse_index_brains

IST = timezone(timedelta(hours=5, minutes=30))
BASE_V2 = "https://api.upstox.com/v2"
BASE_V3 = "https://api.upstox.com/v3"
NIFTY_KEY_DEFAULT = "NSE_INDEX|Nifty 50"
TOKEN_FILE = Path(__file__).parent / ".runtime" / "upstox_token.json"

BANKNIFTY_KEY_DEFAULT = "NSE_INDEX|Nifty Bank"
SENSEX_KEY_DEFAULT = "BSE_INDEX|SENSEX"
MIDCPNIFTY_KEY_DEFAULT = "NSE_INDEX|NIFTY MID SELECT"

# Broad NSE sector universe for the live heatmap. Quotes are discovered from
# Upstox at runtime; unavailable symbols stay N/A rather than being fabricated.
SECTOR_UNIVERSE = {
    "Banking & Finance": ["HDFCBANK","ICICIBANK","SBIN","AXISBANK","KOTAKBANK","INDUSINDBK","BANKBARODA","PNB","CANBK","FEDERALBNK"],
    "IT": ["INFY","TCS","HCLTECH","WIPRO","TECHM","LTIM","PERSISTENT","COFORGE","MPHASIS"],
    "Auto": ["MARUTI","M&M","TATAMOTORS","BAJAJ-AUTO","EICHERMOT","HEROMOTOCO","TVSMOTOR","ASHOKLEY","BOSCHLTD"],
    "Energy & Oil Gas": ["RELIANCE","ONGC","IOC","BPCL","HINDPETRO","GAIL","OIL","PETRONET"],
    "FMCG": ["ITC","HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","TATACONSUM","COLPAL"],
    "Pharma & Healthcare": ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN","AUROPHARMA","ALKEM","TORNTPHARM","MAXHEALTH","APOLLOHOSP"],
    "Metals": ["TATASTEEL","HINDALCO","JSWSTEEL","VEDL","NMDC","SAIL","JINDALSTEL","HINDZINC"],
    "Realty & Construction": ["DLF","GODREJPROP","OBEROIRLTY","PRESTIGE","PHOENIXLTD","LODHA","LT","NBCC"],
    "Consumer & Retail": ["TITAN","TRENT","ASIANPAINT","PIDILITIND","DMART","HAVELLS","VOLTAS","DIXON"],
    "Telecom & Media": ["BHARTIARTL","IDEA","INDUSTOWER","SUNTV","ZEEL"],
    "Capital Goods & Defence": ["HAL","BEL","BHEL","SIEMENS","ABB","CGPOWER","CUMMINSIND","MAZDOCK"],
    "Cement": ["ULTRACEMCO","GRASIM","AMBUJACEM","ACC","SHREECEM","DALBHARAT"]
}

UNDERLYING_CATALOG = {
    "NIFTY": {"label":"NIFTY 50","key":NIFTY_KEY_DEFAULT,"exchange":"NSE"},
    "BANKNIFTY": {"label":"BANK NIFTY","key":BANKNIFTY_KEY_DEFAULT,"exchange":"NSE"},
    "MIDCPNIFTY": {"label":"NIFTY MID SELECT","key":MIDCPNIFTY_KEY_DEFAULT,"exchange":"NSE","search_query":"NIFTY MID SELECT"},
    "SENSEX": {"label":"SENSEX","key":SENSEX_KEY_DEFAULT,"exchange":"BSE"},
}



def now_ist() -> datetime:
    return datetime.now(IST)


def truthy(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def pct_change(ltp: float, close: float) -> float:
    if not close:
        return 0.0
    return (ltp - close) / close * 100.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class Tick:
    ts: float
    volume: float
    oi: float
    ltp: float


class UpstoxError(RuntimeError):
    pass


class UpstoxAuthError(UpstoxError):
    """Confirmed Upstox authentication failure (HTTP 401 / invalid token)."""
    pass


class UpstoxService:
    """Live Upstox market-data bridge for the NIFTY Powerhouse UI.

    Design:
    - REST option-chain bootstraps the full chain and periodically resynchronizes OI/prev OI.
    - MarketDataStreamerV3, when available, updates LTP/depth/volume/OI/IV/Greeks in real time.
    - If the SDK/websocket is unavailable, the service falls back to a slower REST sync.
    - Browser never receives API secret; access token stays in the local backend process.
    """

    def __init__(self, token_file: Optional[Path] = None) -> None:
        self.token_file = token_file or TOKEN_FILE
        self.api_key = (os.getenv("UPSTOX_API_KEY") or os.getenv("UPSTOX_CLIENT_ID") or "").strip()
        self.api_secret = (os.getenv("UPSTOX_API_SECRET") or os.getenv("UPSTOX_CLIENT_SECRET") or "").strip()
        self.redirect_uri = os.getenv(
            "UPSTOX_REDIRECT_URI", "http://127.0.0.1:8787/api/upstox/callback"
        ).strip()
        self.active_code = "NIFTY"
        self.underlying_key = os.getenv("UPSTOX_UNDERLYING_KEY", NIFTY_KEY_DEFAULT).strip()
        self.strike_window = max(3, int(os.getenv("UPSTOX_STRIKE_WINDOW", "12")))
        self.full_chain_snapshot = truthy(os.getenv("UPSTOX_FULL_CHAIN_SNAPSHOT"), True)
        self.d30_max_keys = max(0, min(50, int(os.getenv("UPSTOX_D30_MAX_KEYS", "36"))))
        self.rest_sync_seconds = max(5, int(os.getenv("UPSTOX_REST_SYNC_SECONDS", "15")))
        self.analytics_sync_seconds = max(
            15, int(os.getenv("UPSTOX_ANALYTICS_SYNC_SECONDS", "45"))
        )
        self.enable_ws = truthy(os.getenv("UPSTOX_ENABLE_WEBSOCKET"), True)
        self.enable_breadth = truthy(os.getenv("UPSTOX_ENABLE_BREADTH"), True)

        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.bg_thread: Optional[threading.Thread] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.streamer = None
        self.streamer_connected = False
        self.streamer_error = ""
        self.subscribed_keys: set[str] = set()
        self.subscribed_mode_by_key: Dict[str, str] = {}

        self.oauth_state: Optional[str] = None
        # Render/server Analytics Token is authoritative when configured. Browser/manual
        # credentials are allowed only for local deployments without an env token.
        self.server_access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        self.server_token_configured = bool(self.server_access_token)
        self.access_token = self.server_access_token
        self.token_source = "env" if self.access_token else ""
        self.token_invalid = False
        self.token_invalid_reason = ""
        self.token_validated_at = 0.0
        self.last_rest_success_ts = 0.0
        self.last_data_error = ""
        if not self.access_token:
            self._load_token_file()

        self.current_expiry: Optional[str] = None
        self.expiries: List[str] = []
        self.chain: Dict[float, Dict[str, Any]] = {}
        self.instrument_lookup: Dict[str, Tuple[float, str]] = {}
        self.history: Dict[str, Deque[Tick]] = defaultdict(lambda: deque(maxlen=1200))
        self.last_rest_sync = 0.0
        self.last_analytics_sync = 0.0
        self.last_message_ts = 0.0
        self.spot = 0.0
        self.spot_close = 0.0
        self.vwap = 0.0
        self.futures_key: Optional[str] = None
        self.futures_ltp = 0.0
        self.futures_atp = 0.0
        self.price_series: Dict[int, List[float]] = {3: [], 5: [], 15: []}
        self.official_max_pain: Optional[float] = None
        self.official_pcr: Optional[float] = None
        self.session_context: Dict[str, Any] = {}
        self.analytics_note = ""
        # High-weight constituent futures are shared across NIFTY/BANKNIFTY.
        # Each symbol is subscribed once, then re-weighted separately by Index Brain.
        self.heavy_futures: Dict[str, Dict[str, Any]] = {}
        self.breadth_ready = False
        self.sector_equities: Dict[str, Dict[str, Any]] = {}
        self.sector_universe_ready = False
        # V60.3 dynamic full F&O foundation (REST snapshot + gradual historical baselines).
        self.fno_equities: Dict[str, Dict[str, Any]] = {}
        self.fno_universe_ready = False
        self.fno_universe_error = ""
        self.fno_last_quote_sync = 0.0
        self.fno_quote_sync_seconds = max(5, int(os.getenv("UPSTOX_FNO_QUOTE_SYNC_SECONDS", "5")))
        self.fno_baselines: Dict[str, Dict[str, Any]] = {}
        self.fno_last_baseline_sync = 0.0
        self.fno_baseline_sync_seconds = max(2, int(os.getenv("UPSTOX_FNO_BASELINE_SYNC_SECONDS", "4")))
        self.fno_baseline_cursor = 0
        self.stock_chain_cache: Dict[str, Dict[str, Any]] = {}
        self.stock_chain_ttl_seconds = max(8, int(os.getenv("UPSTOX_STOCK_CHAIN_TTL_SECONDS", "10")))
        self.index_levels: Dict[str, Dict[str, Any]] = {
            "NIFTY": {"instrument_key": self.underlying_key, "ltp": 0.0, "cp": 0.0},
            "BANKNIFTY": {"instrument_key": BANKNIFTY_KEY_DEFAULT, "ltp": 0.0, "cp": 0.0},
            "MIDCPNIFTY": {"instrument_key": MIDCPNIFTY_KEY_DEFAULT, "ltp": 0.0, "cp": 0.0},
            "SENSEX": {"instrument_key": SENSEX_KEY_DEFAULT, "ltp": 0.0, "cp": 0.0},
        }
        self.index_level_keys: Dict[str, str] = {
            self.underlying_key: "NIFTY",
            BANKNIFTY_KEY_DEFAULT: "BANKNIFTY",
            MIDCPNIFTY_KEY_DEFAULT: "MIDCPNIFTY",
            SENSEX_KEY_DEFAULT: "SENSEX",
        }
        self.iv_proxy = 50.0
        # V68 global-market snapshot cache. Upstox Global Instruments are market
        # indices/indicators, not exchange futures unless the instrument itself says so.
        self.global_instruments: Dict[str, Dict[str, Any]] = {}
        self.global_instruments_loaded_at = 0.0
        self.global_quote_cache: Dict[str, Dict[str, Any]] = {}
        self.global_quote_epoch = 0.0
        self.global_quote_sync_seconds = max(15, int(os.getenv("UPSTOX_GLOBAL_QUOTE_SYNC_SECONDS", "30")))

        self.client = httpx.Client(timeout=12.0, follow_redirects=True)

    # ---------- token/auth ----------
    def _load_token_file(self) -> None:
        try:
            if self.token_file.exists():
                payload = json.loads(self.token_file.read_text())
                token = str(payload.get("access_token", "")).strip()
                if token:
                    self.access_token = token
                    self.token_source = "local_file"
        except Exception:
            pass

    def _save_token_file(self, token: str) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(
            json.dumps(
                {
                    "access_token": token,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
        try:
            os.chmod(self.token_file, 0o600)
        except Exception:
            pass

    def set_manual_token(self, token: str, persist: bool = True) -> None:
        if self.server_token_configured:
            raise UpstoxError("Server Analytics Token is configured; browser token override is disabled.")
        token = token.strip()
        if len(token) < 20:
            raise UpstoxError("Access token looks too short.")
        with self.lock:
            old_token, old_source = self.access_token, self.token_source
            self.access_token = token
            self.token_source = "manual"
            self._reset_live_state_for_new_token()
        try:
            # Validate against a read-only option endpoint before saving. This works
            # for both standard OAuth tokens and the long-lived Analytics Token.
            self.fetch_expiries(force=True)
        except Exception:
            with self.lock:
                self.access_token, self.token_source = old_token, old_source
                self._reset_live_state_for_new_token()
            raise
        if persist:
            self._save_token_file(token)
        self.start_background()

    def clear_token(self) -> None:
        with self.lock:
            self._stop_streamer_locked()
            self.chain.clear()
            self.instrument_lookup.clear()
            self.current_expiry = None
            self.token_invalid = False
            self.token_invalid_reason = ""
            self.token_validated_at = 0.0
            self.last_data_error = ""
            if self.server_token_configured:
                # A browser cannot remove/replace the Render-side Analytics Token.
                self.access_token = self.server_access_token
                self.token_source = "env"
            else:
                self.access_token = ""
                self.token_source = ""
        try:
            # Clear any legacy per-device token file so it can never shadow a future
            # server token after configuration changes.
            self.token_file.unlink(missing_ok=True)
        except Exception:
            pass
        if self.server_token_configured:
            self.start_background()

    def _reset_live_state_for_new_token(self) -> None:
        self._stop_streamer_locked()
        self.chain.clear()
        self.instrument_lookup.clear()
        self.expiries = []
        self.current_expiry = None
        self.last_rest_sync = 0
        self.last_analytics_sync = 0
        self.last_rest_success_ts = 0.0
        self.last_message_ts = 0.0
        self.token_invalid = False
        self.token_invalid_reason = ""
        self.token_validated_at = 0.0
        self.last_data_error = ""
        self.streamer_error = ""

    @property
    def configured_app(self) -> bool:
        return bool(self.api_key and self.api_secret and self.redirect_uri)

    @property
    def authenticated(self) -> bool:
        return bool(self.access_token)

    def oauth_login_url(self) -> str:
        if self.server_token_configured:
            raise UpstoxError("Server Analytics Token is active; browser OAuth override is disabled.")
        if not self.api_key:
            raise UpstoxError("UPSTOX_API_KEY is missing in .env")
        state = secrets.token_urlsafe(24)
        self.oauth_state = state
        qs = urlencode(
            {
                "response_type": "code",
                "client_id": self.api_key,
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        return f"{BASE_V2}/login/authorization/dialog?{qs}"

    def exchange_code(self, code: str, state: Optional[str]) -> Dict[str, Any]:
        if self.server_token_configured:
            raise UpstoxError("Server Analytics Token is active; browser OAuth override is disabled.")
        if not self.configured_app:
            raise UpstoxError("API key, secret, or redirect URI is missing in .env")
        if self.oauth_state and state != self.oauth_state:
            raise UpstoxError("OAuth state mismatch. Start login again.")
        resp = self.client.post(
            f"{BASE_V2}/login/authorization/token",
            headers={
                "accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "code": code,
                "client_id": self.api_key,
                "client_secret": self.api_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        data = self._json_or_error(resp, "token exchange")
        token = str(data.get("access_token", "")).strip()
        if not token:
            raise UpstoxError("Upstox token response did not contain access_token")
        with self.lock:
            self.access_token = token
            self.token_source = "oauth"
            self._reset_live_state_for_new_token()
            self.oauth_state = None
        self._save_token_file(token)
        self.start_background()
        return data

    # ---------- HTTP ----------
    def _headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise UpstoxError("Not authenticated with Upstox")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    @staticmethod
    def _looks_like_auth_failure(value: Any) -> bool:
        text = str(value or "").lower()
        return any(x in text for x in ("udapi100050", "invalid token", "unauthorized", "authentication failed", "401"))

    def _mark_auth_invalid(self, detail: Any) -> None:
        reason = str(detail or "Invalid Upstox token")[:300]
        with self.lock:
            self.token_invalid = True
            self.token_invalid_reason = reason
            self.last_data_error = reason
            self.streamer_error = "TOKEN INVALID"
            self._stop_streamer_locked()

    def _mark_rest_success(self) -> None:
        with self.lock:
            self.last_rest_success_ts = time.time()
            self.token_validated_at = self.token_validated_at or self.last_rest_success_ts
            self.last_data_error = ""
            self.token_invalid = False
            self.token_invalid_reason = ""

    def _json_or_error(self, resp: httpx.Response, label: str) -> Dict[str, Any]:
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text[:800]}
        if resp.status_code == 401:
            msg = payload.get("message") or payload.get("errors") or payload.get("raw") or payload
            detail = f"Upstox {label} failed (401): {msg}"
            self._mark_auth_invalid(detail)
            raise UpstoxAuthError(f"TOKEN INVALID — {detail}")
        if resp.status_code >= 400:
            msg = payload.get("message") or payload.get("errors") or payload.get("raw") or payload
            with self.lock:
                self.last_data_error = f"Upstox {label} failed ({resp.status_code}): {msg}"[:300]
            raise UpstoxError(f"Upstox {label} failed ({resp.status_code}): {msg}")
        if isinstance(payload, dict) and payload.get("status") == "error":
            if self._looks_like_auth_failure(payload):
                self._mark_auth_invalid(payload)
                raise UpstoxAuthError(f"TOKEN INVALID — Upstox {label} error: {payload}")
            with self.lock:
                self.last_data_error = f"Upstox {label} error: {payload}"[:300]
            raise UpstoxError(f"Upstox {label} error: {payload}")
        self._mark_rest_success()
        return payload

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = self.client.get(url, params=params, headers=self._headers())
        return self._json_or_error(resp, url)

    # ---------- instrument discovery ----------

    def resolve_underlying_key(self, code: str) -> str:
        """Resolve index key from official Upstox Instrument Search when needed.

        Catalog keys are safe fallbacks. Dynamic lookup prevents hard-coding an
        index alias when Upstox changes display/trading-symbol conventions.
        """
        code=str(code or "").upper().strip()
        meta=UNDERLYING_CATALOG.get(code)
        if not meta:
            raise UpstoxError(f"Unsupported underlying: {code}")
        query=meta.get("search_query")
        if not query or not self.authenticated:
            return str(meta["key"])
        payload=self.get(f"{BASE_V2}/instruments/search", params={"query":query,"exchanges":meta.get("exchange","NSE"),"page_number":1,"records":30})
        rows=payload.get("data") or []
        want=str(query).upper().replace("_"," ")
        def rank(r):
            name=(str(r.get("name") or "")+" "+str(r.get("trading_symbol") or "")).upper().replace("_"," ")
            typ=str(r.get("instrument_type") or "").upper()
            seg=str(r.get("segment") or "").upper()
            return (0 if typ=="INDEX" else 1, 0 if want in name else 1, 0 if "INDEX" in seg else 1)
        rows=sorted([r for r in rows if r.get("instrument_key")], key=rank)
        return str(rows[0]["instrument_key"]) if rows else str(meta["key"])

    def snapshot_for_underlying(self, code: str) -> Dict[str, Any]:
        """Read-only REST snapshot for any supported index without changing active UI state.

        Used by the V70 all-index Hero Radar. It intentionally exposes unavailable
        history/velocity fields as absent rather than fabricating WebSocket history.
        """
        if not self.authenticated:
            raise UpstoxError("Connect Upstox first")
        code=str(code or "").upper().strip()
        if code not in UNDERLYING_CATALOG:
            raise UpstoxError(f"Unsupported underlying: {code}")
        key=self.resolve_underlying_key(code)
        contracts=self.get(f"{BASE_V2}/option/contract", params={"instrument_key":key}).get("data") or []
        today=now_ist().date().isoformat()
        exps=sorted({str(x.get("expiry")) for x in contracts if x.get("expiry")})
        future=[x for x in exps if x>=today]
        expiry=(future or exps or [None])[0]
        if not expiry:
            return {"ok":False,"source":"upstox_rest","active_underlying":code,"active_label":UNDERLYING_CATALOG[code]["label"],"expiry":None,"option_data":[],"reason":"No option expiry returned"}
        rows=self.get(f"{BASE_V2}/option/chain", params={"instrument_key":key,"expiry_date":expiry}).get("data") or []
        out=[]; spot=safe_float(rows[0].get("underlying_spot_price")) if rows else 0.0
        for item in rows:
            strike=safe_float(item.get("strike_price"));
            if not strike: continue
            c=item.get("call_options") or {}; p=item.get("put_options") or {}; cm=c.get("market_data") or {}; pm=p.get("market_data") or {}; cg=c.get("option_greeks") or {}; pg=p.get("option_greeks") or {}
            coi=safe_float(cm.get("oi"))/100000.0; poi=safe_float(pm.get("oi"))/100000.0; cprev=safe_float(cm.get("prev_oi"),safe_float(cm.get("oi")))/100000.0; pprev=safe_float(pm.get("prev_oi"),safe_float(pm.get("oi")))/100000.0
            cl=safe_float(cm.get("ltp")); pl=safe_float(pm.get("ltp")); cc=safe_float(cm.get("close_price"),cl); pc=safe_float(pm.get("close_price"),pl)
            civ=safe_float(cg.get("iv")); piv=safe_float(pg.get("iv")); civ=civ*100 if civ and civ<2 else civ; piv=piv*100 if piv and piv<2 else piv
            out.append({"s":strike,"coi":coi,"cchg":coi-cprev,"cvol":safe_float(cm.get("volume")),"cltp":cl,"cp":pct_change(cl,cc),"civ":civ,"c_delta":safe_float(cg.get("delta")),"c_gamma":safe_float(cg.get("gamma")),"c_theta":safe_float(cg.get("theta")),"c_vega":safe_float(cg.get("vega")),"cbid":safe_float(cm.get("bid_price"),cl),"cask":safe_float(cm.get("ask_price"),cl),"cbidq":safe_float(cm.get("bid_qty")),"caskq":safe_float(cm.get("ask_qty")),"call_key":c.get("instrument_key"),
                        "poi":poi,"pchg":poi-pprev,"pvol":safe_float(pm.get("volume")),"pltp":pl,"pp":pct_change(pl,pc),"piv":piv,"p_delta":safe_float(pg.get("delta")),"p_gamma":safe_float(pg.get("gamma")),"p_theta":safe_float(pg.get("theta")),"p_vega":safe_float(pg.get("vega")),"pbid":safe_float(pm.get("bid_price"),pl),"pask":safe_float(pm.get("ask_price"),pl),"pbidq":safe_float(pm.get("bid_qty")),"paskq":safe_float(pm.get("ask_qty")),"put_key":p.get("instrument_key")})
        series={} ; session={}
        try:
            encoded=quote(key,safe="")
            candles=self.get(f"{BASE_V3}/historical-candle/intraday/{encoded}/minutes/5").get("data",{}).get("candles") or []
            valid=[c for c in reversed(candles) if isinstance(c,(list,tuple)) and len(c)>=5]
            closes=[safe_float(c[4]) for c in valid if safe_float(c[4])>0][-40:]
            if closes: series["5"]=closes
            if valid:
                opening=valid[:3]; session={"day_open":safe_float(valid[0][1]) or None,"day_high":max(safe_float(c[2]) for c in valid) or None,"day_low":min((safe_float(c[3]) for c in valid if safe_float(c[3])>0),default=0) or None,"last_close":safe_float(valid[-1][4]) or None,"opening_range_high":max(safe_float(c[2]) for c in opening) or None,"opening_range_low":min((safe_float(c[3]) for c in opening if safe_float(c[3])>0),default=0) or None,"opening_range_minutes":15,"candles_seen":len(valid)}
        except Exception:
            pass
        return {"ok":True,"source":"upstox_rest_all_index_scan","active_underlying":code,"active_label":UNDERLYING_CATALOG[code]["label"],"spot":spot or None,"vwap":None,"expiry":expiry,"option_data":out,"price_series":series,"session_context":session,"websocket_connected":False,"last_tick_epoch":time.time(),"analytics_note":"REST all-index scan; short-window option velocity/depth is only available for the active streamed index."}

    def fetch_expiries(self, force: bool = False) -> List[str]:
        with self.lock:
            if self.expiries and not force:
                return list(self.expiries)
        payload = self.get(
            f"{BASE_V2}/option/contract", params={"instrument_key": self.underlying_key}
        )
        rows = payload.get("data") or []
        expiries = sorted({str(x.get("expiry")) for x in rows if x.get("expiry")})
        today = now_ist().date().isoformat()
        future = [x for x in expiries if x >= today]
        with self.lock:
            self.expiries = future or expiries
        return list(self.expiries)

    def _search_future(self, query: str) -> Optional[Dict[str, Any]]:
        try:
            payload = self.get(
                f"{BASE_V2}/instruments/search",
                params={
                    "query": query,
                    "exchanges": "NSE",
                    "segments": "FO",
                    "instrument_types": "FUT",
                    "expiry": "current_month",
                    "page_number": 1,
                    "records": 30,
                },
            )
            rows = payload.get("data") or []
            futs = [r for r in rows if r.get("instrument_type") == "FUT"]
            # Prefer an index future for NIFTY, exact underlying symbol for stocks.
            q = query.upper().replace(" ", "")
            futs.sort(
                key=lambda r: (
                    0
                    if str(r.get("underlying_symbol", "")).upper().replace(" ", "") == q
                    else 1,
                    str(r.get("expiry", "9999")),
                )
            )
            return futs[0] if futs else None
        except Exception:
            return None


    def _search_equity(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            payload = self.get(
                f"{BASE_V2}/instruments/search",
                params={
                    "query": symbol,
                    "exchanges": "NSE",
                    "segments": "EQ",
                    "page_number": 1,
                    "records": 20,
                },
            )
            rows = payload.get("data") or []
            q = symbol.upper().replace(" ", "")
            def norm(v: Any) -> str:
                return str(v or "").upper().replace(" ", "")
            eqs = [r for r in rows if norm(r.get("instrument_type")) in {"EQ","EQUITY"} or norm(r.get("segment")) in {"NSE_EQ","EQ"}]
            eqs.sort(key=lambda r: (
                0 if norm(r.get("trading_symbol") or r.get("symbol")) == q else 1,
                0 if norm(r.get("exchange")) == "NSE" else 1,
            ))
            return eqs[0] if eqs else (rows[0] if rows else None)
        except Exception:
            return None

    def discover_sector_universe(self) -> None:
        if not self.authenticated or self.sector_universe_ready:
            return
        found: Dict[str, Dict[str, Any]] = {}
        # Keep the live heatmap broad but bounded so WebSocket subscription load stays reasonable.
        for sector, symbols in SECTOR_UNIVERSE.items():
            for symbol in symbols:
                eq = self._search_equity(symbol)
                key = (eq or {}).get("instrument_key")
                if key:
                    found[key] = {
                        "symbol": symbol,
                        "sector": sector,
                        "instrument_key": key,
                        "ltp": 0.0,
                        "cp": 0.0,
                    }
        with self.lock:
            self.sector_equities = found
            self.sector_universe_ready = bool(found)

    def _sector_for_symbol(self, symbol: str) -> str:
        q = str(symbol or "").upper()
        for sector, symbols in SECTOR_UNIVERSE.items():
            if q in symbols:
                return sector
        return "F&O"

    @staticmethod
    def _expiry_epoch(value: Any) -> float:
        try:
            if isinstance(value, (int, float)):
                x = float(value)
                return x / 1000.0 if x > 10_000_000_000 else x
            txt = str(value or "")
            if not txt:
                return 9e18
            return datetime.fromisoformat(txt.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 9e18

    def discover_full_fno_universe(self, force: bool = False) -> None:
        """Load the official Upstox NSE BOD instrument file and derive the current equity F&O universe.

        This removes the old static-universe blind spot. It intentionally keeps the quote layer
        REST-based so the existing websocket can stay within subscription limits.
        """
        if self.fno_universe_ready and not force:
            return
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        try:
            r = self.client.get(url, timeout=20.0)
            r.raise_for_status()
            raw = gzip.decompress(r.content)
            rows = json.loads(raw.decode("utf-8"))
            now_ts = time.time()
            futures: Dict[str, Dict[str, Any]] = {}
            eq_keys: Dict[str, str] = {}
            for item in rows:
                if str(item.get("segment")) != "NSE_FO" or str(item.get("instrument_type")) != "FUT":
                    continue
                if str(item.get("underlying_type") or "").upper() != "EQUITY":
                    continue
                sym = str(item.get("underlying_symbol") or "").upper().strip()
                ukey = str(item.get("underlying_key") or "").strip()
                fkey = str(item.get("instrument_key") or "").strip()
                if not sym or not ukey or not fkey:
                    continue
                exp = self._expiry_epoch(item.get("expiry"))
                if exp < now_ts - 86400:
                    continue
                cur = futures.get(sym)
                if cur is None or exp < cur["expiry_epoch"]:
                    futures[sym] = {"future_key": fkey, "expiry_epoch": exp, "expiry": item.get("expiry"), "lot_size": item.get("lot_size")}
                    eq_keys[sym] = ukey
            found: Dict[str, Dict[str, Any]] = {}
            for sym, fut in futures.items():
                eq_key = eq_keys[sym]
                found[eq_key] = {
                    "symbol": sym, "sector": self._sector_for_symbol(sym), "instrument_key": eq_key,
                    "future_key": fut["future_key"], "future_expiry": fut.get("expiry"), "lot_size": fut.get("lot_size"),
                    "ltp": 0.0, "cp": 0.0, "live": False,
                }
            with self.lock:
                self.fno_equities = found
                self.fno_universe_ready = bool(found)
                self.fno_universe_error = "" if found else "No equity F&O instruments found in NSE BOD file"
        except Exception as exc:
            with self.lock:
                self.fno_universe_error = f"F&O universe discovery failed: {exc}"

    def _full_quotes_v3(self, keys: List[str]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(keys), 450):
            batch = [k for k in keys[i:i+450] if k]
            if not batch:
                continue
            payload = self.get(f"{BASE_V3}/market-quote/quotes", params={"instrument_key": ",".join(batch)})
            data = payload.get("data") or {}
            for item in data.values():
                if isinstance(item, dict):
                    key = str(item.get("instrument_token") or item.get("instrument_key") or "")
                    if key:
                        out[key] = item
        return out

    def _load_global_instruments(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        """Load Upstox's official Global Instruments file and index it by normalized name.

        The file is public metadata; prices still require the authenticated quote API.
        """
        if self.global_instruments and not force and time.time() - self.global_instruments_loaded_at < 6 * 3600:
            return self.global_instruments
        url = "https://assets.upstox.com/market-quote/instruments/exchange/global.json.gz"
        try:
            resp = self.client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            raw = resp.content
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
            rows = json.loads(raw.decode("utf-8"))
            found: Dict[str, Dict[str, Any]] = {}
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("name") or row.get("trading_symbol") or "").strip().upper()
                    key = str(row.get("instrument_key") or "").strip()
                    if name and key:
                        found[name] = row
            if found:
                self.global_instruments = found
                self.global_instruments_loaded_at = time.time()
            return self.global_instruments
        except Exception:
            return self.global_instruments

    @staticmethod
    def _global_alias_match(rows: Dict[str, Dict[str, Any]], aliases: List[str]) -> Optional[Dict[str, Any]]:
        for alias in aliases:
            a = alias.upper()
            if a in rows:
                return rows[a]
        for alias in aliases:
            a = alias.upper()
            for name, row in rows.items():
                if a in name:
                    return row
        return None

    def global_market_snapshot(self, force: bool = False) -> Dict[str, Any]:
        """Authenticated Upstox global indices/indicators with explicit latency metadata.

        Only working, verified quote rows are returned. Unavailable global cards are hidden
        instead of occupying the UI with dead feeds. Dow Jones is intentionally excluded.
        """
        now = time.time()
        if self.global_quote_cache and not force and now - self.global_quote_epoch < self.global_quote_sync_seconds:
            return {"status": "READY", "source": "Upstox Global Instruments", "epoch": self.global_quote_epoch,
                    "markets": list(self.global_quote_cache.values())}
        if not self.authenticated:
            return {"status": "UNAVAILABLE", "reason": "Upstox not authenticated", "markets": []}
        instruments = self._load_global_instruments(force=force)
        targets = {
            "GIFT NIFTY": ["GIFT NIFTY"],
            "S&P 500": ["S&P 500", "S&P"],
            "NASDAQ / US TECH 100": ["US TECH 100", "NASDAQ 100", "NASDAQ"],
            "DXY": ["US DOLLAR INDEX", "DOLLAR INDEX", "DXY"],
            "USD/INR": ["USD INR", "USD/INR"],
            "BRENT CRUDE": ["OIL (BRENT)", "BRENT"],
            "WTI CRUDE": ["OIL (WTI)", "WTI"],
            "GOLD": ["GOLD"],
        }
        selected: Dict[str, Dict[str, Any]] = {}
        for display, aliases in targets.items():
            row = self._global_alias_match(instruments, aliases)
            if row:
                selected[display] = row
        # India VIX is a normal NSE index key, not part of the Global file.
        selected["INDIA VIX"] = {"instrument_key": "NSE_INDEX|India VIX", "name": "India VIX", "latency": "exchange/API"}
        keys = [str(r.get("instrument_key")) for r in selected.values() if r.get("instrument_key")]
        quotes = self._full_quotes_v3(keys) if keys else {}
        out: Dict[str, Dict[str, Any]] = {}
        for display, meta in selected.items():
            key = str(meta.get("instrument_key") or "")
            q = quotes.get(key) or {}
            ltp = safe_float(q.get("last_price") or q.get("ltp"))
            cp = safe_float(q.get("prev_close_price") or q.get("cp") or (q.get("ohlc") or {}).get("close"))
            change = ((ltp - cp) / cp * 100.0) if ltp and cp else None
            latency = str(meta.get("latency") or "")
            if not ltp:
                # V71.3: dead/unavailable feeds are intentionally omitted from the product UI.
                continue
            out[display] = {
                "market": display, "price": ltp, "change_pct": round(change, 4) if change is not None else None,
                "status": "LIVE", "verified": True,
                "source": "Upstox Global Instruments" if display != "INDIA VIX" else "Upstox NSE Index",
                "instrument_key": key, "provider_latency": latency or None, "epoch": now,
                "truth_label": "INDEX/INDICATOR" if display not in {"BRENT CRUDE", "WTI CRUDE", "GOLD", "USD/INR", "DXY"} else "GLOBAL INDICATOR",
            }
        self.global_quote_cache = out
        self.global_quote_epoch = now
        return {"status": "READY" if any(x.get("price") for x in out.values()) else "PARTIAL",
                "source": "Upstox Global Instruments", "epoch": now, "markets": list(out.values())}

    def sync_full_fno_quotes(self, force: bool = False) -> None:
        if not self.authenticated:
            return
        if not self.fno_universe_ready:
            self.discover_full_fno_universe()
        if not self.fno_universe_ready:
            return
        if not force and time.time() - self.fno_last_quote_sync < self.fno_quote_sync_seconds:
            return
        with self.lock:
            rows = [dict(x) for x in self.fno_equities.values()]
        keys = []
        for x in rows:
            keys.extend([x.get("instrument_key"), x.get("future_key")])
        quotes = self._full_quotes_v3([k for k in keys if k])
        now = time.time()
        with self.lock:
            for key, row in self.fno_equities.items():
                q = quotes.get(key) or {}
                fq = quotes.get(str(row.get("future_key") or "")) or {}
                ohlc = q.get("ohlc") or {}
                ltp = safe_float(q.get("last_price")); cp = safe_float(q.get("prev_close_price") or ohlc.get("close"))
                depth = q.get("depth") or {}; buys = depth.get("buy") or []; sells = depth.get("sell") or []
                bid = safe_float((buys[0] or {}).get("price")) if buys else 0.0
                ask = safe_float((sells[0] or {}).get("price")) if sells else 0.0
                bq = safe_float((buys[0] or {}).get("quantity")) if buys else 0.0
                aq = safe_float((sells[0] or {}).get("quantity")) if sells else 0.0
                depth_levels=[]
                for i in range(max(len(buys),len(sells),0)):
                    b=(buys[i] if i < len(buys) else {}) or {}; a=(sells[i] if i < len(sells) else {}) or {}
                    level={
                        "bid": safe_float(b.get("price")) or None, "bid_qty": safe_float(b.get("quantity")) or None,
                        "bid_orders": int(safe_float(b.get("orders"),0) or 0) or None,
                        "ask": safe_float(a.get("price")) or None, "ask_qty": safe_float(a.get("quantity")) or None,
                        "ask_orders": int(safe_float(a.get("orders"),0) or 0) or None,
                    }
                    if any(v is not None for v in level.values()): depth_levels.append(level)
                row.update({
                    "ltp": ltp or row.get("ltp") or 0.0, "cp": cp or row.get("cp") or 0.0,
                    "change_pct": pct_change(ltp, cp) if ltp and cp else None,
                    "volume": safe_float(q.get("volume") or ohlc.get("volume")) or None,
                    "day_open": safe_float(ohlc.get("open")) or None, "day_high": safe_float(ohlc.get("high")) or None,
                    "day_low": safe_float(ohlc.get("low")) or None, "high_52w": safe_float(q.get("year_high")) or None,
                    "low_52w": safe_float(q.get("year_low")) or None, "atp": safe_float(q.get("average_price")) or None,
                    "bid": bid or None, "ask": ask or None, "bid_qty": bq or None, "ask_qty": aq or None,
                    "depth_levels": depth_levels or row.get("depth_levels") or [],
                    "total_buy_qty": safe_float(q.get("total_buy_quantity")) or None,
                    "total_sell_qty": safe_float(q.get("total_sell_quantity")) or None,
                    "lower_circuit_limit": safe_float(q.get("lower_circuit_limit")) or None,
                    "upper_circuit_limit": safe_float(q.get("upper_circuit_limit")) or None,
                    "reference_price": safe_float(q.get("reference_price")) or None,
                    "indicative_equilibrium_price": safe_float(q.get("indicative_equilibrium_price")) or None,
                    "indicative_equilibrium_quantity": safe_float(q.get("indicative_equilibrium_quantity")) or None,
                    "indicative_imbalance_quantity_total": safe_float(q.get("indicative_imbalance_quantity_total")) or None,
                    "cas_eligible": q.get("cas_eligible"),
                    "live": bool(ltp and cp), "quote_epoch": now,
                })
                oi = safe_float(fq.get("oi")); prev_oi = safe_float(fq.get("previous_oi"))
                row["futures_oi"] = oi or None; row["futures_prev_oi"] = prev_oi or None
                row["futures_oi_change_pct"] = ((oi-prev_oi)/prev_oi*100.0) if oi and prev_oi else None
                row["futures_ltp"] = safe_float(fq.get("last_price")) or None
                row["futures_volume"] = safe_float(fq.get("volume") or (fq.get("ohlc") or {}).get("volume")) or None
                base = self.fno_baselines.get(row.get("symbol") or "") or {}
                row.update({k:v for k,v in base.items() if v is not None})
            self.fno_last_quote_sync = now

    @staticmethod
    def _parse_candle_ts(v: Any) -> Optional[datetime]:
        try:
            if isinstance(v, (int, float)):
                x=float(v); x=x/1000 if x>10_000_000_000 else x
                return datetime.fromtimestamp(x, tz=timezone.utc).astimezone(IST)
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(IST)
        except Exception:
            return None

    def _hydrate_fno_baseline(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = str(row.get("instrument_key") or ""); sym = str(row.get("symbol") or "")
        if not key or not sym:
            return None
        today = now_ist().date(); to_date=(today-timedelta(days=1)).isoformat(); from_daily=(today-timedelta(days=90)).isoformat()
        encoded=quote(key, safe="")
        daily = self.get(f"{BASE_V3}/historical-candle/{encoded}/days/1/{to_date}/{from_daily}")
        dc = ((daily.get("data") or {}).get("candles") or [])
        dvalid=[c for c in dc if isinstance(c,(list,tuple)) and len(c)>=6]
        # API usually returns newest first; sort by timestamp where possible.
        dvalid.sort(key=lambda c: str(c[0]))
        highs=[safe_float(c[2]) for c in dvalid if safe_float(c[2])>0]
        lows=[safe_float(c[3]) for c in dvalid if safe_float(c[3])>0]
        vols=[safe_float(c[5]) for c in dvalid if safe_float(c[5])>0]
        prev=dvalid[-1] if dvalid else None
        out={
            "prev_day_high": safe_float(prev[2]) if prev else None, "prev_day_low": safe_float(prev[3]) if prev else None,
            "prev_day_close": safe_float(prev[4]) if prev else None,
            "high_20d": max(highs[-20:]) if highs else None, "low_20d": min(lows[-20:]) if lows else None,
            "high_50d": max(highs[-50:]) if highs else None, "low_50d": min(lows[-50:]) if lows else None,
            "avg_volume_20d": statistics.mean(vols[-20:]) if vols else None,
        }
        # True same-time-of-day cumulative RVOL baseline from prior 5-minute sessions.
        from_intr=(today-timedelta(days=18)).isoformat()
        intr=self.get(f"{BASE_V3}/historical-candle/{encoded}/minutes/5/{to_date}/{from_intr}")
        ic=((intr.get("data") or {}).get("candles") or [])
        cutoff=now_ist().hour*60+now_ist().minute
        byday: Dict[str,float]=defaultdict(float)
        for c in ic:
            if not isinstance(c,(list,tuple)) or len(c)<6: continue
            dt=self._parse_candle_ts(c[0]); vol=safe_float(c[5])
            if not dt or not vol: continue
            if dt.hour*60+dt.minute <= cutoff:
                byday[dt.date().isoformat()] += vol
        hist=[v for _,v in sorted(byday.items()) if v>0][-10:]
        cur_vol=safe_float(row.get("volume"))
        if len(hist)>=3 and cur_vol:
            avg=statistics.mean(hist)
            out["rvol"] = cur_vol/avg if avg>0 else None
            out["rvol_sessions"] = len(hist)
            out["rvol_baseline_volume"] = avg
        out["baseline_epoch"] = time.time()
        return out

    def hydrate_next_fno_baseline(self) -> None:
        if not self.authenticated or not self.fno_universe_ready:
            return
        if time.time()-self.fno_last_baseline_sync < self.fno_baseline_sync_seconds:
            return
        with self.lock:
            rows=[dict(x) for x in self.fno_equities.values()]
        if not rows:
            return
        # Prioritize active movers/volume, then rotate so coverage eventually reaches the whole F&O universe.
        rows.sort(key=lambda r:(abs(safe_float(r.get("change_pct"))), safe_float(r.get("volume"))), reverse=True)
        pool=rows[:40] + rows[40:]
        row=pool[self.fno_baseline_cursor % len(pool)]
        self.fno_baseline_cursor += 1
        try:
            base=self._hydrate_fno_baseline(row)
            if base:
                sym=str(row.get("symbol") or "")
                with self.lock:
                    self.fno_baselines[sym]=base
                    target=self.fno_equities.get(str(row.get("instrument_key") or ""))
                    if target: target.update(base)
        except Exception as exc:
            with self.lock:
                self.analytics_note = (self.analytics_note + "; " if self.analytics_note else "") + f"baseline {row.get('symbol')} unavailable: {exc}"
        self.fno_last_baseline_sync=time.time()

    def fno_foundation_status(self) -> Dict[str, Any]:
        with self.lock:
            rows=[dict(x) for x in self.fno_equities.values()]
            now=time.time()
            fresh=sum(1 for x in rows if x.get("quote_epoch") and now-safe_float(x.get("quote_epoch"))<=10)
            ltpc=sum(1 for k,m in self.subscribed_mode_by_key.items() if m=="ltpc" and k in self.fno_equities)
            return {
                "ready": self.fno_universe_ready, "error": self.fno_universe_error,
                "universe_count": len(rows), "live_quotes": sum(1 for x in rows if x.get("live")),
                "fresh_under_10s": fresh, "websocket_census_subscribed": ltpc,
                "rvol_ready": sum(1 for x in rows if x.get("rvol") is not None),
                "structure_ready": sum(1 for x in rows if x.get("prev_day_high") is not None),
                "futures_oi_ready": sum(1 for x in rows if x.get("futures_oi_change_pct") is not None),
                "year_range_ready": sum(1 for x in rows if x.get("high_52w") is not None),
                "last_quote_sync": self.fno_last_quote_sync, "baseline_symbols": len(self.fno_baselines),
                "subscription_modes": {m:sum(1 for x in self.subscribed_mode_by_key.values() if x==m) for m in ("ltpc","full","full_d30")},
                "source": "Upstox NSE BOD + LTPC census + Full Market Quotes V3 + Historical Candle V3",
            }

    def discover_aux_instruments(self) -> None:
        if not self.authenticated:
            return
        if not self.futures_key:
            fut = self._search_future("BANKNIFTY" if self.active_code == "BANKNIFTY" else self.active_code)
            if fut:
                self.futures_key = fut.get("instrument_key")
        if self.enable_breadth and not self.breadth_ready:
            found: Dict[str, Dict[str, Any]] = {}
            # Discover one current-month future per unique high-impact stock.
            # The same runtime price can feed multiple index weighting systems.
            for symbol in all_symbols():
                fut = self._search_future(symbol)
                if fut and fut.get("instrument_key"):
                    found[fut["instrument_key"]] = {
                        "query": symbol,
                        "name": symbol,
                        "instrument_key": fut["instrument_key"],
                        "ltp": 0.0,
                        "cp": 0.0,
                    }
            with self.lock:
                self.heavy_futures = found
                self.breadth_ready = bool(found)
        self.discover_sector_universe()

    # ---------- chain ----------
    def sync_chain_rest(self, expiry: Optional[str] = None) -> None:
        if not self.authenticated:
            return
        if expiry:
            self.current_expiry = expiry
        if not self.current_expiry:
            exps = self.fetch_expiries()
            if not exps:
                raise UpstoxError(f"No {self.active_code} option expiries returned by Upstox")
            self.current_expiry = exps[0]

        payload = self.get(
            f"{BASE_V2}/option/chain",
            params={
                "instrument_key": self.underlying_key,
                "expiry_date": self.current_expiry,
            },
        )
        rows = payload.get("data") or []
        if not rows:
            raise UpstoxError("Upstox option chain returned no rows")

        new_chain: Dict[float, Dict[str, Any]] = {}
        new_lookup: Dict[str, Tuple[float, str]] = {}
        spot = safe_float(rows[0].get("underlying_spot_price"), self.spot)

        for item in rows:
            strike = safe_float(item.get("strike_price"))
            if not strike:
                continue
            c = item.get("call_options") or {}
            p = item.get("put_options") or {}
            cm = c.get("market_data") or {}
            pm = p.get("market_data") or {}
            cg = c.get("option_greeks") or {}
            pg = p.get("option_greeks") or {}

            c_oi_raw = safe_float(cm.get("oi"))
            p_oi_raw = safe_float(pm.get("oi"))
            c_prev_raw = safe_float(cm.get("prev_oi"), c_oi_raw)
            p_prev_raw = safe_float(pm.get("prev_oi"), p_oi_raw)
            c_oi = c_oi_raw / 100000.0
            p_oi = p_oi_raw / 100000.0
            c_prev = c_prev_raw / 100000.0
            p_prev = p_prev_raw / 100000.0
            c_ltp = safe_float(cm.get("ltp"))
            p_ltp = safe_float(pm.get("ltp"))
            c_close = safe_float(cm.get("close_price"), c_ltp)
            p_close = safe_float(pm.get("close_price"), p_ltp)
            c_iv = safe_float(cg.get("iv"))
            p_iv = safe_float(pg.get("iv"))
            if c_iv and c_iv < 2:
                c_iv *= 100
            if p_iv and p_iv < 2:
                p_iv *= 100

            row = {
                "s": strike,
                "coi": c_oi,
                "cchg": c_oi - c_prev,
                "cvol": safe_float(cm.get("volume")),
                "cltp": c_ltp,
                "cp": pct_change(c_ltp, c_close),
                "civ": c_iv,
                "c_delta": safe_float(cg.get("delta")),
                "c_gamma": safe_float(cg.get("gamma")),
                "c_theta": safe_float(cg.get("theta")),
                "c_vega": safe_float(cg.get("vega")),
                "poi": p_oi,
                "pchg": p_oi - p_prev,
                "pvol": safe_float(pm.get("volume")),
                "pltp": p_ltp,
                "pp": pct_change(p_ltp, p_close),
                "piv": p_iv,
                "p_delta": safe_float(pg.get("delta")),
                "p_gamma": safe_float(pg.get("gamma")),
                "p_theta": safe_float(pg.get("theta")),
                "p_vega": safe_float(pg.get("vega")),
                "cbid": safe_float(cm.get("bid_price"), c_ltp),
                "cask": safe_float(cm.get("ask_price"), c_ltp),
                "cbidq": safe_float(cm.get("bid_qty")),
                "caskq": safe_float(cm.get("ask_qty")),
                "pbid": safe_float(pm.get("bid_price"), p_ltp),
                "pask": safe_float(pm.get("ask_price"), p_ltp),
                "pbidq": safe_float(pm.get("bid_qty")),
                "paskq": safe_float(pm.get("ask_qty")),
                "call_key": c.get("instrument_key"),
                "put_key": p.get("instrument_key"),
                "call_close": c_close,
                "put_close": p_close,
            }
            new_chain[strike] = row
            if row["call_key"]:
                new_lookup[row["call_key"]] = (strike, "C")
                self._record_history(row["call_key"], row["cvol"], row["coi"], row["cltp"])
            if row["put_key"]:
                new_lookup[row["put_key"]] = (strike, "P")
                self._record_history(row["put_key"], row["pvol"], row["poi"], row["pltp"])

        with self.lock:
            # Preserve freshest websocket fields if the same strike already exists.
            old = self.chain
            for strike, row in new_chain.items():
                prev = old.get(strike)
                if prev and self.streamer_connected:
                    for key in (
                        "cltp",
                        "cvol",
                        "coi",
                        "civ",
                        "cbid",
                        "cask",
                        "cbidq",
                        "caskq",
                        "pltp",
                        "pvol",
                        "poi",
                        "piv",
                        "pbid",
                        "pask",
                        "pbidq",
                        "paskq",
                    ):
                        if prev.get(key) not in (None, 0, 0.0):
                            row[key] = prev[key]
                self.chain[strike] = row
            # replace, do not leave expired/out-of-scope rows behind
            self.chain = {k: self.chain[k] for k in new_chain.keys()}
            self.instrument_lookup = new_lookup
            self.spot = spot or self.spot
            if self.spot:
                self.index_levels.setdefault(self.active_code, {"instrument_key": self.underlying_key, "ltp":0.0, "cp":0.0})["ltp"] = self.spot
            self.last_rest_sync = time.time()
            self._refresh_iv_proxy_locked()
        self.discover_aux_instruments()
        self._ensure_streamer_subscriptions()

    def set_underlying(self, code: str) -> None:
        code = str(code or "").upper().strip()
        if code not in UNDERLYING_CATALOG:
            raise UpstoxError(f"Unsupported underlying: {code}")
        meta = dict(UNDERLYING_CATALOG[code])
        if self.authenticated and meta.get("search_query"):
            try:
                meta["key"] = self.resolve_underlying_key(code)
            except Exception:
                pass
        with self.lock:
            changed = code != self.active_code
            if not changed:
                return
            self._stop_streamer_locked()
            self.active_code = code
            self.underlying_key = meta["key"]
            self.index_levels.setdefault(code, {"instrument_key": self.underlying_key, "ltp":0.0, "cp":0.0})
            self.index_levels[code]["instrument_key"] = self.underlying_key
            # underlying key must win over the generic index-level handler
            self.index_level_keys = {
                NIFTY_KEY_DEFAULT: "NIFTY",
                BANKNIFTY_KEY_DEFAULT: "BANKNIFTY",
                MIDCPNIFTY_KEY_DEFAULT: "MIDCPNIFTY",
                SENSEX_KEY_DEFAULT: "SENSEX",
            }
            self.chain.clear()
            self.instrument_lookup.clear()
            self.expiries = []
            self.current_expiry = None
            self.history.clear()
            self.spot = self.index_levels.get(code, {}).get("ltp") or 0.0
            self.spot_close = self.index_levels.get(code, {}).get("cp") or 0.0
            self.vwap = 0.0
            self.futures_key = None
            self.futures_ltp = 0.0
            self.futures_atp = 0.0
            self.last_rest_sync = 0.0
            self.last_analytics_sync = 0.0
        if self.authenticated:
            self.fetch_expiries(force=True)
            self.sync_chain_rest()
            self.discover_aux_instruments()
            self._ensure_streamer_subscriptions()

    def set_expiry(self, expiry: str) -> None:
        if not expiry:
            raise UpstoxError("Expiry is required")
        with self.lock:
            changed = expiry != self.current_expiry
            self.current_expiry = expiry
            if changed:
                self.chain.clear()
                self.instrument_lookup.clear()
        self.sync_chain_rest(expiry)

    def _refresh_iv_proxy_locked(self) -> None:
        vals: List[float] = []
        for r in self.chain.values():
            for k in ("civ", "piv"):
                v = safe_float(r.get(k))
                if 1 <= v <= 300:
                    vals.append(v)
        if vals:
            med = statistics.median(vals)
            # Explicitly a regime proxy, not a historical IV rank.
            self.iv_proxy = clamp(15 + (med - 8) * 2.5, 5, 95)

    # ---------- live stream ----------
    def _selected_option_keys_locked(self) -> List[str]:
        if not self.chain:
            return []
        strikes = sorted(self.chain)
        spot = self.spot or statistics.median(strikes)
        idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        lo = max(0, idx - self.strike_window)
        hi = min(len(strikes), idx + self.strike_window + 1)
        keys: List[str] = []
        for strike in strikes[lo:hi]:
            r = self.chain[strike]
            if r.get("call_key"):
                keys.append(r["call_key"])
            if r.get("put_key"):
                keys.append(r["put_key"])
        return keys

    def _desired_subscription_keys_locked(self) -> set[str]:
        plan = self._desired_subscription_plan_locked()
        out: set[str] = set()
        for keys in plan.values():
            out.update(keys)
        return out

    def _desired_subscription_plan_locked(self) -> Dict[str, set[str]]:
        """Tiered V71 subscription plan.

        Every discovered F&O equity gets lightweight LTPC telemetry. Richer full/full_d30
        modes are reserved for active index/options and high-context instruments so that
        one expensive mode cannot exhaust the feed entitlement and create blind spots.
        """
        rich = set(self._selected_option_keys_locked())
        rich.add(self.underlying_key)
        if self.futures_key:
            rich.add(self.futures_key)
        rich.update(self.index_level_keys.keys())
        rich.update(self.heavy_futures.keys())
        rich.update(self.sector_equities.keys())

        census = set(self.fno_equities.keys())
        # Do not duplicate a key in LTPC and a richer mode.
        census -= rich

        d30: set[str] = set()
        if os.getenv("UPSTOX_DEPTH_30", "1") == "1" and self.d30_max_keys > 0:
            # Deep-book priority: the currently selected option strikes first.
            for k in self._selected_option_keys_locked():
                if len(d30) >= self.d30_max_keys:
                    break
                d30.add(k)
        full = rich - d30
        return {"ltpc": {k for k in census if k}, "full": {k for k in full if k}, "full_d30": {k for k in d30 if k}}

    def _subscribe_plan(self, streamer: Any, plan: Dict[str, set[str]]) -> Dict[str, str]:
        applied: Dict[str, str] = {}
        # LTPC first: universal low-cost observation coverage.
        if plan.get("ltpc"):
            keys = sorted(plan["ltpc"])
            streamer.subscribe(keys, "ltpc")
            applied.update({k: "ltpc" for k in keys})
        if plan.get("full"):
            keys = sorted(plan["full"])
            streamer.subscribe(keys, "full")
            applied.update({k: "full" for k in keys})
        if plan.get("full_d30"):
            keys = sorted(plan["full_d30"])
            try:
                streamer.subscribe(keys, "full_d30")
                applied.update({k: "full_d30" for k in keys})
            except Exception:
                # Truthful degradation: keep the same instruments observed in full mode.
                streamer.subscribe(keys, "full")
                applied.update({k: "full" for k in keys})
        return applied

    def _ensure_streamer_subscriptions(self) -> None:
        if not self.enable_ws or not self.authenticated:
            return
        with self.lock:
            plan = self._desired_subscription_plan_locked()
            streamer = self.streamer
            connected = self.streamer_connected
            existing = dict(self.subscribed_mode_by_key)

        if not streamer:
            self._start_streamer_thread()
            return
        if not connected:
            return

        desired_mode: Dict[str, str] = {}
        for mode, keys in plan.items():
            desired_mode.update({k: mode for k in keys})
        remove = sorted(set(existing) - set(desired_mode))
        changed = sorted(k for k, mode in desired_mode.items() if existing.get(k) not in (None, mode))
        add_by_mode: Dict[str, list[str]] = {"ltpc": [], "full": [], "full_d30": []}
        for k, mode in desired_mode.items():
            if existing.get(k) is None or k in changed:
                add_by_mode[mode].append(k)
        try:
            if remove or changed:
                streamer.unsubscribe(sorted(set(remove + changed)))
            applied = {k: v for k, v in existing.items() if k not in set(remove + changed)}
            for mode in ("ltpc", "full", "full_d30"):
                keys = sorted(add_by_mode[mode])
                if not keys:
                    continue
                try:
                    streamer.subscribe(keys, mode)
                    applied.update({k: mode for k in keys})
                except Exception:
                    if mode == "full_d30":
                        streamer.subscribe(keys, "full")
                        applied.update({k: "full" for k in keys})
                    else:
                        raise
            with self.lock:
                self.subscribed_mode_by_key = applied
                self.subscribed_keys = set(applied)
        except Exception as exc:
            with self.lock:
                self.streamer_error = f"subscription update: {exc}"

    def _start_streamer_thread(self) -> None:
        if self.token_invalid or not self.authenticated:
            return
        if self.ws_thread and self.ws_thread.is_alive():
            return

        def runner() -> None:
            try:
                import upstox_client  # type: ignore

                configuration = upstox_client.Configuration()
                configuration.access_token = self.access_token
                streamer = upstox_client.MarketDataStreamerV3(
                    upstox_client.ApiClient(configuration)
                )
                try:
                    streamer.auto_reconnect(True, 5, 20)
                except Exception:
                    pass

                def on_open() -> None:
                    with self.lock:
                        self.streamer_connected = True
                        self.streamer_error = ""
                        plan = self._desired_subscription_plan_locked()
                    applied = self._subscribe_plan(streamer, plan)
                    with self.lock:
                        self.subscribed_mode_by_key = applied
                        self.subscribed_keys = set(applied)

                def on_message(message: Dict[str, Any]) -> None:
                    self._handle_stream_message(message)

                def on_error(error: Any) -> None:
                    if self._looks_like_auth_failure(error):
                        self._mark_auth_invalid(error)
                        try:
                            streamer.disconnect()
                        except Exception:
                            pass
                        return
                    with self.lock:
                        self.streamer_error = str(error)
                        self.last_data_error = str(error)[:300]

                def on_close(*_args: Any) -> None:
                    with self.lock:
                        self.streamer_connected = False

                streamer.on("open", on_open)
                streamer.on("message", on_message)
                streamer.on("error", on_error)
                streamer.on("close", on_close)
                with self.lock:
                    self.streamer = streamer
                streamer.connect()
            except Exception as exc:
                with self.lock:
                    self.streamer_connected = False
                    self.streamer_error = f"WebSocket unavailable: {exc}"
                    self.streamer = None

        self.ws_thread = threading.Thread(target=runner, name="upstox-streamer", daemon=True)
        self.ws_thread.start()

    def _stop_streamer_locked(self) -> None:
        s = self.streamer
        self.streamer = None
        self.streamer_connected = False
        self.subscribed_keys.clear()
        self.subscribed_mode_by_key.clear()
        if s:
            try:
                s.disconnect()
            except Exception:
                pass

    def _handle_stream_message(self, message: Dict[str, Any]) -> None:
        feeds = message.get("feeds") or {}
        ts_ms = safe_float(message.get("currentTs"), time.time() * 1000)
        ts = ts_ms / 1000 if ts_ms > 10_000_000_000 else time.time()
        with self.lock:
            self.last_message_ts = ts

        for key, raw in feeds.items():
            root = raw.get("firstLevelWithGreeks")
            if root is None:
                ff = raw.get("fullFeed") or raw.get("ff") or {}
                root = ff.get("marketFF") or ff.get("indexFF")
            if root is None:
                # LTPC mode has the payload directly under raw["ltpc"].
                root = raw.get("ltpc") or raw
            if not isinstance(root, dict):
                continue

            ltpc = root.get("ltpc") or {}
            if not ltpc and "ltp" in root:
                ltpc = root
            ltp = safe_float(ltpc.get("ltp"))
            cp = safe_float(ltpc.get("cp"))

            if key == self.underlying_key:
                with self.lock:
                    if ltp:
                        self.spot = ltp
                        self.index_levels.setdefault(self.active_code, {"instrument_key": self.underlying_key, "ltp":0.0, "cp":0.0})["ltp"] = ltp
                    if cp:
                        self.spot_close = cp
                        self.index_levels.setdefault(self.active_code, {"instrument_key": self.underlying_key, "ltp":0.0, "cp":0.0})["cp"] = cp
                continue

            if key in self.index_level_keys:
                code = self.index_level_keys[key]
                with self.lock:
                    if ltp:
                        self.index_levels[code]["ltp"] = ltp
                    if cp:
                        self.index_levels[code]["cp"] = cp
                continue

            if key == self.futures_key:
                with self.lock:
                    if ltp:
                        self.futures_ltp = ltp
                    atp = safe_float(root.get("atp"))
                    if atp:
                        self.futures_atp = atp
                    self._update_spot_vwap_from_future_locked()
                continue

            if key in self.heavy_futures:
                with self.lock:
                    h = self.heavy_futures[key]
                    if ltp:
                        h["ltp"] = ltp
                    if cp:
                        h["cp"] = cp
                continue

            if key in self.fno_equities:
                with self.lock:
                    h = self.fno_equities[key]
                    if ltp:
                        h["ltp"] = ltp
                    if cp:
                        h["cp"] = cp
                    h["change_pct"] = pct_change(safe_float(h.get("ltp")), safe_float(h.get("cp"))) if safe_float(h.get("ltp")) and safe_float(h.get("cp")) else h.get("change_pct")
                    h["live"] = bool(safe_float(h.get("ltp")) and safe_float(h.get("cp")))
                    h["quote_epoch"] = ts
                    vol = safe_float(root.get("vtt") or root.get("volume"))
                    if vol:
                        h["volume"] = vol
                    atp = safe_float(root.get("atp"))
                    if atp:
                        h["atp"] = atp
                    tbq = safe_float(root.get("tbq")); tsq = safe_float(root.get("tsq"))
                    if tbq is not None: h["total_buy_qty"] = tbq
                    if tsq is not None: h["total_sell_qty"] = tsq
                    rp = safe_float(root.get("rp"))
                    if rp is not None: h["reference_price"] = rp
                    quotes = ((root.get("marketLevel") or {}).get("bidAskQuote") or [])
                    if quotes:
                        norm=[]
                        for q in quotes[:30]:
                            q=q or {}
                            bp=safe_float(q.get("bidP") or q.get("bid_price")); ap=safe_float(q.get("askP") or q.get("ask_price"))
                            bq=safe_float(q.get("bidQ") or q.get("bid_qty")); aq=safe_float(q.get("askQ") or q.get("ask_qty"))
                            if any((bp,ap,bq,aq)):
                                norm.append({"bid":bp or None,"ask":ap or None,"bid_qty":bq or None,"ask_qty":aq or None})
                        h["depth_levels"] = norm
                        q0=quotes[0] or {}
                        bp=safe_float(q0.get("bidP") or q0.get("bid_price")); ap=safe_float(q0.get("askP") or q0.get("ask_price"))
                        bq=safe_float(q0.get("bidQ") or q0.get("bid_qty")); aq=safe_float(q0.get("askQ") or q0.get("ask_qty"))
                        if bp: h["bid"] = bp
                        if ap: h["ask"] = ap
                        if bq: h["bid_qty"] = bq
                        if aq: h["ask_qty"] = aq
                # A symbol can also be present in the legacy sector universe; let that
                # block update too, otherwise the universal census update is complete.
                if key not in self.sector_equities:
                    continue

            if key in self.sector_equities:
                with self.lock:
                    h = self.sector_equities[key]
                    if ltp: h["ltp"] = ltp
                    if cp: h["cp"] = cp
                    vol = safe_float(root.get("vtt") or root.get("volume"))
                    if vol: h["volume"] = vol
                    quotes = ((root.get("marketLevel") or {}).get("bidAskQuote") or [])
                    if quotes:
                        norm=[]
                        for q in quotes[:30]:
                            q=q or {}
                            bp=safe_float(q.get("bidP") or q.get("bid_price")); ap=safe_float(q.get("askP") or q.get("ask_price"))
                            bq=safe_float(q.get("bidQ") or q.get("bid_qty")); aq=safe_float(q.get("askQ") or q.get("ask_qty"))
                            if any((bp,ap,bq,aq)): norm.append({"bid":bp or None,"ask":ap or None,"bid_qty":bq or None,"ask_qty":aq or None})
                        h["depth_levels"] = norm
                        q0 = quotes[0] or {}
                        bp=safe_float(q0.get("bidP") or q0.get("bid_price")); ap=safe_float(q0.get("askP") or q0.get("ask_price"))
                        bq=safe_float(q0.get("bidQ") or q0.get("bid_qty")); aq=safe_float(q0.get("askQ") or q0.get("ask_qty"))
                        if bp: h["bid"] = bp
                        if ap: h["ask"] = ap
                        if bq: h["bid_qty"] = bq
                        if aq: h["ask_qty"] = aq
                continue

            with self.lock:
                loc = self.instrument_lookup.get(key)
            if not loc:
                continue
            strike, side = loc
            with self.lock:
                row = self.chain.get(strike)
                if not row:
                    continue
                depth = root.get("firstDepth") or {}
                if not depth:
                    quotes = ((root.get("marketLevel") or {}).get("bidAskQuote") or [])
                    depth = quotes[0] if quotes else {}
                greeks = root.get("optionGreeks") or {}
                vtt = safe_float(root.get("vtt"))
                oi_raw = safe_float(root.get("oi"))
                oi = oi_raw / 100000.0 if oi_raw else 0.0
                iv = safe_float(root.get("iv"))
                if iv and iv < 2:
                    iv *= 100
                prefix = "c" if side == "C" else "p"
                full_quotes = ((root.get("marketLevel") or {}).get("bidAskQuote") or [])
                if full_quotes:
                    norm=[]
                    for q in full_quotes[:30]:
                        q=q or {}
                        bp=safe_float(q.get("bidP") or q.get("bid_price")); ap=safe_float(q.get("askP") or q.get("ask_price"))
                        bq=safe_float(q.get("bidQ") or q.get("bid_qty")); aq=safe_float(q.get("askQ") or q.get("ask_qty"))
                        if any((bp,ap,bq,aq)): norm.append({"bid":bp or None,"ask":ap or None,"bid_qty":bq or None,"ask_qty":aq or None})
                    row[f"{prefix}depth"] = norm
                if ltp:
                    row[f"{prefix}ltp"] = ltp
                if vtt:
                    row[f"{prefix}vol"] = vtt
                if oi:
                    row[f"{prefix}oi"] = oi
                if iv:
                    row[f"{prefix}iv"] = iv
                if cp:
                    close_key = "call_close" if side == "C" else "put_close"
                    row[f"{prefix}p"] = pct_change(ltp, safe_float(row.get(close_key), cp))
                bidp = safe_float(depth.get("bidP") or depth.get("bid_price"))
                askp = safe_float(depth.get("askP") or depth.get("ask_price"))
                bidq = safe_float(depth.get("bidQ") or depth.get("bid_qty"))
                askq = safe_float(depth.get("askQ") or depth.get("ask_qty"))
                if bidp:
                    row[f"{prefix}bid"] = bidp
                if askp:
                    row[f"{prefix}ask"] = askp
                if bidq:
                    row[f"{prefix}bidq"] = bidq
                if askq:
                    row[f"{prefix}askq"] = askq
                for g in ("delta", "gamma", "theta", "vega"):
                    gv = safe_float(greeks.get(g))
                    if gv:
                        row[f"{prefix}_{g}"] = gv
                volume = safe_float(row.get(f"{prefix}vol"))
                oi_now = safe_float(row.get(f"{prefix}oi"))
                ltp_now = safe_float(row.get(f"{prefix}ltp"))
            self._record_history(key, volume, oi_now, ltp_now, ts=ts)

    def _update_spot_vwap_from_future_locked(self) -> None:
        # Futures ATP is a true exchange average traded price. Convert it into
        # a spot-equivalent reference by subtracting the current futures basis.
        if self.spot and self.futures_ltp and self.futures_atp:
            basis = self.futures_ltp - self.spot
            self.vwap = self.futures_atp - basis

    # ---------- microstructure history ----------
    def _record_history(
        self, key: str, volume: float, oi: float, ltp: float, ts: Optional[float] = None
    ) -> None:
        if not key:
            return
        ts = ts or time.time()
        dq = self.history[key]
        if dq and abs(dq[-1].ts - ts) < 0.35:
            dq[-1] = Tick(ts, volume, oi, ltp)
        else:
            dq.append(Tick(ts, volume, oi, ltp))
        cutoff = ts - 20 * 60
        while dq and dq[0].ts < cutoff:
            dq.popleft()

    def _sample_at_or_before(self, key: str, seconds_ago: float) -> Optional[Tick]:
        dq = self.history.get(key)
        if not dq:
            return None
        target = time.time() - seconds_ago
        candidate = None
        for tick in reversed(dq):
            if tick.ts <= target:
                return tick
            candidate = tick
        return candidate if candidate and candidate.ts < time.time() - 5 else None

    def _session_minutes(self) -> float:
        d = now_ist()
        minutes = (d.hour * 60 + d.minute + d.second / 60) - (9 * 60 + 15)
        return clamp(minutes, 1, 375)

    def _live_metrics(self, key: Optional[str], current_volume: float, current_oi: float, current_ltp: float) -> Dict[str, float]:
        if not key:
            return {"v1": 1.0, "v3": 1.0, "v5": 1.0, "oi_vel": 0.0, "prem": 0.0}
        session_avg = max(current_volume / self._session_minutes(), 1.0)

        def spike(sec: int, mins: int) -> float:
            old = self._sample_at_or_before(key, sec)
            if not old:
                return 1.0
            delta = max(0.0, current_volume - old.volume)
            return clamp((delta / max(mins, 1)) / session_avg, 0.0, 8.0)

        old1 = self._sample_at_or_before(key, 60)
        if old1:
            dt_min = max((time.time() - old1.ts) / 60.0, 0.1)
            # current_oi is already normalised to lakhs throughout the dashboard.
            oi_vel = (current_oi - old1.oi) / dt_min
            prem = (current_ltp - old1.ltp) / dt_min
        else:
            oi_vel = 0.0
            prem = 0.0
        return {
            "v1": spike(60, 1),
            "v3": spike(180, 3),
            "v5": spike(300, 5),
            "oi_vel": clamp(oi_vel, -99, 99),
            "prem": clamp(prem, -999, 999),
        }

    # ---------- analytics ----------
    def sync_analytics(self) -> None:
        if not self.authenticated or not self.current_expiry:
            return
        today = now_ist().date().isoformat()
        max_pain = None
        pcr = None
        note_parts = []
        try:
            mp = self.get(
                f"{BASE_V2}/market/max-pain",
                params={
                    "instrument_key": self.underlying_key,
                    "expiry": self.current_expiry,
                    "date": today,
                    "bucket_interval": 60,
                },
            )
            d = mp.get("data") or {}
            max_pain = safe_float(d.get("max_pain")) or None
        except Exception as exc:
            note_parts.append(f"max-pain unavailable: {exc}")
        try:
            pr = self.get(
                f"{BASE_V2}/market/pcr",
                params={
                    "instrument_key": self.underlying_key,
                    "expiry": self.current_expiry,
                    "date": today,
                    "bucket_interval": 60,
                },
            )
            d = pr.get("data") or {}
            pcr = safe_float(d.get("pcr")) or None
        except Exception as exc:
            note_parts.append(f"PCR unavailable: {exc}")
        series: Dict[int, List[float]] = {}
        session_context: Dict[str, Any] = {}
        for interval in (3, 5, 15):
            try:
                encoded_key = quote(self.underlying_key, safe="")
                r = self.get(
                    f"{BASE_V3}/historical-candle/intraday/{encoded_key}/minutes/{interval}"
                )
                candles = ((r.get("data") or {}).get("candles") or [])
                closes = []
                for c in reversed(candles):
                    if isinstance(c, (list, tuple)) and len(c) >= 5:
                        closes.append(safe_float(c[4]))
                closes = [x for x in closes if x > 0][-40:]
                if closes:
                    series[interval] = closes
                if interval == 5 and candles:
                    asc = list(reversed(candles))
                    valid = [c for c in asc if isinstance(c, (list, tuple)) and len(c) >= 5]
                    if valid:
                        day_open = safe_float(valid[0][1])
                        day_high = max((safe_float(c[2]) for c in valid), default=0.0)
                        day_low = min((safe_float(c[3]) for c in valid if safe_float(c[3]) > 0), default=0.0)
                        last_close = safe_float(valid[-1][4])
                        opening = valid[:3]
                        or_high = max((safe_float(c[2]) for c in opening), default=0.0)
                        or_low = min((safe_float(c[3]) for c in opening if safe_float(c[3]) > 0), default=0.0)
                        session_context = {
                            "day_open": day_open or None, "day_high": day_high or None, "day_low": day_low or None,
                            "last_close": last_close or None, "opening_range_high": or_high or None, "opening_range_low": or_low or None,
                            "opening_range_minutes": 15, "candles_seen": len(valid),
                        }
            except Exception as exc:
                note_parts.append(f"{interval}m candles unavailable")
        with self.lock:
            if max_pain is not None:
                self.official_max_pain = max_pain
            if pcr is not None:
                self.official_pcr = pcr
            for k, v in series.items():
                self.price_series[k] = v
            if session_context:
                self.session_context = session_context
            self.analytics_note = "; ".join(note_parts[:3])
            self.last_analytics_sync = time.time()

    def intraday_candles(self, interval: int = 5, limit: int = 120):
        if interval not in (1, 3, 5, 15, 30):
            raise UpstoxError("Unsupported candle interval")
        encoded_key = quote(self.underlying_key, safe="")
        r = self.get(f"{BASE_V3}/historical-candle/intraday/{encoded_key}/minutes/{interval}")
        candles = ((r.get("data") or {}).get("candles") or [])
        valid = [c for c in reversed(candles) if isinstance(c, (list, tuple)) and len(c) >= 5]
        return valid[-max(20, min(int(limit), 240)):]

    def instrument_candles(self, symbol: str, interval: int = 5, limit: int = 120):
        """Intraday candles for an index code or discovered NSE equity F&O symbol.

        Uses only official Upstox instrument keys already available from the BOD universe.
        Unknown symbols are rejected rather than guessed.
        """
        if interval not in (1, 3, 5, 15, 30):
            raise UpstoxError("Unsupported candle interval")
        code = str(symbol or "").upper().strip()
        index_map = {
            "NIFTY": NIFTY_KEY_DEFAULT, "NIFTY50": NIFTY_KEY_DEFAULT,
            "BANKNIFTY": BANKNIFTY_KEY_DEFAULT, "BANK NIFTY": BANKNIFTY_KEY_DEFAULT,
            "MIDCPNIFTY": MIDCPNIFTY_KEY_DEFAULT, "NIFTY MID SELECT": MIDCPNIFTY_KEY_DEFAULT,
            "SENSEX": SENSEX_KEY_DEFAULT,
        }
        key = index_map.get(code)
        if not key:
            if not self.fno_universe_ready:
                self.discover_full_fno_universe()
            for row in self.fno_equities.values():
                if str(row.get("symbol") or "").upper() == code:
                    key = row.get("instrument_key"); break
        if not key:
            raise UpstoxError(f"Unknown/unavailable chart symbol: {code}")
        encoded_key = quote(str(key), safe="")
        r = self.get(f"{BASE_V3}/historical-candle/intraday/{encoded_key}/minutes/{interval}")
        candles = ((r.get("data") or {}).get("candles") or [])
        valid = [c for c in reversed(candles) if isinstance(c, (list, tuple)) and len(c) >= 5]
        return valid[-max(20, min(int(limit), 240)):]

    def fno_chart_symbols(self):
        if not self.fno_universe_ready:
            self.discover_full_fno_universe()
        rows = sorted((self.fno_equities or {}).values(), key=lambda x: str(x.get("symbol") or ""))
        return [str(x.get("symbol") or "").upper() for x in rows if x.get("symbol")]

    def stock_option_chain_snapshot(self, symbol: str, force: bool = False, expiry_override: Optional[str] = None) -> Dict[str, Any]:
        """Verified stock option chain with cache and optional explicit expiry.

        V71 callers keep the nearest-expiry behaviour. V72 may request one additional
        listed expiry on-demand for expiry/strike comparison. The universal scanner still
        observes every F&O underlying first and never burns full-chain calls for the whole
        market continuously.
        """
        if not self.authenticated:
            raise UpstoxError("Connect Upstox first")
        sym = str(symbol or "").upper().strip()
        if not sym:
            raise UpstoxError("Stock symbol is required")
        cache_key = f"{sym}|{expiry_override or 'AUTO'}"
        cached = self.stock_chain_cache.get(cache_key) or {}
        if cached and not force and time.time() - safe_float(cached.get("epoch")) < self.stock_chain_ttl_seconds:
            return dict(cached.get("payload") or {})
        if not self.fno_universe_ready:
            self.discover_full_fno_universe()
        row = next((x for x in self.fno_equities.values() if str(x.get("symbol") or "").upper() == sym), None)
        key = str((row or {}).get("instrument_key") or "")
        if not key:
            eq = self._search_equity(sym)
            key = str((eq or {}).get("instrument_key") or "")
        if not key:
            raise UpstoxError(f"NSE F&O underlying not found for {sym}")
        contracts = self.get(f"{BASE_V2}/option/contract", params={"instrument_key": key}).get("data") or []
        today = now_ist().date().isoformat()
        expiries = sorted({str(x.get("expiry")) for x in contracts if x.get("expiry")})
        if expiry_override and expiry_override in expiries:
            expiry = expiry_override
        else:
            expiry = next((x for x in expiries if x >= today), expiries[0] if expiries else None)
        if not expiry:
            return {"ok": False, "symbol": sym, "instrument_key": key, "expiry": None, "chain": [], "reason": "No listed option expiry returned"}
        raw = self.get(f"{BASE_V2}/option/chain", params={"instrument_key": key, "expiry_date": expiry}).get("data") or []
        out=[]; spot=safe_float(raw[0].get("underlying_spot_price")) if raw else safe_float((row or {}).get("ltp"))
        for item in raw:
            strike=safe_float(item.get("strike_price"))
            if not strike:
                continue
            c=item.get("call_options") or {}; p=item.get("put_options") or {}
            cm=c.get("market_data") or {}; pm=p.get("market_data") or {}; cg=c.get("option_greeks") or {}; pg=p.get("option_greeks") or {}
            civ=safe_float(cg.get("iv")); piv=safe_float(pg.get("iv")); civ=civ*100 if civ and civ<2 else civ; piv=piv*100 if piv and piv<2 else piv
            out.append({
                "strike": strike, "spot": spot or None,
                "ce": {"ltp":safe_float(cm.get("ltp")) or None,"oi":safe_float(cm.get("oi")) or None,"prev_oi":safe_float(cm.get("prev_oi")) or None,"volume":safe_float(cm.get("volume")) or None,"bid":safe_float(cm.get("bid_price")) or None,"ask":safe_float(cm.get("ask_price")) or None,"iv":civ or None,"delta":safe_float(cg.get("delta")) or None,"gamma":safe_float(cg.get("gamma")) or None,"theta":safe_float(cg.get("theta")) or None,"vega":safe_float(cg.get("vega")) or None,"key":c.get("instrument_key")},
                "pe": {"ltp":safe_float(pm.get("ltp")) or None,"oi":safe_float(pm.get("oi")) or None,"prev_oi":safe_float(pm.get("prev_oi")) or None,"volume":safe_float(pm.get("volume")) or None,"bid":safe_float(pm.get("bid_price")) or None,"ask":safe_float(pm.get("ask_price")) or None,"iv":piv or None,"delta":safe_float(pg.get("delta")) or None,"gamma":safe_float(pg.get("gamma")) or None,"theta":safe_float(pg.get("theta")) or None,"vega":safe_float(pg.get("vega")) or None,"key":p.get("instrument_key")},
            })
        payload={"ok":True,"symbol":sym,"instrument_key":key,"expiry":expiry,"expiries":expiries[:12],"spot":spot or None,"chain":out,"chain_rows":len(out),"source":"Upstox option chain","epoch":time.time(),"read_only":True}
        self.stock_chain_cache[cache_key]={"epoch":time.time(),"payload":payload}
        return payload

    # ---------- background lifecycle ----------
    def start_background(self) -> None:
        if self.bg_thread and self.bg_thread.is_alive():
            return
        self.stop_event.clear()

        def loop() -> None:
            while not self.stop_event.is_set():
                if not self.authenticated:
                    self.stop_event.wait(1.0)
                    continue
                # A confirmed 401 is terminal for this token. Do not create reconnect
                # storms; Render/server env must be corrected and the service restarted.
                if self.token_invalid:
                    self.stop_event.wait(30.0)
                    continue
                try:
                    if not self.token_validated_at:
                        # Read-only startup validation. fetch_expiries uses /option/contract
                        # and will mark HTTP 401 as TOKEN INVALID.
                        self.fetch_expiries(force=True)
                    if not self.current_expiry:
                        exps = self.fetch_expiries()
                        if exps:
                            self.current_expiry = exps[0]
                    if not self.chain or time.time() - self.last_rest_sync >= self.rest_sync_seconds:
                        self.sync_chain_rest()
                    if time.time() - self.last_analytics_sync >= self.analytics_sync_seconds:
                        self.sync_analytics()
                    # V60.3: complete F&O universe via official BOD + V3 quotes; baselines hydrate gradually to respect API load.
                    self.sync_full_fno_quotes()
                    self.hydrate_next_fno_baseline()
                    if self.enable_ws:
                        self._ensure_streamer_subscriptions()
                    # REST fallback becomes more frequent when WS is not connected.
                    sleep_for = 1.0 if self.streamer_connected else 3.0
                except Exception as exc:
                    with self.lock:
                        self.streamer_error = "TOKEN INVALID" if self.token_invalid else str(exc)
                        self.last_data_error = str(exc)[:300]
                    sleep_for = 30.0 if self.token_invalid else 3.0
                self.stop_event.wait(sleep_for)

        self.bg_thread = threading.Thread(target=loop, name="upstox-sync", daemon=True)
        self.bg_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            self._stop_streamer_locked()
        try:
            self.client.close()
        except Exception:
            pass

    # ---------- diagnostics ----------
    def diagnostics(self) -> Dict[str, Any]:
        """Run read-only checks against Upstox and return actionable status.

        No orders are placed and the access token is never returned to the browser.
        """
        checks: List[Dict[str, Any]] = []
        if not self.authenticated:
            return {
                "ok": False,
                "checks": [{"name": "authentication", "ok": False, "detail": "No Upstox token connected"}],
            }

        try:
            exps = self.fetch_expiries(force=True)
            checks.append({"name": "option_contracts", "ok": bool(exps), "detail": f"{len(exps)} expiries discovered"})
        except Exception as exc:
            checks.append({"name": "option_contracts", "ok": False, "detail": str(exc)})
            return {"ok": False, "checks": checks}

        try:
            self.sync_chain_rest(self.current_expiry or (exps[0] if exps else None))
            checks.append({"name": "option_chain", "ok": bool(self.chain), "detail": f"{len(self.chain)} strikes loaded"})
        except Exception as exc:
            checks.append({"name": "option_chain", "ok": False, "detail": str(exc)})

        try:
            encoded_key = quote(self.underlying_key, safe="")
            r = self.get(f"{BASE_V3}/historical-candle/intraday/{encoded_key}/minutes/5")
            candles = ((r.get("data") or {}).get("candles") or [])
            checks.append({"name": "intraday_candles", "ok": isinstance(candles, list), "detail": f"{len(candles)} candles returned"})
        except Exception as exc:
            checks.append({"name": "intraday_candles", "ok": False, "detail": str(exc)})

        # WebSocket may be silent outside market hours. Report connection state separately
        # instead of treating a closed market as a hard failure.
        checks.append({
            "name": "websocket_v3",
            "ok": bool(self.streamer_connected),
            "detail": "connected" if self.streamer_connected else (self.streamer_error or "starting / market may be closed"),
        })
        hard = [c for c in checks if c["name"] != "websocket_v3"]
        return {"ok": all(c["ok"] for c in hard), "checks": checks, "status": self.status()}

    # ---------- dashboard view ----------
    def _pitch_snapshot_locked(self) -> List[Dict[str, Any]]:
        """Legacy NIFTY weighted-breadth rows consumed by the fusion engine."""
        rows: List[Dict[str, Any]] = []
        by_query = {v.get("query"): v for v in self.heavy_futures.values()}
        for spec in INDEX_UNIVERSES["NIFTY"]["stocks"]:
            query = spec["symbol"]
            h = by_query.get(query, {})
            ltp = safe_float(h.get("ltp"))
            cp = safe_float(h.get("cp"))
            rows.append({
                "n": spec["name"],
                "symbol": query,
                "cmp": ltp,
                "f": pct_change(ltp, cp) if ltp and cp else 0.0,
                "w": safe_float(spec.get("weight")),
                "live": bool(ltp and cp),
            })
        return rows

    def _index_brain_snapshot_locked(self) -> Dict[str, Any]:
        runtime_by_symbol = {
            str(v.get("query")): {
                "ltp": safe_float(v.get("ltp")),
                "cp": safe_float(v.get("cp")),
                "instrument_key": v.get("instrument_key"),
            }
            for v in self.heavy_futures.values()
            if v.get("query")
        }
        levels = {k: dict(v) for k, v in self.index_levels.items()}
        return analyse_index_brains(runtime_by_symbol, levels)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            rows = [dict(r) for _, r in sorted(self.chain.items())]
            spot = self.spot
            expiry = self.current_expiry
            official_max_pain = self.official_max_pain
            official_pcr = self.official_pcr
            vwap = self.vwap
            price_series = {str(k): list(v) for k, v in self.price_series.items()}
            pitch = self._pitch_snapshot_locked()
            index_brain = self._index_brain_snapshot_locked()
            ws_connected = self.streamer_connected
            ws_error = self.streamer_error
            last_msg = self.last_message_ts
            iv_proxy = self.iv_proxy
            session_context = dict(self.session_context)
            sector_equities = [dict(v) for v in self.sector_equities.values()]
            fno_equities = [dict(v) for v in self.fno_equities.values()]

        if rows and spot:
            rows.sort(key=lambda r: abs(r["s"] - spot))
            # V71 can expose the full verified chain for Hero/expiry research.
            # D30 streaming remains separately limited to prioritized strikes.
            if not self.full_chain_snapshot:
                rows = rows[: max(9, self.strike_window * 2 + 5)]
            rows.sort(key=lambda r: r["s"])

        out: List[Dict[str, Any]] = []
        for r in rows:
            cm = self._live_metrics(r.get("call_key"), r["cvol"], r["coi"], r["cltp"])
            pm = self._live_metrics(r.get("put_key"), r["pvol"], r["poi"], r["pltp"])
            row = {
                "s": r["s"],
                "coi": r["coi"],
                "cchg": r["cchg"],
                "cvol": r["cvol"],
                "cltp": r["cltp"],
                "cp": r["cp"],
                "civ": r["civ"],
                "poi": r["poi"],
                "pchg": r["pchg"],
                "pvol": r["pvol"],
                "pltp": r["pltp"],
                "pp": r["pp"],
                "piv": r["piv"],
                "cbid": r["cbid"],
                "cask": r["cask"],
                "cbidq": r["cbidq"],
                "caskq": r["caskq"],
                "cdepth": r.get("cdepth") or [],
                "cv1": cm["v1"],
                "cv3": cm["v3"],
                "cv5": cm["v5"],
                "coivel": cm["oi_vel"],
                "cprem": cm["prem"],
                "pbid": r["pbid"],
                "pask": r["pask"],
                "pbidq": r["pbidq"],
                "paskq": r["paskq"],
                "pdepth": r.get("pdepth") or [],
                "pv1": pm["v1"],
                "pv3": pm["v3"],
                "pv5": pm["v5"],
                "poivel": pm["oi_vel"],
                "pprem": pm["prem"],
                # Real greeks from Upstox. UI uses these when present.
                "c_delta": r.get("c_delta", 0),
                "c_gamma": r.get("c_gamma", 0),
                "c_theta": r.get("c_theta", 0),
                "c_vega": r.get("c_vega", 0),
                "p_delta": r.get("p_delta", 0),
                "p_gamma": r.get("p_gamma", 0),
                "p_theta": r.get("p_theta", 0),
                "p_vega": r.get("p_vega", 0),
                "call_key": r.get("call_key"),
                "put_key": r.get("put_key"),
            }
            out.append(row)

        # If futures-derived VWAP isn't ready yet, use a conservative session-price
        # reference rather than inventing a true VWAP.
        if not vwap:
            series = price_series.get("5") or price_series.get("3") or []
            vwap = statistics.mean(series[-12:]) if series else spot

        status_now = self._data_status(core_present=bool(spot or out or fno_equities or sector_equities))
        return {
            "ok": True,
            "source": "upstox_websocket_v3" if status_now["data_status"] == "LIVE" else ("upstox_rest_fallback" if status_now["data_status"] == "REST" else "upstox_cached_or_unavailable"),
            "data_status": status_now["data_status"],
            "tick_age_sec": status_now["tick_age_sec"],
            "rest_age_sec": status_now["rest_age_sec"],
            "active_underlying": self.active_code,
            "active_label": UNDERLYING_CATALOG.get(self.active_code, {}).get("label", self.active_code),
            "spot": spot,
            "vwap": vwap,
            "vwap_source": f"{self.active_code} futures ATP adjusted for current basis"
            if self.futures_atp and self.futures_ltp
            else "intraday price-reference fallback",
            "expiry": expiry,
            "option_data": out,
            "price_series": price_series,
            "official_max_pain": official_max_pain,
            "official_pcr": official_pcr,
            "iv_proxy": iv_proxy,
            "session_context": session_context,
            "pitch": pitch,
            "index_brain": index_brain,
            "sector_heatmap": [
                {
                    "symbol": x.get("symbol"),
                    "sector": x.get("sector"),
                    "instrument_key": x.get("instrument_key"),
                    "future_key": x.get("future_key"),
                    "future_expiry": x.get("future_expiry"),
                    "lot_size": x.get("lot_size"),
                    "ltp": safe_float(x.get("ltp")) or None,
                    "change_pct": pct_change(safe_float(x.get("ltp")), safe_float(x.get("cp"))) if safe_float(x.get("ltp")) and safe_float(x.get("cp")) else None,
                    "live": bool(safe_float(x.get("ltp")) and safe_float(x.get("cp"))),
                    "volume": safe_float(x.get("volume")) or None,
                    "bid": safe_float(x.get("bid")) or None,
                    "ask": safe_float(x.get("ask")) or None,
                    "bid_qty": safe_float(x.get("bid_qty")) or None,
                    "ask_qty": safe_float(x.get("ask_qty")) or None,
                    "depth_levels": x.get("depth_levels") or [],
                    "high_52w": x.get("high_52w"),
                    "low_52w": x.get("low_52w"),
                    "rvol": x.get("rvol"),
                    "rvol_sessions": x.get("rvol_sessions"),
                    "prev_day_high": x.get("prev_day_high"),
                    "prev_day_low": x.get("prev_day_low"),
                    "prev_day_close": x.get("prev_day_close"),
                    "high_20d": x.get("high_20d"),
                    "low_20d": x.get("low_20d"),
                    "high_50d": x.get("high_50d"),
                    "low_50d": x.get("low_50d"),
                    "avg_volume_20d": x.get("avg_volume_20d"),
                    "futures_oi": x.get("futures_oi"),
                    "futures_prev_oi": x.get("futures_prev_oi"),
                    "futures_oi_change_pct": x.get("futures_oi_change_pct"),
                    "futures_volume": x.get("futures_volume"),
                    "atp": x.get("atp"),
                    "quote_epoch": x.get("quote_epoch"),
                    "baseline_epoch": x.get("baseline_epoch"),
                } for x in (fno_equities if fno_equities else sector_equities)
            ],
            "fno_foundation": self.fno_foundation_status(),
            "websocket_connected": ws_connected,
            "websocket_error": ws_error,
            "last_tick_epoch": last_msg,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "analytics_note": self.analytics_note,
        }

    def _data_status(self, core_present: Optional[bool] = None) -> Dict[str, Any]:
        now = time.time()
        with self.lock:
            token_present = bool(self.access_token)
            invalid = bool(self.token_invalid)
            last_tick = float(self.last_message_ts or 0.0)
            last_rest = float(self.last_rest_success_ts or 0.0)
            ws_connected = bool(self.streamer_connected)
            err = str(self.last_data_error or self.streamer_error or "")
            if core_present is None:
                core_present = bool(self.spot or self.chain or self.fno_equities or self.sector_equities)
        tick_age = max(0.0, now - last_tick) if last_tick else None
        rest_age = max(0.0, now - last_rest) if last_rest else None
        dt = now_ist()
        market_open = dt.weekday() < 5 and ((dt.hour * 60 + dt.minute) >= 9 * 60 + 15) and ((dt.hour * 60 + dt.minute) <= 15 * 60 + 30)
        live_max_age = max(8.0, min(20.0, float(self.rest_sync_seconds)))
        rest_max_age = max(20.0, float(self.rest_sync_seconds) * 2.5)

        if not token_present:
            state = "OFFLINE"
        elif invalid:
            state = "TOKEN INVALID"
        elif ws_connected and tick_age is not None and tick_age <= live_max_age:
            state = "LIVE"
        elif market_open and core_present and rest_age is not None and rest_age <= rest_max_age:
            state = "REST"
        elif core_present and ((tick_age is not None) or (rest_age is not None)):
            state = "STALE"
        elif err:
            state = "DATA ERROR"
        else:
            state = "WARMING"
        return {
            "data_status": state,
            "tick_age_sec": round(tick_age, 2) if tick_age is not None else None,
            "rest_age_sec": round(rest_age, 2) if rest_age is not None else None,
            "market_session_open": market_open,
        }

    def status(self) -> Dict[str, Any]:
        ds = self._data_status()
        with self.lock:
            return {
                "authenticated": self.authenticated,
                "data_status": ds["data_status"],
                "tick_age_sec": ds["tick_age_sec"],
                "rest_age_sec": ds["rest_age_sec"],
                "market_session_open": ds["market_session_open"],
                "configured_app": self.configured_app,
                "token_source": self.token_source,
                "server_token_configured": self.server_token_configured,
                "manual_token_allowed": not self.server_token_configured,
                "token_invalid": self.token_invalid,
                "token_invalid_reason": self.token_invalid_reason if self.token_invalid else "",
                "token_validated_at": self.token_validated_at or None,
                "underlying": self.underlying_key,
                "active_underlying": self.active_code,
                "active_label": UNDERLYING_CATALOG.get(self.active_code, {}).get("label", self.active_code),
                "available_underlyings": [{"code":k, **v} for k,v in UNDERLYING_CATALOG.items()],
                "current_expiry": self.current_expiry,
                "chain_rows": len(self.chain),
                "websocket_enabled": self.enable_ws,
                "websocket_connected": self.streamer_connected,
                "websocket_error": self.streamer_error,
                "last_tick_epoch": self.last_message_ts,
                "breadth_live_contracts": sum(
                    1 for x in self.heavy_futures.values() if x.get("ltp") and x.get("cp")
                ),
                "token_hint": "Standard OAuth tokens expire at 3:30 AM the following day; Upstox Analytics Tokens are read-only and can be valid for 1 year.",
            }
