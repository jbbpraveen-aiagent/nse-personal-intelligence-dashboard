import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(
    page_title="NSE Market Intelligence Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

NSE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/134.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": NSE + "/market-data/top-gainers-losers",
}

@st.cache_data(ttl=30, show_spinner=False)
def fetch_nse_json(path, referer):
    s = requests.Session()
    h = dict(HEADERS)
    h["Referer"] = referer
    home = s.get(referer, headers=h, timeout=20)
    home.raise_for_status()
    r = s.get(NSE + path, headers=h, timeout=20)
    r.raise_for_status()
    return r.json()

def num(v):
    try:
        return float(v)
    except Exception:
        return None

def sentiment(buy, sell):
    b, s = num(buy) or 0, num(sell) or 0
    total = b + s
    if not total:
        return None, None, "No book"
    bp = b / total * 100
    sp = 100 - bp
    label = "Buy-led" if bp >= 55 else ("Sell-led" if bp <= 45 else "Balanced")
    return bp, sp, label

@st.cache_data(ttl=30, show_spinner=False)
def load_gainers():
    raw = fetch_nse_json(
        "/api/live-analysis-variations?index=gainers",
        NSE + "/market-data/top-gainers-losers"
    )
    bucket = raw.get("allSec") or raw.get("FOSec")
    if not bucket:
        for v in raw.values():
            if isinstance(v, dict) and isinstance(v.get("data"), list):
                bucket = v
                break
    rows = bucket.get("data", []) if bucket else []
    rows = sorted(rows, key=lambda x: num(x.get("pChange")) or 0, reverse=True)[:20]

    out = []
    for x in rows:
        symbol = x.get("symbol", "")
        buy = sell = None
        last_update = x.get("lastUpdateTime") or x.get("lastUpdate")
        try:
            q = fetch_nse_json(
                "/api/quote-equity?symbol=" + requests.utils.quote(symbol) + "&section=trade_info",
                NSE + "/market-data/top-gainers-losers",
            )
            book = q.get("marketDeptOrderBook", {}) or {}
            buy = book.get("totalBuyQuantity")
            sell = book.get("totalSellQuantity")
            last_update = last_update or q.get("metadata", {}).get("lastUpdateTime")
        except Exception:
            pass

        bp, sp, label = sentiment(buy, sell)
        out.append({
            "Rank": len(out) + 1,
            "Symbol": symbol,
            "Company": x.get("companyName") or x.get("company") or symbol,
            "LTP ₹": num(x.get("ltp")),
            "Change %": num(x.get("pChange")),
            "Volume": num(x.get("totalTradedVolume")),
            "Buy Qty": num(buy),
            "Sell Qty": num(sell),
            "Buy %": bp,
            "Sell %": sp,
            "Sentiment": label,
            "Updated": last_update or "—",
        })
    return pd.DataFrame(out)

@st.cache_data(ttl=60, show_spinner=False)
def load_results():
    # NSE has changed this endpoint/schema over time, so try the current
    # corporate-results endpoint and filter records containing today's IST date.
    s = requests.Session()
    referer = NSE + "/companies-listing/corporate-filings-financial-results"
    h = dict(HEADERS)
    h["Referer"] = referer
    home = s.get(referer, headers=h, timeout=20)
    home.raise_for_status()

    today = datetime.now(ZoneInfo("Asia/Kolkata"))
    tokens = {
        today.strftime("%d-%b-%Y"),
        today.strftime("%d-%m-%Y"),
        today.strftime("%Y-%m-%d"),
        today.strftime("%d/%m/%Y"),
    }

    result = []
    for period in ["Quarterly", "Annual", "Half-Yearly", "Others"]:
        try:
            r = s.get(
                NSE + "/api/corporates-financial-results",
                params={"index": "equities", "period": period},
                headers=h,
                timeout=20,
            )
            r.raise_for_status()
            payload = r.json()
            arr = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
            if not isinstance(arr, list):
                continue
            for x in arr:
                text = " ".join(str(v) for v in x.values() if isinstance(v, str))
                if not any(t in text for t in tokens):
                    continue
                def pick(keys):
                    for k in keys:
                        if x.get(k) not in (None, ""):
                            return x.get(k)
                    return ""
                result.append({
                    "Symbol": pick(["symbol", "Symbol", "SYMBOL"]),
                    "Company": pick(["companyName", "company", "COMPANY NAME", "name"]),
                    "Period": pick(["period", "Period", "PERIOD"]) or period,
                    "Result Date": pick(["date", "Date", "submissionDate", "broadcastDate", "resultDate"]) or "Today",
                    "Nature": pick(["nature", "Nature", "natureOfReport", "financialResultType"]),
                    "Type": pick(["type", "Type", "resultType", "classification"]),
                    "Details": pick(["url", "link", "details", "xbrlUrl", "fileUrl"]),
                })
        except Exception:
            continue

    if not result:
        return pd.DataFrame(columns=["Symbol","Company","Period","Result Date","Nature","Type","Details"])
    return pd.DataFrame(result).drop_duplicates()

st.markdown("""
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 3rem;}
.small-note {color:#71809a;font-size:.88rem;}
.metric-card {padding:1rem;border:1px solid #e5eaf1;border-radius:12px;background:#fff;}
</style>
""", unsafe_allow_html=True)

st.title("📈 NSE Market Intelligence Dashboard")
st.caption("Top gainers + order-book sentiment + today's financial results • IST")

with st.sidebar:
    st.header("Controls")
    if st.button("🔄 Refresh NSE data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.write("**Market window:** 09:00–15:30 IST")
    st.write("**Source:** NSE India")
    st.caption("Buy/Sell % is calculated from total order-book quantities. It is not executed-trade classification.")

now = datetime.now(ZoneInfo("Asia/Kolkata"))
g1, g2, g3 = st.columns(3)
g1.metric("IST", now.strftime("%d %b %Y %H:%M:%S"))
g2.metric("Market window", "09:00 – 15:30")
try:
    gainers = load_gainers()
    g3.metric("Top gainers loaded", len(gainers))
except Exception as e:
    gainers = pd.DataFrame()
    g3.metric("Top gainers loaded", "Error")

st.subheader("Top NSE Gainers")
search = st.text_input("Search symbol/company", placeholder="e.g. RELIANCE")
if not gainers.empty:
    view = gainers.copy()
    if search:
        q = search.lower()
        view = view[view["Symbol"].str.lower().str.contains(q, na=False) |
                    view["Company"].str.lower().str.contains(q, na=False)]
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "LTP ₹": st.column_config.NumberColumn(format="₹ %.2f"),
            "Change %": st.column_config.NumberColumn(format="%.2f%%"),
            "Volume": st.column_config.NumberColumn(format="%,.0f"),
            "Buy Qty": st.column_config.NumberColumn(format="%,.0f"),
            "Sell Qty": st.column_config.NumberColumn(format="%,.0f"),
            "Buy %": st.column_config.NumberColumn(format="%.1f%%"),
            "Sell %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
else:
    st.warning("NSE market data could not be loaded. Press Refresh and try again.")

st.subheader("Corporate Financial Results — Today")
try:
    results = load_results()
except Exception:
    results = pd.DataFrame()

if not results.empty:
    rq = st.text_input("Search financial results", placeholder="Symbol/company")
    rv = results.copy()
    if rq:
        q = rq.lower()
        rv = rv[rv["Symbol"].str.lower().str.contains(q, na=False) |
                rv["Company"].str.lower().str.contains(q, na=False)]
    st.dataframe(rv, use_container_width=True, hide_index=True)
else:
    st.info("No current-day financial-results records were returned by the NSE endpoint, or the endpoint/schema was unavailable.")

st.divider()
st.caption(
    "Data source: NSE India public web endpoints. NSE may rate-limit or change these endpoints. "
    "For commercial redistribution, high-frequency/non-display use, or guaranteed real-time data, "
    "review NSE's applicable market-data products and data-sharing terms."
)
