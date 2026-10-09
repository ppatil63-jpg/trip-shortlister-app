"""Trip Shortlister engine: destination dataset, weighted scoring, review helpers.

Pure Python, no MCP dependency — the scoring/review logic can be tested
standalone. server.py wires these functions up as MCP tools for ChatGPT.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

DEFAULT_WEIGHTS = {
    "interest": 30,   # matches the traveler's style picks
    "budget": 25,     # realistic on their budget
    "reviews": 20,    # aggregate sentiment (Google / Reddit / Instagram)
    "logistics": 15,  # getting there & around
    "safety": 10,     # general comfort, esp. solo travelers
}

# daily_cost_usd = rough mid-range daily spend per person (2026 estimates,
# excluding flights). Treat as estimates, not quotes.
DESTINATIONS = [
    {"id": "kyoto", "name": "Kyoto, Japan", "country": "Japan", "region": "Asia",
     "daily_cost_usd": 95, "styles": ["culture", "food", "photography"],
     "safety": 9, "logistics": 7, "best_months": "Mar-May, Oct-Nov",
     "blurb": "Temples, gardens, and some of the best food streets in Japan."},
    {"id": "bangkok", "name": "Bangkok, Thailand", "country": "Thailand", "region": "Asia",
     "daily_cost_usd": 55, "styles": ["food", "nightlife", "culture"],
     "safety": 7, "logistics": 8, "best_months": "Nov-Feb",
     "blurb": "Street food capital with easy day trips and big-city energy."},
    {"id": "bali", "name": "Bali, Indonesia", "country": "Indonesia", "region": "Asia",
     "daily_cost_usd": 50, "styles": ["beaches", "chill", "nature", "photography"],
     "safety": 7, "logistics": 7, "best_months": "Apr-Oct",
     "blurb": "Beaches, rice terraces, and cheap private villas."},
    {"id": "hoian", "name": "Hoi An, Vietnam", "country": "Vietnam", "region": "Asia",
     "daily_cost_usd": 45, "styles": ["food", "culture", "beaches", "photography"],
     "safety": 8, "logistics": 6, "best_months": "Feb-Apr",
     "blurb": "Lantern-lit old town, tailors, and beach a short ride away."},
    {"id": "goa", "name": "Goa, India", "country": "India", "region": "Asia",
     "daily_cost_usd": 40, "styles": ["beaches", "nightlife", "food", "chill"],
     "safety": 7, "logistics": 9, "best_months": "Nov-Feb",
     "blurb": "Easiest logistics for an Indian passport; beach + party scene."},
    {"id": "paris", "name": "Paris, France", "country": "France", "region": "Europe",
     "daily_cost_usd": 140, "styles": ["culture", "food", "photography"],
     "safety": 7, "logistics": 8, "best_months": "Apr-Jun, Sep-Oct",
     "blurb": "Museums, food, and walkable neighborhoods. Pricey but dense."},
    {"id": "rome", "name": "Rome, Italy", "country": "Italy", "region": "Europe",
     "daily_cost_usd": 120, "styles": ["culture", "food", "photography"],
     "safety": 7, "logistics": 8, "best_months": "Apr-Jun, Sep-Oct",
     "blurb": "Ancient history stacked next to great cheap eats."},
    {"id": "barcelona", "name": "Barcelona, Spain", "country": "Spain", "region": "Europe",
     "daily_cost_usd": 110, "styles": ["culture", "beaches", "nightlife", "food"],
     "safety": 7, "logistics": 8, "best_months": "May-Jun, Sep-Oct",
     "blurb": "Beach + city + late-night food culture in one trip."},
    {"id": "interlaken", "name": "Interlaken, Switzerland", "country": "Switzerland", "region": "Europe",
     "daily_cost_usd": 160, "styles": ["adventure", "nature", "photography"],
     "safety": 9, "logistics": 7, "best_months": "Jun-Sep",
     "blurb": "Alps adventure base: hiking, paragliding, lake swims. Expensive."},
    {"id": "nyc", "name": "New York City, USA", "country": "USA", "region": "North America",
     "daily_cost_usd": 150, "styles": ["culture", "food", "nightlife", "photography"],
     "safety": 6, "logistics": 9, "best_months": "Apr-Jun, Sep-Nov",
     "blurb": "No visa needed on F-1; endless food and neighborhoods."},
    {"id": "banff", "name": "Banff, Canada", "country": "Canada", "region": "North America",
     "daily_cost_usd": 130, "styles": ["nature", "adventure", "photography"],
     "safety": 9, "logistics": 6, "best_months": "Jun-Sep",
     "blurb": "Turquoise lakes and mountain hikes. Needs a Canada visa."},
    {"id": "cdmx", "name": "Mexico City, Mexico", "country": "Mexico", "region": "North America",
     "daily_cost_usd": 65, "styles": ["food", "culture", "photography"],
     "safety": 6, "logistics": 7, "best_months": "Mar-May",
     "blurb": "World-class food city at a fraction of US/Europe prices."},
]


def normalize_styles(styles: list[str]) -> set[str]:
    """'beaches/chill' -> {'beaches', 'chill'}; lowercase everything."""
    out: set[str] = set()
    for s in styles:
        for part in re.split(r"[/,]", s.lower()):
            part = part.strip()
            if part:
                out.add(part)
    return out


def _interest_fit(user_styles: set[str], place_styles: list[str]) -> float:
    if not user_styles:
        return 5.0
    overlap = len(user_styles & set(place_styles))
    return round(max(1.0, min(10.0, overlap / len(user_styles) * 10)), 1)


def _budget_fit(per_day_budget: float, place_cost: float) -> float:
    if per_day_budget <= 0:
        return 5.0
    ratio = per_day_budget / place_cost
    # ratio 1.5x+ -> 10; 0.6x or less -> 1; linear between
    score = 1 + 9 * (ratio - 0.6) / (1.5 - 0.6)
    return round(max(1.0, min(10.0, score)), 1)


def shortlist(region: str, budget_per_person_usd: float, trip_days: int,
               styles: list[str], weights: dict | None = None) -> dict:
    """Score destinations on the weighted matrix. Returns ranked results."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)
    total_w = sum(w.values()) or 1

    user_styles = normalize_styles(styles)
    per_day = budget_per_person_usd / max(trip_days, 1)
    region = (region or "anywhere").strip().lower()

    results = []
    for d in DESTINATIONS:
        if region not in ("anywhere", "any", "") and d["region"].lower() != region:
            continue
        scores = {
            "interest": _interest_fit(user_styles, d["styles"]),
            "budget": _budget_fit(per_day, d["daily_cost_usd"]),
            # Reviews start neutral: real review data comes from the
            # reddit_takes / google_reviews tools. Never invent a score.
            "reviews": 7.0,
            "logistics": float(d["logistics"]),
            "safety": float(d["safety"]),
        }
        total = round(sum(scores[k] * w[k] for k in w) / total_w, 1)
        results.append({
            "destination": d["name"],
            "country": d["country"],
            "scores": scores,
            "weighted_total": total,
            "est_daily_cost_usd": d["daily_cost_usd"],
            "best_months": d["best_months"],
            "blurb": d["blurb"],
        })
    results.sort(key=lambda r: r["weighted_total"], reverse=True)
    return {
        "results": results,
        "weights": w,
        "per_day_budget_usd": round(per_day, 2),
        "reviews_note": "Review scores are neutral placeholders until the "
                        "reddit_takes / google_reviews tools return real data. "
                        "The model should call those tools before final ranking.",
    }


def format_matrix(shortlist_result: dict) -> str:
    """Render the ranked matrix as a Markdown table."""
    lines = ["| # | Destination | Interest | Budget | Reviews | Logistics | Safety | Total |",
             "|---|-------------|----------|--------|---------|-----------|--------|-------|"]
    for i, r in enumerate(shortlist_result["results"], 1):
        s = r["scores"]
        lines.append(
            f"| {i} | {r['destination']} | {s['interest']} | {s['budget']} | "
            f"{s['reviews']} | {s['logistics']} | {s['safety']} | **{r['weighted_total']}** |"
        )
    return "\n".join(lines)


def _reddit_token() -> str | None:
    """App-only OAuth token. Needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.

    Free: reddit.com → user settings → Privacy & Security → App
    preferences → "create another app" (script type). No review needed.
    """
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        return None
    import base64
    creds = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=urllib.parse.urlencode(
            {"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {creds}",
                 "User-Agent": "trip-shortlister/0.1 (personal project)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("access_token")
    except Exception:  # noqa: BLE001
        return None


def fetch_reddit_takes(destination: str, limit: int = 5) -> dict:
    """Real Reddit search. Prefers free OAuth (env creds); falls back to the
    anonymous endpoint, which Reddit increasingly blocks (403).

    Returns top honest-take threads. Failures return an honest error
    instead of fake data.
    """
    query = f"{destination} travel worth it tips"
    params = urllib.parse.urlencode({
        "q": query, "sort": "top", "t": "year",
        "limit": min(max(limit, 1), 10) + 5, "type": "link",
    })
    headers = {"User-Agent": "trip-shortlister/0.1 (personal project)"}

    token = _reddit_token()
    if token:
        url, headers = (f"https://oauth.reddit.com/search?{params}",
                        {**headers, "Authorization": f"Bearer {token}"})
        auth_note = "oauth"
    else:
        url = f"https://www.reddit.com/search.json?{params}"
        auth_note = "anonymous"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 - surface honestly
        hint = "" if token else (" Reddit blocks anonymous API access; set "
                                 "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (free) "
                                 "for the OAuth path.")
        return {"destination": destination,
                "error": f"Reddit request failed ({auth_note}): {e}.{hint}"}

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        if p.get("over_18") or p.get("stickied"):
            continue
        posts.append({
            "title": p.get("title", ""),
            "subreddit": p.get("subreddit_name_prefixed", ""),
            "score": p.get("score", 0),
            "comments": p.get("num_comments", 0),
            "url": "https://www.reddit.com" + p.get("permalink", ""),
            "snippet": (p.get("selftext") or "")[:280],
        })
        if len(posts) >= limit:
            break
    if not posts:
        return {"destination": destination,
                "error": "No useful threads found — try a broader search."}
    return {"destination": destination, "posts": posts}


def instagram_links(destination: str) -> dict:
    """Instagram has no public API for reviews/location data.

    Honest fallback: hashtag deep link (real, stable URL pattern) plus
    guidance to check the Places tab in the Instagram app.
    """
    city = destination.split(",")[0].strip().lower()
    tag = re.sub(r"[^a-z0-9]", "", city)
    return {
        "destination": destination,
        "hashtag_url": f"https://www.instagram.com/explore/tags/{tag}/",
        "note": ("Instagram offers no public reviews API, so this tool can't pull "
                 "ratings. Open the hashtag's Recent tab for current vibe/crowds, "
                 "or search the place name in the Instagram app under Places for "
                 "geo-tagged posts."),
    }


def google_reviews(destination: str) -> dict:
    """Google reviews via the Places API (New). Requires a paid API key.

    Set GOOGLE_PLACES_API_KEY. Without it, returns setup instructions —
    never fake review data.
    """
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        return {
            "destination": destination,
            "configured": False,
            "message": ("Google Places API key not set. Set the "
                        "GOOGLE_PLACES_API_KEY environment variable (Google Cloud "
                        "console → enable Places API (New) → create API key; "
                        "it's usage-based paid). Then this tool returns live "
                        "ratings + review snippets."),
        }
    try:
        body = json.dumps({"textQuery": f"{destination} tourist attraction"}).encode()
        req = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchText",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": ("places.displayName,places.rating,"
                                     "places.userRatingCount,places.reviews"),
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        places = data.get("places", [])
        if not places:
            return {"destination": destination, "configured": True,
                    "error": "No place found for that query."}
        p = places[0]
        reviews = [{
            "author": r.get("authorAttribution", {}).get("displayName", "Google user"),
            "rating": r.get("rating"),
            "text": (r.get("text", {}).get("text", "") or "")[:300],
            "when": r.get("relativePublishTimeDescription", ""),
        } for r in p.get("reviews", [])[:5]]
        return {
            "destination": destination,
            "configured": True,
            "place": p.get("displayName", {}).get("text", destination),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount"),
            "reviews": reviews,
        }
    except Exception as e:  # noqa: BLE001
        return {"destination": destination, "configured": True,
                "error": f"Places API request failed: {e}"}
