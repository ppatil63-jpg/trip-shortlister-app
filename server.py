"""Trip Shortlister MCP server — the backend of the ChatGPT app.

Built for the MCP Python SDK 2.x (MCPServer).

Run locally:  pip install -r requirements.txt
              python server.py
Then point ChatGPT's developer mode at http://localhost:8000/mcp
(see README.md). For hosting, use the included Dockerfile / render.yaml.

ChatGPT Apps SDK notes:
- Each @mcp.tool() becomes callable by the model when the user asks a
  trip question; the model picks tools based on the tool descriptions.
- The scorecard widget is attached via meta={"openai/outputTemplate": ...}
  on the shortlist_destinations tool, so ChatGPT renders it inline in
  the chat. The widget degrades gracefully — text output always works.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from engine import (
    fetch_reddit_takes,
    format_matrix,
    google_reviews,
    instagram_links,
    shortlist,
)

mcp = MCPServer(
    "trip-shortlister",
    instructions=(
        "Trip planning tools. When the user asks where to go on a trip, "
        "first collect the basics if missing (region or 'surprise me', dates "
        "or trip length, budget per person excluding flights, travel style, "
        "who's going, pace), then call shortlist_destinations. Before giving "
        "final recommendations, call reddit_takes and google_reviews for the "
        "top candidates and fold the findings into the ranking. Use "
        "instagram_links to point the user at live Instagram content — never "
        "claim Instagram ratings exist. Never invent review scores or prices."
    ),
)

WIDGET_PATH = os.path.join(os.path.dirname(__file__), "web", "scorecard.html")


@mcp.tool(meta={"openai/outputTemplate": "ui://widget/scorecard.html"})
def shortlist_destinations(
    region: str,
    budget_per_person_usd: float,
    trip_days: int,
    styles: list[str],
    travelers: str = "solo",
    pace: str = "balanced",
    weights: dict | None = None,
) -> dict:
    """Score destinations on a weighted matrix for a trip.

    Args:
        region: 'Asia', 'Europe', 'North America', or 'anywhere'.
        budget_per_person_usd: total budget per person, excluding flights.
        trip_days: length of the trip in days.
        styles: travel styles, e.g. ['food', 'beaches', 'culture'].
        travelers: 'solo', 'partner', 'friends', or 'family'.
        pace: 'packed' or 'balanced'.
        weights: optional override, e.g. {'budget': 40, 'interest': 30,
            'reviews': 10, 'logistics': 10, 'safety': 10}.
    """
    result = shortlist(region, budget_per_person_usd, trip_days, styles, weights)
    return {
        "summary": format_matrix(result),
        "results": result["results"],
        "weights": result["weights"],
        "per_day_budget_usd": result["per_day_budget_usd"],
        "travelers": travelers,
        "pace": pace,
        "reviews_note": result["reviews_note"],
    }


@mcp.tool()
def reddit_takes(destination: str, limit: int = 5) -> dict:
    """Get honest traveler takes on a destination from Reddit threads.

    Needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars (free).
    Args:
        destination: e.g. 'Kyoto, Japan'.
        limit: max threads to return (1-10).
    """
    return fetch_reddit_takes(destination, limit)


@mcp.tool()
def google_reviews(destination: str) -> dict:
    """Get live Google rating + review snippets for a destination.

    Requires the GOOGLE_PLACES_API_KEY environment variable (paid,
    usage-based). Without it, returns setup instructions — never fake data.

    Args:
        destination: e.g. 'Kyoto, Japan'.
    """
    return google_reviews(destination)


@mcp.tool()
def instagram_links(destination: str) -> dict:
    """Get Instagram deep links for a destination's vibe/photos.

    Instagram has no public reviews API, so this returns hashtag links
    plus guidance — never invented ratings.

    Args:
        destination: e.g. 'Kyoto, Japan'.
    """
    return instagram_links(destination)


@mcp.resource("ui://widget/scorecard.html", mime_type="text/html+skybridge")
def scorecard_widget() -> str:
    """Scorecard widget rendered inline in ChatGPT."""
    with open(WIDGET_PATH, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    # PORT is set by hosts like Render; default 8000 for local runs.
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
