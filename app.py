# OnlineBusinessValidator - app.py
# FULL WORKING STREAMLIT APPLICATION

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import openai
import whois
from duckduckgo_search import DDGS
import tldextract
import json
import re
import time

# ------------------
# Helper: Extract Domain
# ------------------
def get_domain(url_or_name):
    if "http" in url_or_name:
        ext = tldextract.extract(url_or_name)
        return f"{ext.domain}.{ext.suffix}"
    else:
        return url_or_name.replace(" ", "")

# ------------------
# WHOIS Lookup
# ------------------
def get_whois_info(domain):
    try:
        data = whois.whois(domain)
        return {
            "domain": domain,
            "creation_date": str(data.creation_date),
            "registrar": str(data.registrar),
            "org": str(data.org)
        }
    except:
        return {"error": "WHOIS not available"}

# ------------------
# Google Reviews Scraper (A + B Combined)
# ------------------
def scrape_google_reviews(business_name):
    results = []
    query = f"{business_name} Google reviews"

    try:
        with DDGS() as ddgs:
            links = [r.get("href") for r in ddgs.text(query, max_results=5)]

        for url in links:
            if not url:
                continue
            try:
                page = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                soup = BeautifulSoup(page.text, "html.parser")

                review_blocks = soup.find_all("span")
                for rb in review_blocks:
                    text = rb.get_text(strip=True)
                    if len(text) > 40:
                        results.append({"source": "Google", "text": text, "rating": None})
            except:
                pass

    except:
        pass

    return results

# ------------------
# General Review Scraper
# ------------------
def scrape_review_pages(domain):
    results = []
    try:
        with DDGS() as ddgs:
            pages = ddgs.text(f"{domain} reviews", max_results=10)

            for p in pages:
                url = p.get("href")
                if not url:
                    continue
                try:
                    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    soup = BeautifulSoup(r.text, "html.parser")
                    json_blocks = soup.find_all("script", {"type": "application/ld+json"})

                    for jb in json_blocks:
                        try:
                            data = json.loads(jb.string)
                            if isinstance(data, dict) and "review" in data:
                                for rv in data["review"]:
                                    results.append({
                                        "source": url,
                                        "author": rv.get("author"),
                                        "rating": rv.get("reviewRating", {}).get("ratingValue"),
                                        "text": rv.get("reviewBody")
                                    })
                        except:
                            pass

                except:
                    pass
    except:
        pass

    return results

# ------------------
# AI Analysis
# ------------------
def ai_analysis(api_key, business_name, domain, whois_info, review_count):
    if not api_key:
        return "Enter OpenAI API key to enable AI analysis."

    try:
        openai.api_key = api_key
        prompt = f"""
        Evaluate authenticity and trustworthiness of '{business_name}'.
        Domain: {domain}
        WHOIS: {whois_info}
        Number of reviews collected: {review_count}

        Provide:
        - Legitimacy score (0-100)
        - Business age reliability
        - Ethical concerns
        - Red flags
        - Final recommendation
        """

        completion = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI error: {e}"

# ------------------
# Streamlit UI
# ------------------
st.title("🔍 Online Business Validator")
st.write("Paste a URL or business name below.")

business_input = st.text_input("Business Name or URL:")
openai_key = st.text_input("OpenAI API Key (optional)", type="password")

if st.button("Run Analysis"):
    if not business_input:
        st.error("Please enter a business name or URL.")
    else:
        domain = get_domain(business_input)

        st.subheader("WHOIS Information")
        who = get_whois_info(domain)
        st.json(who)

        st.subheader("Google Reviews (Primary Source)")
        google_reviews = scrape_google_reviews(business_input)
        st.write(google_reviews)

        st.subheader("Other Public Reviews")
        other_reviews = scrape_review_pages(domain)
        st.write(other_reviews)

        all_reviews = google_reviews + other_reviews
        st.subheader(f"Total Reviews Found: {len(all_reviews)}")

        if len(all_reviews) > 0:
            df = pd.DataFrame(all_reviews)
            st.dataframe(df)

        st.subheader("AI Authenticity Analysis")
        ai_result = ai_analysis(openai_key, business_input, domain, who, len(all_reviews))
        st.write(ai_result)

# ------------------
# Always Create Excel + Enable Download Button
# ------------------
from io import BytesIO

st.subheader("📥 Download Full Report")

df = pd.DataFrame(all_reviews)

output = BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="Reviews")

excel_data = output.getvalue()

st.download_button(
    label="Download Excel Report",
    data=excel_data,
    file_name="business_validation_report.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
