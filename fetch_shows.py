"""Fetch upcoming Houston comedy shows from the Ticketmaster Discovery API
and save them to shows.json. The API key is read from the environment
(set as a GitHub secret), never written in this file."""
import json, os, sys, time, urllib.parse, urllib.request

import re

VENUE_NAMES = {
    "Improv Comedy Club- Houston": "Houston Improv",
    "Toyota Center - TX": "Toyota Center",
}

def fix_text(s):
    """Repair garbled accents and quotes that Ticketmaster sometimes sends."""
    def rep(m):
        run = m.group(0)
        for cand in (run, run.replace("\u00e3", "\u00c3").replace("\u00e2", "\u00c2")):
            try:
                return cand.encode("latin-1").decode("utf-8")
            except Exception:
                pass
        return run
    s = re.sub(r"[\u0080-\u00ff]+", rep, s)
    s = re.sub(r"[\u0080-\u009f\u00c2]", "", s)
    return s.replace("\u00a0", " ").strip()

KEY = os.environ.get("TICKETMASTER_API_KEY")
if not KEY:
    sys.exit("Missing TICKETMASTER_API_KEY")

BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
shows, page, total_pages = [], 0, 1

while page < total_pages and page < 5:  # up to ~1000 events
    q = urllib.parse.urlencode({
        "apikey": KEY, "city": "Houston", "stateCode": "TX",
        "classificationName": "comedy", "size": 200, "page": page,
        "sort": "date,asc",
    })
    with urllib.request.urlopen(f"{BASE}?{q}", timeout=30) as r:
        data = json.load(r)
    total_pages = data.get("page", {}).get("totalPages", 1)
    for e in data.get("_embedded", {}).get("events", []):
        start = e.get("dates", {}).get("start", {})
        if not start.get("localDate"):
            continue
        time_part = start.get("localTime", "19:00:00")
        venues = e.get("_embedded", {}).get("venues", [{}])
        imgs = sorted(e.get("images", []), key=lambda i: i.get("width", 0), reverse=True)
        img = next((i["url"] for i in imgs if i.get("ratio") == "16_9" and i.get("width", 0) <= 1100), None)
        prices = e.get("priceRanges", [])
        shows.append({
            "title": fix_text(e.get("name", "Comedy show")),
            "venue": VENUE_NAMES.get(fix_text(venues[0].get("name", "Houston")), fix_text(venues[0].get("name", "Houston"))),
            "start": f"{start['localDate']}T{time_part}",
            "price": prices[0].get("min") if prices else None,
            "url": e.get("url"),
            "img": img,
        })
    page += 1
    time.sleep(0.3)

# ----- Eventbrite: pull upcoming shows from the organizers listed in organizers.txt -----
# The token is read from the environment (GitHub secret EVENTBRITE_TOKEN). If it is missing,
# or Eventbrite refuses a request, we print a note and carry on: Ticketmaster shows still update.
EB_TOKEN = os.environ.get("EVENTBRITE_TOKEN")
def eb_get(path, params=None):
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request("https://www.eventbriteapi.com/v3" + path + q,
                                 headers={"Authorization": "Bearer " + EB_TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

if EB_TOKEN and os.path.exists("organizers.txt"):
    for line in open("organizers.txt", encoding="utf-8"):
        line = line.split("#")[0].strip()
        m = re.search(r"(\d{6,})\s*$", line.split("|")[0].strip().rstrip("/"))
        if not m:
            continue
        oid, added = m.group(1), 0
        try:
            cont = None
            for _ in range(5):
                params = {"status": "live", "order_by": "start_asc", "expand": "venue"}
                if cont:
                    params["continuation"] = cont
                data = eb_get(f"/organizers/{oid}/events/", params)
                for e in data.get("events", []):
                    if e.get("online_event") or not e.get("url"):
                        continue
                    st = (e.get("start") or {}).get("local")
                    if not st:
                        continue
                    v = e.get("venue") or {}
                    logo = e.get("logo") or {}
                    shows.append({
                        "title": fix_text((e.get("name") or {}).get("text") or "Comedy show"),
                        "venue": fix_text(v.get("name") or "Houston"),
                        "start": st[:19],
                        "price": None,
                        "url": e["url"].split("?")[0],
                        "img": logo.get("url"),
                        "extra": True,  # organizers you list are trusted, so these show automatically
                    })
                    added += 1
                pg = data.get("pagination", {})
                cont = pg.get("continuation")
                if not pg.get("has_more_items") or not cont:
                    break
            print(f"Eventbrite organizer {oid}: {added} shows")
        except Exception as ex:
            print(f"Eventbrite organizer {oid}: skipped ({ex})")
elif not EB_TOKEN:
    print("Eventbrite: no EVENTBRITE_TOKEN set, skipping")

# Remove duplicates: same venue and start time, with matching or overlapping titles.
# Keep the most reliable link: real Ticketmaster pages first, then TicketWeb, then the venue's own page.
# Short ticketmaster.com/event/Z7r... cross-listings go last because some lead to "page not found".
def norm(t):
    return re.sub(r"\W+", "", t.lower())

def rank(u):
    u = u or ""
    if "ticketmaster.com" in u:
        return 0 if "/event/3A" in u else 3
    if "ticketweb.com" in u:
        return 1
    return 2

unique = []
for sh in shows:
    n = norm(sh["title"])
    dup = None
    for u in unique:
        if u["start"] == sh["start"] and u["venue"] == sh["venue"]:
            un = norm(u["title"])
            if n == un or n in un or un in n:
                dup = u
                break
    if dup is None:
        unique.append(sh)
    elif rank(sh["url"]) < rank(dup["url"]):
        unique[unique.index(dup)] = sh
shows = unique

shows.sort(key=lambda s: s["start"])
with open("shows.json", "w") as f:
    json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "shows": shows}, f, indent=1)
# Build a browsable list of every act (soonest first) to help with picking.
import datetime
seen = {}
for sh in shows:
    seen.setdefault(sh["title"].lower(), sh)
lines = ["# ALL UPCOMING ACTS - rebuilt automatically twice a day. Do not edit this file.",
         "# To pick one, copy its line into picks.txt. Soonest shows come first."]
month = None
for sh in seen.values():
    m = datetime.datetime.strptime(sh["start"][:7], "%Y-%m").strftime("%B %Y")
    if m != month:
        lines += ["", f"# ----- {m} -----"]
        month = m
    lines.append(sh["title"])
with open("comedians.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"Saved {len(shows)} shows")
