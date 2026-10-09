# Trip Shortlister — ChatGPT app

A ChatGPT app (Apps SDK) that plans trips the way you asked: it asks a few
basic questions, shortlists destinations on a **weighted scoring matrix**,
and grounds recommendations in **real reviews from Google, Reddit, and
Instagram** — then renders an interactive scorecard right inside the chat.

## How it works

```
User: "plan a 5-day food trip under $800"
  → ChatGPT calls shortlist_destinations (the matrix)
  → calls reddit_takes + google_reviews for the top candidates
  → renders the scorecard widget inline + explains the ranking
```

## What's real vs. stubbed (honest)

| Piece | Status |
|---|---|
| Quiz → weighted matrix (interest/budget/reviews/logistics/safety) | ✅ Real, in `engine.py` |
| Reddit honest-takes | ⚠️ Needs free `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (reddit.com → settings → app preferences, "script" app — no review). Anonymous access is blocked by Reddit |
| Google rating + review snippets | ⚠️ Needs `GOOGLE_PLACES_API_KEY` (**paid**, usage-based — Google Cloud → enable Places API (New)) |
| Instagram | ⚠️ No public reviews API exists — the app returns hashtag deep links + guidance instead of fake ratings |

## Run it locally

```bash
cd trip-shortlister-app
pip install -r requirements.txt
python server.py        # serves MCP on http://localhost:8000/mcp
```

Test the engine without the server:

```bash
python -c "
from engine import shortlist, format_matrix, fetch_reddit_takes
r = shortlist('Asia', 800, 5, ['food', 'culture'])
print(format_matrix(r))
print(fetch_reddit_takes('Hoi An, Vietnam', 3)['posts'][0]['title'])
"
```

## Connect it to ChatGPT (developer mode — free, no Plus needed)

1. Deploy the server somewhere HTTPS (Render / Railway / Fly.io all have
   free tiers; Cloudflare Workers also works).
2. In ChatGPT: Settings → Apps/Connectors → **Developer mode** → add your
   `https://<your-host>/mcp` URL. (Exact menu paths move — check the
   current Apps SDK docs if it looks different.)
3. Ask a trip question in ChatGPT — the model will discover and call your
   tools. Text output works immediately.

## Show the scorecard widget inline

The widget (`web/scorecard.html`) is served as an MCP resource with the
`text/html+skybridge` MIME type, and it's already wired: the
`shortlist_destinations` tool carries
`meta={"openai/outputTemplate": "ui://widget/scorecard.html"}` on its
decorator, so ChatGPT renders the scorecard inline in the chat.

## Submit to the ChatGPT app directory

1. Polish in developer mode until the flow works end-to-end.
2. Submit via OpenAI's app submission portal (**developers.openai.com/apps-sdk**).
   You need a verified developer account; OpenAI reviews for quality,
   safety, and data-use disclosure before listing. Only one version can be
   under review at a time.
3. Until approved, the app works privately via developer mode / direct link.

Reference: official examples at
`github.com/openai/openai-apps-sdk-examples`.

## Costs, plainly

- Building + testing in developer mode: **$0**
- Hosting: **$0** on free tiers (Render/Railway/Fly.io/Cloudflare)
- Reddit: **$0**
- Google Places API: **paid, usage-based** (this is the one real cost —
  check current pricing in Google Cloud before enabling billing)
- Instagram: **$0** (no API — deep links only)
- App directory submission: **$0**, but review-gated

## Files

- `engine.py` — dataset, matrix scoring, Reddit/Google/Instagram helpers
- `server.py` — MCP server (FastMCP) exposing the 4 tools + widget resource
- `web/scorecard.html` — inline scorecard widget (no dependencies)
- `requirements.txt` — `mcp` package
