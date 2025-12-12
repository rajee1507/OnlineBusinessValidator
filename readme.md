# OnlineBusinessValidator

Streamlit app that validates online businesses by collecting reviews and generating an AI report.

## What it does
- Accepts a **Business Name** or **Website URL**.
- Automatically discovers public review pages (Trustpilot, SiteJabber, Reddit, Glassdoor, ProductHunt, etc.) and scrapes them.
- Optionally fetches Google Reviews using **SerpAPI** (put your SerpAPI key in the sidebar).
- Optionally generates a full structured AI report using **OpenAI** (put your OpenAI key in the sidebar).
- Produces a single Excel file with 4 sheets:
  1. Google_Reviews
  2. API_Reviews (placeholder)
  3. Scraped_Free_Reviews
  4. AI_Full_Business_Report

## How to run (Streamlit Cloud)
1. Commit `app.py`, `requirements.txt`, `README.md` to your GitHub repo.
2. Deploy to Streamlit Cloud (https://share.streamlit.io) and point to `app.py`.
3. Open the app, paste API keys (optional), input business name or URL and click **Run Analysis**.
4. Download the Excel report.

## How to run (Colab / local)
Install dependencies:
```bash
pip install -r requirements.txt
