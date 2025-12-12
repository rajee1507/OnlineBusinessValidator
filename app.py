import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# NEW OpenAI client (2025 syntax)
from openai import OpenAI
client = None

# DuckDuckGo search (new stable version)
from duckduckgo_search import DDGS

import tldextract


# ==========================================================
# STREAMLIT CONFIG
# ==========================================================
st.set_page_config(page_title="Online Business Validator", layout="wide")
st.title("🔍 OnlineBusinessValidator")

st.markdown("""
Produces **one Excel file** with 4 sheets:

1. Google_Reviews  
2. API_Reviews  
3. Scraped_Free_Reviews  
4. AI_Full_Business_Report  
""")


# ==========================================================
# HELPERS
# ==========================================================
def safe_get(url):
    try:
        return requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12
        )
    except:
        return None


def get_domain(query):
    if query.startswith("http"):
        ext = tldextract.extract(query)
        return f"{ext.domain}.{ext.suffix}"
    if "." in query and " " not in query:
        return query
    return query.strip()


# ==========================================================
# GOOGLE REVIEWS — SERPAPI
# ==========================================================
def get_google_reviews(domain, serp_key):
    if not serp_key:
        return []

    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_maps_reviews",
        "q": domain,
        "hl": "en",
        "api_key": serp_key
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return []

        data = r.json()
        reviews = data.get("reviews") or []

        out = []
        for rv in reviews:
            out.append({
                "reviewer": rv.get("user_name"),
                "rating": rv.get("rating"),
                "date": rv.get("date"),
                "text": rv.get("text"),
                "link": rv.get("source")
            })
        return out
    except:
        return []


# ==========================================================
# SCRAPING — FREE SOURCES
# ==========================================================
def ddg_search(q, max_results=5):
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(q, max_results=max_results):
            if r and "href" in r:
                results.append(r["href"])
    return results


def extract_reviews_from_html(url, html):
    soup = BeautifulSoup(html, "html.parser")
    out = []

    # JSON-LD structured reviews
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except:
            continue

        if isinstance(data, dict):
            data = [data]

        for node in data:
            if not isinstance(node, dict):
                continue

            if "review" in node:
                revs = node["review"]
                if not isinstance(revs, list):
                    revs = [revs]

                for r in revs:
                    out.append({
                        "site": url,
                        "reviewer": r.get("author"),
                        "rating": (r.get("reviewRating") or {}).get("ratingValue"),
                        "date": r.get("datePublished"),
                        "text": r.get("reviewBody")
                    })

    # fallback — detect visible review-like text
    blocks = soup.find_all(
        ["p", "div"],
        string=re.compile(r"review|bad|good|service|experience|company|scam|refund", re.I)
    )

    for b in blocks:
        text = b.get_text(" ", strip=True)
        if len(text) > 50:
            out.append({
                "site": url,
                "reviewer": None,
                "rating": None,
                "date": None,
                "text": text
            })

    return out


def scrape_free_reviews(query):
    keywords = ["trustpilot", "sitejabber", "reddit", "glassdoor"]
    urls = []

    for site in keywords:
        urls.extend(ddg_search(f"{query} {site} reviews", max_results=3))

    all_reviews = []

    for u in urls:
        r = safe_get(u)
        if not r:
            continue
        html = r.text
        revs = extract_reviews_from_html(u, html)
        all_reviews.extend(revs)

    return all_reviews


# ==========================================================
# OPENAI — NEW API
# ==========================================================
def generate_ai_report(query, domain, google_df, free_df, openai_key):
    global client
    if not openai_key:
        return {"error": "OpenAI key not provided"}

    client = OpenAI(api_key=openai_key)

    prompt = f"""
Write a structured JSON due-diligence report.

Business: {query}
Domain: {domain}

Google reviews sample:
{google_df.head(5).to_dict('records')}

Scraped free reviews sample:
{free_df.head(5).to_dict('records')}

Return ONLY valid JSON with fields:
title, summary, risk_score, strengths, weaknesses,
sentiment, red_flags, recommendations, final_verdict
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=800
    )

    raw = resp.choices[0].message.content

    try:
        return json.loads(raw)
    except:
        return {"raw": raw}


# ==========================================================
# EXCEL BUILDER — FIXED
# ==========================================================
def build_excel(df1, df2, df3, ai):
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df1.to_excel(writer, sheet_name="Google_Reviews", index=False)
        df2.to_excel(writer, sheet_name="API_Reviews", index=False)
        df3.to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)

        ai_rows = [{"section": k, "content": str(v)} for k, v in ai.items()]
        pd.DataFrame(ai_rows).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)

    output.seek(0)
    return output.getvalue()


# ==========================================================
# UI
# ==========================================================
st.sidebar.header("API Keys")
openai_key = st.sidebar.text_input("OpenAI Key", type="password")
serp_key = st.sidebar.text_input("SerpAPI Key", type="password")

query = st.text_input("Business name or URL")
start = st.button("Run Analysis")


if start:
    if not query.strip():
        st.error("Enter a business name or domain")
    else:
        with st.spinner("Collecting reviews..."):

            domain = get_domain(query)

            google_reviews = get_google_reviews(domain, serp_key)
            df_google = pd.DataFrame(google_reviews)

            df_api = pd.DataFrame([], columns=["site", "reviewer", "rating", "date", "text"])

            free_reviews = scrape_free_reviews(query)
            df_free = pd.DataFrame(free_reviews)

            ai = generate_ai_report(query, domain, df_google, df_free, openai_key)

            excel_bytes = build_excel(df_google, df_api, df_free, ai)

            st.download_button(
                "Download Excel (4 sheets)",
                data=excel_bytes,
                file_name=f"report_{domain}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            st.success("Completed successfully!")
