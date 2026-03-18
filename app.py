import os
import time
import threading
import requests
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ozb-deals-changeme")
FEED_URL   = "https://www.ozbargain.com.au/deals/feed"
INTERVAL   = 15  # seconds between checks

seen_guids = set()
status = {"last_check": None, "deals_found": 0, "new_deals": 0, "running": False, "error": None, "last_titles": []}

def send_notification(title, message, url):
    try:
        r = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "moneybag,fire",
                "Click": url,
            },
            data=message.encode("utf-8"),
            timeout=10,
            timeout=10,
        )
        print(f"[ntfy] Sent notification, status={r.status_code}: {title}")
    except Exception as e:
        print(f"[ntfy] ERROR sending notification: {e}")

def fetch_deals():
    resp = requests.get(FEED_URL, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (compatible; OZBMonitor/1.0)"
    })
    resp.raise_for_status()
    
    # Parse with string splitting to avoid XML namespace issues
    text = resp.text
    items = text.split("<item>")[1:]  # split on <item>, skip first empty part
    
    deals = []
    for item in items:
        # Extract guid
        guid = ""
        if "<guid" in item:
            try:
                guid = item.split("<guid")[1].split(">")[1].split("<")[0].strip()
            except:
                pass
        
        # Extract title
        title = ""
        if "<title>" in item:
            try:
                title = item.split("<title>")[1].split("</title>")[0].strip()
                # Remove CDATA if present
                if "CDATA" in title:
                    title = title.split("[CDATA[")[1].split("]]")[0].strip()
            except:
                pass
        
        # Extract link
        link = ""
        if "<link>" in item:
            try:
                link = item.split("<link>")[1].split("</link>")[0].strip()
            except:
                pass
        elif "<guid" in item and "http" in guid:
            link = guid
            
        if not guid and link:
            guid = link
            
        if title and (guid or link):
            deals.append({"guid": guid or link, "title": title, "link": link or guid})
    
    print(f"[fetch] Got {len(deals)} deals from feed")
    return deals

def monitor_loop():
    global seen_guids
    print(f"[monitor] Starting OzBargain monitor... ntfy topic={NTFY_TOPIC}")
    status["running"] = True

    # First run — load existing deals silently
    try:
        deals = fetch_deals()
        for d in deals:
            seen_guids.add(d["guid"])
        status["deals_found"] = len(seen_guids)
        status["last_titles"] = [d["title"] for d in deals[:3]]
        print(f"[monitor] Loaded {len(seen_guids)} existing deals silently. Now watching for new ones...")
    except Exception as e:
        print(f"[monitor] Initial load ERROR: {e}")
        status["error"] = str(e)

    while True:
        time.sleep(INTERVAL)
        try:
            deals = fetch_deals()
            new_found = []

            for d in deals:
                if d["guid"] not in seen_guids:
                    seen_guids.add(d["guid"])
                    new_found.append(d)
                    print(f"[monitor] 🔥 NEW DEAL FOUND: {d['title']}")

            if new_found:
                status["new_deals"] += len(new_found)
                for d in new_found:
                    send_notification(
                        title="New OzBargain Deal!",
                        message=d["title"],
                        url=d["link"],
                    )

            status["deals_found"] = len(seen_guids)
            status["last_check"] = datetime.utcnow().isoformat() + "Z"
            status["last_titles"] = [d["title"] for d in deals[:3]]
            status["error"] = None
            print(f"[monitor] Check done. Total seen={len(seen_guids)}, new this check={len(new_found)}")

        except Exception as e:
            status["error"] = str(e)
            print(f"[monitor] ERROR during check: {e}")

@app.route("/")
def index():
    titles_html = "".join(f"<li>{t}</li>" for t in status["last_titles"])
    return f"""
    <html><body style="font-family:monospace;background:#111;color:#eee;padding:30px">
    <h2 style="color:#f47920">🟠 OzBargain Monitor</h2>
    <p>Status: <b style="color:{'#22c55e' if status['running'] else '#ef4444'}">{'RUNNING ✅' if status['running'] else 'STOPPED'}</b></p>
    <p>ntfy topic: <b>{NTFY_TOPIC}</b></p>
    <p>Last check: {status['last_check'] or 'never'}</p>
    <p>Total deals seen: {status['deals_found']}</p>
    <p>New deals notified this session: <b style="color:#22c55e">{status['new_deals']}</b></p>
    {f'<p style="color:#ef4444">Last error: {status["error"]}</p>' if status["error"] else ''}
    <p>Latest deals in feed:</p><ul>{''.join(f'<li>{t}</li>' for t in status['last_titles'])}</ul>
    <p style="color:#555">Checking every {INTERVAL} seconds.</p>
    </body></html>
    """

@app.route("/health")
def health():
    return jsonify({"status": "ok", "running": status["running"], "deals_seen": status["deals_found"]})

def start_monitor():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

start_monitor()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
