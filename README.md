# NSE Streamlit Dashboard

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the Streamlit URL shown in the terminal.

## Publish cheaply

### Streamlit Community Cloud
For the cheapest/easiest public deployment:

1. Create a GitHub repository.
2. Upload `app.py` and `requirements.txt`.
3. Go to Streamlit Community Cloud.
4. Connect GitHub.
5. Select the repository and `app.py`.
6. Deploy.

You will receive a free Streamlit-hosted URL.

### Important
This dashboard uses NSE public web/API endpoints. NSE can rate-limit requests or change endpoint structures. The dashboard therefore includes a manual refresh and caching.

## Data interpretation

Buy % and Sell % are calculated from total buy/sell order-book quantities:

Buy % = Buy Qty / (Buy Qty + Sell Qty) × 100
Sell % = Sell Qty / (Buy Qty + Sell Qty) × 100

These percentages describe the displayed order-book quantities; they are not a definitive classification of executed trades.

The top-gainers endpoint is a live snapshot. This app does not automatically reconstruct every minute between 09:00 and 15:30. For a historical intraday time series, add scheduled polling plus storage.
