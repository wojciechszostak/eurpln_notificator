import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from flask import Flask, render_template, jsonify
import requests

from scraper import get_eurpln_snapshot
from config import (
    TZ,
    NTFY_TOPIC_URL,
    NTFY_TITLE,
    POLL_INTERVAL_SECONDS,
    ALERT_THRESHOLD,
    TEST_ALWAYS_NOTIFY,
    TEST_RESPECT_SCHEDULE,
)

app = Flask(__name__)

# --- Stan aplikacji ---
_state = {
    "armed": False,          # histereza: True po wysłaniu alertu, reset gdy spadnie poniżej progu
    "last_alert_iso": None,  # ISO timestamp ostatniego alertu
    "last_snapshot": None,   # ostatni snapshot (dla /api/data, /health)
}

# --- Utils ---
def _to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    t = s.replace("\xa0", "").replace(" ", "").strip()
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None

def _can_encode_latin1(s: str) -> bool:
    try:
        s.encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False

def _latin1_sanitize(s: str) -> str:
    return s.encode("latin-1", "ignore").decode("latin-1")

def _send_ntfy_message(text: str, title: Optional[str] = None) -> bool:
    """
    Bezpieczna wysyłka do ntfy:
    - body w UTF-8 (obsłuży emoji/PL znaki),
    - nagłówek Title tylko jeśli mieści się w latin-1; inaczej przenosimy tytuł do body.
    """
    headers = {}
    body = text
    if title:
        if _can_encode_latin1(title):
            headers["Title"] = title
        else:
            safe = _latin1_sanitize(title)
            if safe.strip():
                headers["Title"] = safe
            else:
                body = f"{title}\n\n{body}"

    try:
        resp = requests.post(
            NTFY_TOPIC_URL,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        ok = 200 <= resp.status_code < 300
        if ok:
            print(f"[NTFY] OK {resp.status_code}", file=sys.stderr)
        else:
            print(f"[NTFY] HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        return ok
    except Exception as e:
        print(f"[NTFY][EXC] {e}", file=sys.stderr)
        return False

def _build_alert_message(snapshot: dict, delta: Optional[float] = None) -> str:
    line_delta = ""
    if delta is not None:
        znak = "▲" if delta > 0 else "▼"
        line_delta = f"Zmiana vs otwarcie: {delta:+.4f} PLN {znak}\n"

    msg = (
        f"🚨 ALERT EUR/PLN\n"
        f"---\n"
        f"Kurs: {snapshot.get('kurs') or '—'}  "
        f"{snapshot.get('zmiana') or ''} {snapshot.get('zmiana_pct') or ''}\n"
        f"Otwarcie: {snapshot.get('kurs_otwarcia') or '—'}\n"
        f"{line_delta}"
        f"{snapshot.get('timestamp') or ''}"
    )
    return msg

def _in_schedule(now: datetime) -> bool:
    # pn–pt, 9–17
    return (0 <= now.weekday() <= 4) and (9 <= now.hour < 17)

# --- Worker pollingu ---
def _polling_worker():
    """
    Co POLL_INTERVAL_SECONDS:
     - w trybie TEST_ALWAYS_NOTIFY: wysyła snapshot co cykl (zależnie od TEST_RESPECT_SCHEDULE),
     - w trybie normalnym: wysyła przy przekroczeniu progu |kurs - otwarcie| >= ALERT_THRESHOLD
       tylko pn–pt 9–17, z histerezą (cross).
    """
    print("[POLL] worker start", file=sys.stderr)
    while True:
        try:
            msg = None  # ważne: inicjalizacja, by uniknąć błędu "msg not associated with a value"

            print("[POLL] start cycle", file=sys.stderr)
            snap = get_eurpln_snapshot()
            _state["last_snapshot"] = snap
            print(
                f"[POLL] snap: kurs={snap.get('kurs')} open={snap.get('kurs_otwarcia')} "
                f"zm={snap.get('zmiana')} zm%={snap.get('zmiana_pct')}",
                file=sys.stderr,
            )

            now = datetime.now(tz=TZ)

            # --- Tryb testowy ---
            if TEST_ALWAYS_NOTIFY:
                if not TEST_RESPECT_SCHEDULE or _in_schedule(now):
                    msg = "TEST ALERT: snapshot\n" + _build_alert_message(snap)
                    print("[POLL] TEST: sending ntfy…", file=sys.stderr)
                    _send_ntfy_message(msg, title=NTFY_TITLE)
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # --- Tryb normalny ---
            kurs = _to_float(snap.get("kurs"))
            open_ = _to_float(snap.get("kurs_otwarcia"))
            if kurs is None or open_ is None:
                print("[POLL] parse None -> skip", file=sys.stderr)
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            delta = kurs - open_
            in_sched = _in_schedule(now)
            if not in_sched:
                print("[POLL] in_schedule=False", file=sys.stderr)

            crossed = abs(delta) >= ALERT_THRESHOLD
            if crossed and not _state["armed"] and in_sched:
                print("[POLL] sending ntfy (cross)…", file=sys.stderr)
                msg = _build_alert_message(snap, delta)
                ok = _send_ntfy_message(msg, title=NTFY_TITLE)
                if ok:
                    _state["armed"] = True
                    _state["last_alert_iso"] = snap.get("timestamp")
            elif not crossed and _state["armed"]:
                print("[POLL] reset arm (below threshold)", file=sys.stderr)
                _state["armed"] = False

        except Exception as e:
            print(f"[POLL][EXC] {e}", file=sys.stderr)

        time.sleep(POLL_INTERVAL_SECONDS)

def _start_background_polling_once():
    should_start = True
    if app.debug:
        should_start = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if should_start:
        t = threading.Thread(target=_polling_worker, daemon=True, name="eurpln-poll")
        t.start()
        print("[POLL] thread started", file=sys.stderr)

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.get("/api/data")
def api_data():
    try:
        snap = _state.get("last_snapshot") or get_eurpln_snapshot()
        _state["last_snapshot"] = snap
        return jsonify(snap)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/notify")
def notify():
    try:
        snap = get_eurpln_snapshot()
        ok = _send_ntfy_message(_build_alert_message(snap), title=NTFY_TITLE)
        return jsonify({"ok": bool(ok)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# --- Diagnostyka ---
@app.get("/ntfy/test")
def ntfy_test_get():
    ok = _send_ntfy_message("TEST z /ntfy/test (GET)", title=NTFY_TITLE)
    return jsonify({"ok": ok})

@app.post("/ntfy/test")
def ntfy_test_post():
    ok = _send_ntfy_message("TEST z /ntfy/test (POST)", title=NTFY_TITLE)
    return jsonify({"ok": ok})

@app.get("/health")
def health():
    return jsonify({
        "thread_active": True,
        "last_snapshot": _state.get("last_snapshot"),
        "last_alert_iso": _state.get("last_alert_iso"),
        "armed": _state.get("armed"),
        "settings": {
            "ALERT_THRESHOLD": ALERT_THRESHOLD,
            "TEST_ALWAYS_NOTIFY": TEST_ALWAYS_NOTIFY,
            "TEST_RESPECT_SCHEDULE": TEST_RESPECT_SCHEDULE,
            "POLL_INTERVAL_SECONDS": POLL_INTERVAL_SECONDS,
        }
    })

# start worker
_start_background_polling_once()

if __name__ == "__main__":
    # unikamy podwójnego wątku (reloader)
    app.run(debug=True, use_reloader=False)
