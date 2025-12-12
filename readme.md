# OnlineBusinessValidator

Streamlit app that validates online businesses by collecting reviews and generating an AI report.

## Features
- Input: Business name or Website URL
- Sources:
  - Google Reviews (via SerpAPI) — recommended
  - Free-discovery scraped reviews: Trustpilot, SiteJabber, G2, Capterra, Reviews.io, Reddit, Glassdoor, ProductHunt, Yelp, BBB, etc.
  - AI structured report (OpenAI) — optional
- Output: single Excel workbook with 4 sheets:
  1. Google_Reviews
  2. API_Reviews (placeholder)
  3. Scraped_Free_Reviews
  4. AI_Full_Business_Report

## Quick start
1. Commit `app.py`, `requirements.txt`, `README.md` to your GitHub repo.
2. Deploy to Streamlit Cloud (`app.py` as main file) or run locally with:
