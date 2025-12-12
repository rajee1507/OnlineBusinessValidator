# Online Business Validator

This Streamlit app validates online businesses using multiple sources:

### ✔ Google Reviews (SerpAPI)
### ✔ Free Scraped Review Sources (Trustpilot, SiteJabber, Reddit, Glassdoor, etc.)
### ✔ AI Full Business Report (via OpenAI API)

The app generates **one Excel file** with 4 sheets:

1. Google_Reviews  
2. API_Reviews (placeholder, future expansion)
3. Scraped_Free_Reviews  
4. AI_Full_Business_Report  

---

## 🔧 Requirements

All dependencies are listed in `requirements.txt`:

- streamlit  
- requests  
- beautifulsoup4  
- pandas  
- openpyxl  
- tldextract  
- duckduckgo-search  
- openai>=1.0.0  

---

## 🚀 How to Run Locally

```bash
streamlit run app.py
