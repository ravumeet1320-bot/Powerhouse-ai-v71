import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import upstox_service as us

OLD_TOKEN = os.environ.get("UPSTOX_ACCESS_TOKEN")
OLD_WS = os.environ.get("UPSTOX_ENABLE_WEBSOCKET")
try:
    os.environ["UPSTOX_ACCESS_TOKEN"] = "server-analytics-token-" + "x" * 32
    os.environ["UPSTOX_ENABLE_WEBSOCKET"] = "false"
    with tempfile.TemporaryDirectory() as td:
        svc = us.UpstoxService(token_file=Path(td) / "legacy_token.json")
        assert svc.server_token_configured is True
        assert svc.token_source == "env"
        assert svc.status()["manual_token_allowed"] is False
        assert svc.status()["data_status"] == "WARMING"

        try:
            svc.set_manual_token("manual-" + "y" * 40)
            raise AssertionError("manual token unexpectedly overrode server token")
        except us.UpstoxError as exc:
            assert "override is disabled" in str(exc)

        bad = httpx.Response(401, json={"status": "error", "errors": [{"errorCode": "UDAPI100050", "message": "Invalid token used to access API"}]})
        try:
            svc._json_or_error(bad, "test")
            raise AssertionError("401 did not raise")
        except us.UpstoxAuthError as exc:
            assert "TOKEN INVALID" in str(exc)
        st = svc.status()
        assert st["token_invalid"] is True
        assert st["data_status"] == "TOKEN INVALID"
        assert st["websocket_connected"] is False

        # Browser/local disconnect may clear stale local files, but cannot remove the env token.
        svc.start_background = lambda: None
        svc.clear_token()
        st = svc.status()
        assert st["authenticated"] is True
        assert st["token_source"] == "env"
        assert st["server_token_configured"] is True
        assert st["token_invalid"] is False

        # LIVE requires an actual fresh tick, not merely a connected websocket transport.
        svc.spot = 25000.0
        svc.streamer_connected = True
        svc.last_message_ts = 0.0
        assert svc._data_status(core_present=True)["data_status"] != "LIVE"
        svc.last_message_ts = time.time()
        assert svc._data_status(core_present=True)["data_status"] == "LIVE"

        # REST is a truthful fallback only during market hours with a recent successful REST call.
        original_now_ist = us.now_ist
        us.now_ist = lambda: datetime(2026, 9, 14, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        svc.streamer_connected = False
        svc.last_message_ts = 0.0
        svc.last_rest_success_ts = time.time()
        assert svc._data_status(core_present=True)["data_status"] == "REST"

        # Outside market hours cached data is STALE, never LIVE.
        us.now_ist = lambda: datetime(2026, 9, 13, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert svc._data_status(core_present=True)["data_status"] == "STALE"
        us.now_ist = original_now_ist
        svc.stop()

    print("TEST_V72_2_AUTH_STATUS PASS — server token authority + truthful feed states + 401 lockout")
finally:
    if OLD_TOKEN is None:
        os.environ.pop("UPSTOX_ACCESS_TOKEN", None)
    else:
        os.environ["UPSTOX_ACCESS_TOKEN"] = OLD_TOKEN
    if OLD_WS is None:
        os.environ.pop("UPSTOX_ENABLE_WEBSOCKET", None)
    else:
        os.environ["UPSTOX_ENABLE_WEBSOCKET"] = OLD_WS
