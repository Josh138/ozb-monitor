import os
import time
import threading
import requests
import xml.etree.ElementTree as ET
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

# -------------------------------------------------------
# CONFIGURATION — change NTFY_TOPIC to your chosen topic
# -------------------------------------------------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ozb-deals-changeme")
FEED_URL   = "https://www.ozbargain.com.au/deals/feed"
INTERVAL   = 10  # seconds between checks

seen_guids = set()
status = {"last_check": None, "deals_found": 0, "new_deals": 0, "running": False, "error": None}

# -------------------------------------------------------

def send_notification(title, message, url):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "moneybag,fire",
                "Click": url,
            },
            data=message.encode("utf-8"),
            timeout=10,
        )
        print(f"[ntfy] Sent: {title}")
    except Exception as e:
        print(f"[ntfy] Failed to send notification: {e}")


def fetch_deals():
    try:
        resp = requests.get(FEED_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        return items
    except Exception as e:
        raise Exception(f"Feed fetch failed: {e}")


def monitor_loop():
    global seen_guids
    print("[monitor] Starting OzBargain monitor...")
    status["running"] = True

    # On first run, load existing deals silently (don't notify for old deals)
    try:
        items = fetch_deals()
        for item in items:
            guid = item.findtext("guid") or item.findtext("link") or ""
            seen_guids.add(guid.strip())
        status["deals_found"] = len(seen_guids)
        print(f"[monitor] Loaded {len(seen_guids)} existing deals — watching for new ones...")
    except Exception as e:
        print(f"[monitor] Initial load failed: {e}")

    while True:
        try:
            items = fetch_deals()
            new_found = []

            for item in items:
                guid  = (item.findtext("guid")  or item.findtext("link") or "").strip()
                title = (item.findtext("title") or "New Deal").strip()
                link  = (item.findtext("link")  or "https://www.ozbargain.com.au").strip()

                if guid and guid not in seen_guids:
                    seen_guids.add(guid)
                    new_found.append({"title": title, "link": link})

            if new_found:
                status["new_deals"] += len(new_found)
                for deal in new_found:
                    print(f"[monitor] NEW DEAL: {deal['title']}")
                    send_notification(
                        title=f"🔥 New OzBargain Deal!",
                        message=deal["title"],
                        url=deal["link"],
                    )

            status["deals_found"] = len(seen_guids)
            status["last_check"] = datetime.utcnow().isoformat() + "Z"
            status["error"] = None

        except Exception as e:
            status["error"] = str(e)
            print(f"[monitor] Error: {e}")

        time.sleep(INTERVAL)


# -------------------------------------------------------
# Flask routes — keeps Render alive + lets you check status
# -------------------------------------------------------

@app.route("/")
def index():
    return f"""
    <html><body style="font-family:monospace;background:#111;color:#eee;padding:30px">
    <h2 style="color:#f47920">🟠 OzBargain Monitor</h2>
    <p>Status: <b style="color:{'#22c55e' if status['running'] else '#ef4444'}">{'RUNNING' if status['running'] else 'STOPPED'}</b></p>
    <p>ntfy topic: <b>{NTFY_TOPIC}</b></p>
    <p>Last check: {status['last_check'] or 'never'}</p>
    <p>Total deals seen: {status['deals_found']}</p>
    <p>New deals notified: {status['new_deals']}</p>
    {f'<p style="color:#ef4444">Last error: {status["error"]}</p>' if status["error"] else ''}
    <br><p style="color:#555">Checking every {INTERVAL} seconds.</p>
    </body></html>
    """

@app.route("/health")
def health():
    return jsonify({"status": "ok", "running": status["running"]})


# -------------------------------------------------------
# Start monitor thread when app boots
# -------------------------------------------------------

def start_monitor():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

start_monitor()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
