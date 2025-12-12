# OnlineBusinessValidator

Streamlit app to validate online businesses:
- Google Reviews (SerpAPI optional)
- Free scraped reviews (Trustpilot, SiteJabber, Reddit, ProductHunt, Glassdoor, etc.)
- AI full business report (OpenAI optional)
- Single Excel output with 4 sheets:
  1. Google_Reviews (SerpAPI)
  2. API_Reviews (placeholder for other paid APIs)
  3. Scraped_Free_Reviews (fallback)
  4. AI_Full_Business_Report (structured)

## Quick start (Streamlit Cloud)
1. Commit `app.py`, `requirements.txt`, `README.md` to your GitHub repo.
2. Deploy on Streamlit Cloud (https://share.streamlit.io) pointing to `app.py`.
3. In the app sidebar you may paste:
   - SerpAPI Key (optional but recommended for Google reviews)
   - OpenAI API Key (optional for full AI report)
4. Enter a business name or website URL and click "Run Analysis".
5. Download Excel (4 sheets) when ready.

## Quick start (Google Colab)
1. Upload `app.py` to Colab.
2. Install dependencies:
