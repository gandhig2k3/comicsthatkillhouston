"""Fetch upcoming Houston comedy shows from the Ticketmaster Discovery API
and save them to shows.json. The API key is read from the environment
(set as a GitHub secret), never written in this file."""
import json, os, sys, time, urllib.parse, urllib.request

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
            "title": e.get("name", "Comedy show"),
            "venue": venues[0].get("name", "Houston"),
            "start": f"{start['localDate']}T{time_part}",
            "price": prices[0].get("min") if prices else None,
            "url": e.get("url"),
            "img": img,
        })
    page += 1
    time.sleep(0.3)

shows.sort(key=lambda s: s["start"])
with open("shows.json", "w") as f:
    json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "shows": shows}, f, indent=1)
print(f"Saved {len(shows)} shows")
