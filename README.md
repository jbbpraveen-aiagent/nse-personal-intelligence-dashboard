# NSE Pulse — Streamlit Dashboard

A mobile-friendly Streamlit dashboard showing:
- **Top Gainers (all securities)** from NSE India, with a derived buy/sell sentiment split and volume
- **Today's Corporate Financial Results filings**
- Manual refresh button + toggleable auto-refresh (30s / 1min / 5min)

## Please read this first — how NSE data actually behaves

NSE India's site is not a public API. Its pages call **internal JSON endpoints** that only respond
to requests carrying a valid session cookie and browser-like headers, and NSE periodically changes
its anti-bot rules. `app.py` does the same handshake a browser does (visits `nseindia.com` first to
collect cookies, then calls the data endpoint with those cookies), so it works most of the time —
but two things can break it, through no fault of the code:

1. **NSE changes an endpoint or its parameters.** If a table stops loading, open
   `https://www.nseindia.com/market-data/top-gainers-losers` (or the corporate-results page) in
   Chrome, open **DevTools → Network → Fetch/XHR**, reload, and find the request returning the same
   JSON shown in NSE's own table. Copy that URL into `NSE_ENDPOINTS` near the top of `app.py`.
2. **NSE blocks the IP range of your host.** Streamlit Community Cloud, like most free hosts, can
   occasionally get rate-limited or blocked by NSE more than a home connection would. If you deploy
   and see repeated "could not fetch" errors, that's usually this rather than a bug — try again
   later, or self-host on your own network as a fallback.

**On the "buy/sell sentiment %"**: NSE's public top-gainers list does not expose live order-book
buy/sell depth per stock across an entire list at once. The dashboard instead shows a **derived
sentiment** from % price change and relative trading volume — a fast visual read, clearly labeled
as such, not raw broker order-book data or investment advice.

## Run it locally

Requires Python 3.9+.

```bash
pip install -r requirements.txt
streamlit run app.py
```

It opens at **http://localhost:8501**. For access from your phone on the same Wi-Fi, use your
computer's local IP instead, e.g. `http://192.168.1.23:8501` — this alone covers "internal team
use" at zero hosting cost.

## Publish it for free (public URL)

### Option A — Streamlit Community Cloud (recommended, free, made for this)
1. Push this folder to a new **public** GitHub repository (Community Cloud's free tier requires a
   public repo, or a private one on a paid plan).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → connect your GitHub repo.
3. Set:
   - **Main file path:** `app.py`
   - Leave the rest as default — Streamlit Cloud reads `requirements.txt` and
     `.streamlit/config.toml` automatically.
4. Deploy. You'll get a public URL like `https://your-app-name.streamlit.app`.
5. Free-tier note: the app "sleeps" after a period of no visitors and takes a few seconds to wake
   on the next visit — fine for internal/occasional use.

### Option B — Render.com or Railway.app (alternative)
Both can also run a Streamlit app for free using a start command like:
```
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```
Streamlit Community Cloud is simpler and purpose-built for this, so start there.

## Project structure

```
nse-streamlit-dashboard/
├── app.py                    # Everything: data fetch, sentiment logic, UI
├── requirements.txt
└── .streamlit/
    └── config.toml            # Dark theme colors
```

## Customizing

- **Colors**: edit `.streamlit/config.toml` (theme) and the `CUSTOM_CSS` block at the top of
  `app.py` (badges, ticker, split bars).
- **Auto-refresh intervals**: edit the options list passed to `st.selectbox` in `app.py`.
- **"Today only" filter for results**: `load_results()` in `app.py` filters to today's date and
  falls back to the latest available filings if none were posted yet — adjust that logic if you'd
  rather always show the latest N filings regardless of date.

## Note on auto-refresh

Auto-refresh uses the `streamlit-autorefresh` package (in `requirements.txt`), which triggers a
full script rerun on a timer — this is the standard way to do timed refreshes in Streamlit, since
Streamlit doesn't have refresh loops built in natively. If you ever remove that package, the
"Auto-refresh" toggle will show a warning and only the manual refresh button will work.
