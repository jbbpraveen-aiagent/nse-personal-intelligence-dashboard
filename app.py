"""
NSE Pulse — Streamlit dashboard
--------------------------------
Shows NSE India's Top Gainers (all securities) with a derived buy/sell
sentiment split, plus today's Corporate Financial Results filings.

IMPORTANT — read this before deploying:
NSE India's site is not a public API. Its pages call internal JSON endpoints
that only respond to requests carrying a valid session cookie + browser-like
headers, and NSE periodically changes its anti-bot rules and endpoint shapes.
`get_session()` below does the same handshake a browser does (visits
nseindia.com to collect cookies, then reuses them on the data endpoint).
If a table stops loading after NSE changes something, open the relevant NSE
page in Chrome DevTools -> Network -> Fetch/XHR, find the request returning
the JSON, and update NSE_ENDPOINTS below.

Also note: some hosts (including some cloud IP ranges) get blocked by NSE
more than a home connection would. If you deploy this and get repeated
"could not fetch" errors, that is almost always this, not a bug in the code.
"""

import time
from datetime import datetime, date

import pandas as pd
import requests
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False


# ----------------------------- Config -----------------------------

NSE_BASE = "https://www.nseindia.com"
REFERER_GAINERS = f"{NSE_BASE}/market-data/top-gainers-losers"
REFERER_RESULTS = f"{NSE_BASE}/companies-listing/corporate-filings-financial-results"

NSE_ENDPOINTS = {
    "gainers_losers": f"{NSE_BASE}/api/live-analysis-variations?index=gainers",
    "corporate_results": f"{NSE_BASE}/api/corporates-financial-results?index=equities",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "DNT": "1",
}

COOKIE_TTL_SECONDS = 4 * 60
MAX_FETCH_RETRIES = 2

st.set_page_config(
    page_title="NSE Pulse — Top Gainers & Corporate Results",
    page_icon="📈",
    layout="wide",
)


# ----------------------------- NSE session handling -----------------------------

def _build_session(referer: str) -> requests.Session:
    """
    Do the same multi-step handshake a real browser does: visit the
    homepage first (sets base cookies), then the actual page that would
    call this API (some cookies/anti-bot tokens are set per-section, not
    just on the homepage).
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    session.get(NSE_BASE, timeout=10)
    time.sleep(0.3)
    session.get(referer, headers={"Referer": NSE_BASE}, timeout=10)
    return session


def get_session(referer: str, force: bool = False) -> requests.Session:
    """Reuse a cached session with fresh-enough cookies across reruns."""
    now = time.time()
    key = f"_nse_session_{referer}"
    time_key = f"_nse_cookie_time_{referer}"
    cached = st.session_state.get(key)
    fetched_at = st.session_state.get(time_key, 0)

    if not force and cached and (now - fetched_at) < COOKIE_TTL_SECONDS:
        return cached

    try:
        session = _build_session(referer)
    except requests.RequestException:
        session = cached or requests.Session()  # fetch call below will surface the real error

    st.session_state[key] = session
    st.session_state[time_key] = now
    return session


def fetch_json(referer: str, url: str):
    """
    Fetch JSON from an NSE endpoint. Retries with a freshly rebuilt session
    if the first attempt comes back 401/403 — this recovers from a stale or
    rejected cookie. If NSE is blocking the *IP* the request comes from
    (common on shared cloud hosts), every retry will still fail with 403 —
    that's a hosting/IP issue, not something headers alone can fix. See the
    README's "Deployed and still getting 403" section.
    """
    last_error = None
    for attempt in range(MAX_FETCH_RETRIES):
        session = get_session(referer, force=(attempt > 0))
        try:
            resp = session.get(url, headers={"Referer": referer}, timeout=10)
            if resp.status_code in (401, 403):
                last_error = requests.HTTPError(
                    f"{resp.status_code} Client Error: Forbidden for url: {url}"
                )
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
    raise last_error


# ----------------------------- Sentiment heuristic -----------------------------

def sentiment_for(pchange: float, volume: float, avg_volume: float):
    """
    Derived "sentiment", not raw order-book buy/sell depth.
    NSE's list endpoints don't expose live per-symbol buy/sell quantities for
    an entire table at once, so this reads directional strength from
    % change plus how volume compares to the table's average volume.
    """
    change = pchange or 0
    vol_ratio = (volume / avg_volume) if avg_volume else 1

    if change > 0:
        label = "Strong Buying" if (change >= 10 or vol_ratio >= 2) else (
            "Buying" if change >= 3 else "Mild Buying"
        )
        buy_pct = min(95, 55 + change * 2 + min(vol_ratio, 3) * 3)
    elif change < 0:
        label = "Strong Selling" if (change <= -10 or vol_ratio >= 2) else (
            "Selling" if change <= -3 else "Mild Selling"
        )
        buy_pct = max(5, 45 + change * 2 - min(vol_ratio, 3) * 3)
    else:
        label, buy_pct = "Neutral", 50

    buy_pct = round(max(0, min(100, buy_pct)))
    return label, buy_pct, 100 - buy_pct


# ----------------------------- Data fetchers -----------------------------

def load_gainers():
    data = fetch_json(REFERER_GAINERS, NSE_ENDPOINTS["gainers_losers"])
    section = data.get("allSec") or data.get("NIFTY") or {}
    rows = (section.get("gainers") or {}).get("data", [])

    if not rows:
        return pd.DataFrame(), None

    volumes = [float(r.get("trade_quantity") or r.get("tradeQuantity") or 0) for r in rows]
    avg_volume = (sum(volumes) / len(volumes)) if volumes else 1

    records = []
    for r in rows:
        pchange = float(r.get("perChange") or r.get("per_change") or r.get("pChange") or 0)
        volume = float(r.get("trade_quantity") or r.get("tradeQuantity") or 0)
        label, buy_pct, sell_pct = sentiment_for(pchange, volume, avg_volume)
        records.append({
            "Symbol": r.get("symbol"),
            "LTP": r.get("ltp"),
            "Prev Close": r.get("previousPrice") or r.get("prev_price"),
            "Change": r.get("netPrice") or r.get("net_price"),
            "% Change": pchange,
            "Volume": volume,
            "Sentiment": label,
            "Buy %": buy_pct,
            "Sell %": sell_pct,
        })

    return pd.DataFrame(records), datetime.now()


def load_results():
    data = fetch_json(REFERER_RESULTS, NSE_ENDPOINTS["corporate_results"])
    rows = data if isinstance(data, list) else data.get("data", [])

    if not rows:
        return pd.DataFrame(), False

    today_str = date.today().isoformat()
    todays_rows = [
        r for r in rows
        if str(r.get("broadcastDate") or r.get("filingDate") or r.get("exchdisstime") or "")[:10] == today_str
    ]
    use_rows = todays_rows if todays_rows else rows

    records = [{
        "Symbol": r.get("symbol") or r.get("SYMBOL"),
        "Company": r.get("companyName") or r.get("comp"),
        "Period": r.get("period") or r.get("re_period"),
        "Period Type": r.get("periodType") or r.get("re_periodType"),
        "Audited": r.get("audited") or r.get("re_auditedType"),
        "Filed On": r.get("broadcastDate") or r.get("filingDate"),
    } for r in use_rows]

    return pd.DataFrame(records), bool(todays_rows)


# ----------------------------- Styling helpers -----------------------------

CUSTOM_CSS = """
<style>
:root {
  --accent: #FF9B45;
  --gain: #34D399;
  --loss: #F76C6C;
}
.nse-badge {
  display: inline-block; padding: 3px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600;
}
.nse-badge.buy { background: rgba(52,211,153,0.14); color: var(--gain); }
.nse-badge.sell { background: rgba(247,108,108,0.14); color: var(--loss); }
.nse-badge.neutral { background: rgba(138,150,172,0.14); color: #8A96AC; }

.split-wrap { display:flex; align-items:center; gap:8px; }
.split-bar { width: 90px; height: 6px; border-radius: 999px; background: var(--loss); overflow:hidden; }
.split-bar > span { display:block; height:100%; background: var(--gain); }
.split-text { font-size: 11.5px; color: #8A96AC; white-space:nowrap; }

.pos { color: var(--gain); font-weight: 600; }
.neg { color: var(--loss); font-weight: 600; }

.ticker-tape {
  background:#05070C; border:1px solid #232D42; border-radius:8px;
  overflow:hidden; white-space:nowrap; height:34px; display:flex; align-items:center;
  margin-bottom: 14px;
}
.ticker-track { display:inline-flex; gap:32px; padding-left:100%; animation: scroll-ticker 35s linear infinite; }
@keyframes scroll-ticker { from { transform: translateX(0); } to { transform: translateX(-100%); } }
.ticker-item { font-family: monospace; font-size: 12.5px; color: #8A96AC; }
.ticker-item .sym { color:#E7ECF5; font-weight:600; }
.ticker-item.up { color: var(--gain); }
.ticker-item.down { color: var(--loss); }

.status-pill {
  display:inline-flex; align-items:center; gap:8px; padding:5px 12px;
  border-radius:999px; border:1px solid #232D42; background:#121826;
  font-size: 13px; color:#8A96AC;
}
.dot { width:8px; height:8px; border-radius:50%; background: var(--gain); }
.dot.pulse { box-shadow: 0 0 0 0 rgba(52,211,153,0.6); animation: pulse 1.6s infinite; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(52,211,153,0.55); }
  70% { box-shadow: 0 0 0 8px rgba(52,211,153,0); }
  100% { box-shadow: 0 0 0 0 rgba(52,211,153,0); }
}

/* stretch dataframe tables full width, tighter row height */
.stDataFrame { font-size: 13.5px; }
</style>
"""


def render_ticker_html(df: pd.DataFrame) -> str:
    if df.empty:
        return '<div class="ticker-tape"><div class="ticker-track"><span class="ticker-item">Loading market ticker…</span></div></div>'

    top = df.head(15)
    items = []
    for _, r in top.iterrows():
        direction = "up" if (r["% Change"] or 0) >= 0 else "down"
        arrow = "▲" if direction == "up" else "▼"
        items.append(
            f'<span class="ticker-item {direction}"><span class="sym">{r["Symbol"]}</span> {arrow} {r["% Change"]:.2f}%</span>'
        )
    html_items = "".join(items)
    return f'<div class="ticker-tape"><div class="ticker-track">{html_items}{html_items}</div></div>'


def gainers_table_html(df: pd.DataFrame) -> str:
    rows_html = []
    for _, r in df.iterrows():
        cls = "pos" if (r["% Change"] or 0) >= 0 else "neg"
        buy_pct = r["Buy %"]
        badge_cls = "buy" if buy_pct >= 55 else ("sell" if buy_pct <= 45 else "neutral")
        rows_html.append(f"""
          <tr>
            <td style="font-weight:600">{r['Symbol']}</td>
            <td>{r['LTP']}</td>
            <td>{r['Prev Close']}</td>
            <td class="{cls}">{r['Change']}</td>
            <td class="{cls}">{r['% Change']:.2f}%</td>
            <td>{int(r['Volume']):,}</td>
            <td><span class="nse-badge {badge_cls}">{r['Sentiment']}</span></td>
            <td>
              <div class="split-wrap">
                <span class="split-bar"><span style="width:{buy_pct}%"></span></span>
                <span class="split-text">{buy_pct}% / {r['Sell %']}%</span>
              </div>
            </td>
          </tr>""")

    return f"""
    <div style="overflow-x:auto;">
    <table style="width:100%; border-collapse:collapse; font-size:13.5px;">
      <thead>
        <tr style="text-align:left; color:#8A96AC; font-size:11px; text-transform:uppercase; letter-spacing:.04em;">
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">Symbol</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">LTP (₹)</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">Prev Close</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">Change</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">% Change</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">Volume</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">Sentiment</th>
          <th style="padding:10px 12px; border-bottom:1px solid #232D42;">Buy / Sell</th>
        </tr>
      </thead>
      <tbody>{"".join(rows_html)}</tbody>
    </table>
    </div>
    """


# ----------------------------- App layout -----------------------------

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

header_left, header_right = st.columns([3, 2])
with header_left:
    st.markdown(
        '<h1 style="font-size:26px; margin-bottom:0;">'
        '<span style="color:#FF9B45;">NSE</span> Pulse</h1>',
        unsafe_allow_html=True,
    )
    st.caption("Top gainers & corporate results, live from NSE India")

with header_right:
    status_ph = st.empty()

st.divider()

# --- Controls ---
c1, c2, c3, c4 = st.columns([1, 1, 1.4, 2])
with c1:
    manual_refresh = st.button("🔄 Refresh now", use_container_width=True)
with c2:
    auto_on = st.toggle("Auto-refresh", value=False)
with c3:
    interval_label = st.selectbox(
        "Interval",
        ["Every 30s", "Every 1 min", "Every 5 min"],
        index=1,
        disabled=not auto_on,
        label_visibility="collapsed",
    )
with c4:
    if auto_on and not HAS_AUTOREFRESH:
        st.warning("Install `streamlit-autorefresh` (see requirements.txt) to enable auto-refresh.", icon="⚠️")

interval_ms = {"Every 30s": 30_000, "Every 1 min": 60_000, "Every 5 min": 300_000}[interval_label]

if auto_on and HAS_AUTOREFRESH:
    st_autorefresh(interval=interval_ms, key="nse_autorefresh")

# --- Fetch data (on load, manual click, or autorefresh rerun) ---
ticker_ph = st.empty()

try:
    gainers_df, gainers_time = load_gainers()
    gainers_error = None
except Exception as e:  # noqa: BLE001
    gainers_df, gainers_time, gainers_error = pd.DataFrame(), None, str(e)

try:
    results_df, is_today = load_results()
    results_error = None
except Exception as e:  # noqa: BLE001
    results_df, is_today, results_error = pd.DataFrame(), False, str(e)

status_ok = gainers_error is None and results_error is None
with header_right:
    status_ph.markdown(
        f"""
        <div style="text-align:right;">
          <span class="status-pill">
            <span class="dot {'pulse' if status_ok else ''}" style="background:{'#34D399' if status_ok else '#F76C6C'};"></span>
            {'Live' if status_ok else 'Connection issue'}
          </span>
          <div style="font-size:12px; color:#8A96AC; margin-top:6px; font-family:monospace;">
            Updated {datetime.now().strftime('%I:%M:%S %p')}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

ticker_ph.markdown(render_ticker_html(gainers_df), unsafe_allow_html=True)

# --- Top Gainers panel ---
st.subheader("Top Gainers · All Securities")
st.caption(
    "Sentiment is a derived read on % move and traded volume — not raw order-book buy/sell "
    "depth (NSE doesn't expose that for a whole list at once). A quick visual read, not investment advice."
)

if gainers_error:
    st.error(f"Could not fetch gainers from NSE right now: {gainers_error}")
elif gainers_df.empty:
    st.info("No gainers returned right now — market may be closed, or try refresh.")
else:
    st.caption(f"{len(gainers_df)} securities")
    st.markdown(gainers_table_html(gainers_df), unsafe_allow_html=True)

st.divider()

# --- Corporate Results panel ---
st.subheader("Corporate Financial Results")
st.caption(
    "Quarterly / annual results filings broadcast by companies today. "
    "Falls back to the latest available filings if none were posted yet today."
)

if results_error:
    st.error(f"Could not fetch corporate results from NSE right now: {results_error}")
elif results_df.empty:
    st.info("No filings found.")
else:
    label = "filed today" if is_today else "most recent available (none filed yet today)"
    st.caption(f"{len(results_df)} filings — {label}")
    st.dataframe(results_df, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Data sourced live from NSE India. Market hours: 9:15 AM – 3:30 PM IST, Mon–Fri. "
    "Outside market hours the feed may return the last traded session."
)

if manual_refresh:
    st.rerun()
