from datetime import timezone, timedelta

# Strefa czasowa (dla timestampów). Jeśli chcesz auto-DST, odkomentuj pytz.
TZ = timezone(timedelta(hours=1))
# import pytz
# TZ = pytz.timezone("Europe/Warsaw")

# === Konfiguracja ntfy ===
NTFY_TOPIC_URL = "https://ntfy.sh/eurpln-TENlhu8Ok9zTwUK6ArL"
NTFY_TITLE = "EUR/PLN Alert"

# === Polling i logika alertów ===
POLL_INTERVAL_SECONDS = 5  # jak często sprawdzać

# Minimalna zmiana kursu EUR/PLN (PLN) do wysłania alertu
ALERT_THRESHOLD = 0.0001

TEST_ALWAYS_NOTIFY = True # jeśli chcesz zawsze wysyłać notyfikację przy teście
TEST_RESPECT_SCHEDULE = True  # jeśli chcesz testować o dowolnej porze