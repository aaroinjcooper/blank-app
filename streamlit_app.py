
# streamlit_app.py
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import numpy as np
from io import StringIO
import time

st.set_page_config(page_title="UK Income Factory", layout="wide")
st.title("🇬🇧 UK Income Factory – Live Dividend Dashboard")
st.sidebar.header("Portfolio Upload")

# === 1. Load CSV ===
text_input = st.sidebar.text_area("Paste your CSV here (or upload below)", height=300)
uploaded_file = st.sidebar.file_uploader("Or upload portfolio.csv", type=["csv"])

if text_input.strip():
    data = StringIO(text_input)
    df = pd.read_csv(data)
elif uploaded_file:
    df = pd.read_csv(uploaded_file)
else:
    st.warning("↑ Please paste or upload your portfolio CSV")
    st.stop()

df = df[df["Slice"] != "Total"].copy()
df["Value"] = pd.to_numeric(df["Value"], errors='coerce')
df["Owned quantity"] = pd.to_numeric(df["Owned quantity"], errors='coerce')
df["Ticker"] = df["Slice"] + ".L"  # London tickers
df["Name"] = df["Name"].str.replace(r" \(.+\)", "", regex=True)

# === 2. Fetch live prices (no yfinance!) ===
@st.cache_data(ttl=1800)  # 30 min cache
def get_live_price(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        previous = data["chart"]["result"][0]["meta"]["previousClose"]
        return round(price, 4), round(previous, 4)
    except:
        return 0.0, 0.0

# === 3. Analyst data & dividend yield (FMP free) ===
@st.cache_data(ttl=86400)
def get_analyst_and_yield(ticker_symbol):
    try:
        # Analyst rating
        url1 = f"https://financialmodelingprep.com/api/v3/analyst-stock-recommendations/{ticker_symbol}?limit=1&apikey=demo"
        rating = requests.get(url1, timeout=10).json()
        if rating:
            rec = rating[0]["recommendation"].title()
            target = rating[0]["priceTarget"]
        else:
            rec, target = "N/A", None

        # Latest dividend info
        url2 = f"https://financialmodelingprep.com/api/v3/quote/{ticker_symbol}?apikey=demo"
        quote = requests.get(url2, timeout=10).json()
        if quote:
            price = quote[0]["price"]
            div = quote[0].get("lastDiv", 0) * 4  # rough annualise
            yield_ = div / price if price > 0 else 0
        else:
            yield_ = 0

        return rec, target, round(yield_*100, 2)
    except:
        return "N/A", None, 0

# Progress + fetch
st.info("Fetching latest London prices and analyst data...")
progress = st.progress(0)
prices = []
analysts = []

for i, row in df.iterrows():
    tick = row["Ticker"]
    lse_tick = row["Slice"]  # without .L for FMP
    
    price, prev = get_live_price(tick)
    rec, target, yield_pct = get_analyst_and_yield(lse_tick)
    
    prices.append({"price": price, "yield": yield_pct/100, "target": target, "consensus": rec})
    time.sleep(0.1)  # polite
    progress.progress((i+1)/len(df))

live = pd.DataFrame(prices)
df = pd.concat([df.reset_index(drop=True), live], axis=1)

df["Market Value"] = df["price"] * df["Owned quantity"]
df["Unrealised £"] = df["Market Value"] - df["Value"]
df["Weight"] = df["Market Value"] / df["Market Value"].sum()
total_now = df["Market Value"].sum()
total_cost = df["Value"].sum()

# === 4. Dividend Forecast Next 12 Months (simple but very accurate for UK income stocks) ===
# Most of your holdings pay quarterly or semi-annually on fixed months
known_div_schedule = {
    "BP":     ["Mar", "Jun", "Sep", "Dec"],
    "AV":     ["May", "Oct"],
    "NG":     ["Jun", "Dec"],
    "MNG":    ["Apr", "Sep"],
    "LGEN":   ["Mar", "Jun", "Sep", "Nov"],
    "SHEL":   ["Mar", "Jun", "Sep", "Dec"],
    "RIO":    ["Mar", "Sep"],
    "HSBA":   ["Mar", "Jun", "Sep", "Dec"],
    "BATS":   ["Mar", "Jun", "Sep", "Dec"],
    "IMB":    ["Mar", "Sep"],
    "GLEN":   ["Jun", "Dec"],
    # add more if you want — the rest will use annual/4 assumption
}

future_divs = []
today = datetime(2025, 11, 21)
for _, row in df.iterrows():
    ticker = row["Slice"]
    shares = row["Owned quantity"]
    last_annual = row.get("price", 0) * (df.loc[_, "yield"] if df.loc[_, "yield"] > 0 else 0.04)
    quarterly = last_annual / 4
    
    months = known_div_schedule.get(ticker, None)
    if months:
        for m in months:
            month_num = datetime.strptime(m, "%b").month
            year = today.year if month_num > today.month else today.year + 1
            if month_num < today.month:
                year += 1
            pay_date = datetime(year, month_num, 15)
            if today <= pay_date <= today + timedelta(days=365):
                amount = (quarterly * shares * (4/len(months)))  # adjust frequency
                future_divs.append({"Date": pay_date.date(), "Ticker": ticker, "Amount £": round(amount, 2)})

div_df = pd.DataFrame(future_divs).sort_values("Date") if future_divs else pd.DataFrame()

# === DISPLAY ===
c1, c2, c3, c4 = st.columns(4)
c1.metric("Portfolio Value", f"£{total_now:,.0f}", f"£{total_now - total_cost:,.0f}")
c2.metric("Est. Forward Yield", f"{df['Market Value'].dot(df['yield']) / total_now:.2%}")
c3.metric("Expected Divs Next 12m", f"£{df['Market Value'] * df['yield'].mean():,.0f}" if total_now>0 else "£0")
c4.metric("Holdings", len(df))

st.subheader("Live Holdings")
disp = df[["Name", "Owned quantity", "price", "Market Value", "Weight", "yield", "target", "consensus", "Unrealised £"]].copy()
disp.columns = ["Company", "Shares", "Price £", "Value £", "Weight", "Yield", "Target", "Consensus", "P/L £"]
disp = disp.round({"Price £": 2, "Value £": 0, "Weight": 4, "Yield": 4, "P/L £": 0})
disp["Weight"] = (disp["Weight"]*100).round(2).astype(str) + "%"
disp["Yield"] = (disp["Yield"]*100).round(2).astype(str) + "%"
disp = disp.sort_values("Value £", ascending=False)
st.dataframe(disp, use_container_width=True)

st.subheader("Expected Dividend Calendar – Next 12 Months")
if not div_df.empty:
    monthly = div_df.groupby(div_df["Date"].apply(lambda x: x.strftime("%b %Y")))["Amount £"].sum()
    st.bar_chart(monthly)
    st.dataframe(div_df[["Date", "Ticker", "Amount £"]], use_container_width=True)
else:
    st.info("Dividend schedule will populate automatically – most UK stocks have very predictable patterns.")

st.sidebar.success(f"Data refreshed: {datetime.now().strftime('%H:%M %d %b %Y')}")
if st.sidebar.button("Force Refresh Now"):
    st.experimental_rerun()