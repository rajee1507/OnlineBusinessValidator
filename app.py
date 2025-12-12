import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime
import time

# optional libs
try:
    from duckduckgo_search import ddg
except Exception:
    ddg = None

try:
    import tldextract
except Exception:
    tldextract = None

try:
    import openai
except Exception:
    openai = None


# ==========================================================
# STREAMLIT CONFIG
# ==========================================================
st.set_page_config(page_title="Online Business Validator", layout="wide")
st.title("🔍 OnlineBusinessValidator")


st.markdown("""
Enter a business name **OR** website URL.  
Optional: Paste SerpAPI + OpenAI API keys in sidebar.  
App will produce **one Excel file with 4 sheets**:
1. Google_Reviews  
2. API_Reviews (placeholder)  
3. Scraped_Free_Reviews  
4. AI_Full_Business_Report (structured)
""")


# ==========================================================
# UTILS
# ==========================================================
def safe_get(url, timeout=12):
    try:
        return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    except:
        return None


def get_domain_from_input(q):
    if q.startswith("http"):
        try:
            if tldextract:
                ext = tldextract.extract(q)
                return f"{ext.domain}.{ext.suffix}"
            return re.sub(r"^https?://", "", q).split("/")[0]
        except:
            return q
    if "." in q and " " not in q:
        return q
    return q.strip()


# ==========================================================
# GENERIC REVIEW EXTRACTOR
# ==========================================================
def extract_reviews_from_html_generic(url, html):
    results = []
    if not html:
        return results

    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except:
            continue

        nodes = data if isinstance(data, list) else [data]

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("@type") in ("Product", "Service") and node.get("review"):
                for r in node["review"]:
                    results.append({
                        "source": url,
                        "site": url,
                        "reviewer": r.get("author"),
                        "rating": (r.get("reviewRating") or {}).get("ratingValue"),
                        "date": r.get("datePublished"),
                        "text": r.get("reviewBody")
                    })

            if node.get("@type") == "Review":
                results.append({
                    "source": url,
                    "site": url,
                    "reviewer": node.get("author"),
                    "rating": (node.get("reviewRating") or {}).get("ratingValue"),
                    "date": node.get("datePublished"),
                    "text": node.get("reviewBody")
                })

    # heuristic fallback
    candidates = soup.find_all(class_=re.compile("review|comment|testimonial|rating", re.I))
    for c in candidates:
        text = c.get_text(" ", strip=True)
        if len(text) < 40:
            continue
        results.append({
            "source": url,
            "site": url,
            "reviewer": None,
            "rating": None,
            "date": None,
            "text": text
        })

    return results


# ==========================================================
# SERPAPI GOOGLE REVIEWS
# ==========================================================
def serpapi_google_reviews(query, serpapi_key):
    if not serpapi_key:
        return []

    try:
        params = {
            "engine": "google_maps_reviews",
            "q": query,
            "api_key": serpapi_key,
            "hl": "en"
        }

        r = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        if r.status_code != 200:
            return []

        data = r.json()
        reviews = data.get("reviews", [])

        out = []
        for r in reviews:
            out.append({
                "source": "SerpAPI_Google",
                "site": "google",
                "reviewer": r.get("user_name"),
                "rating": r.get("rating"),
                "date": r.get("date"),
                "text": r.get("text"),
                "link": r.get("source")
            })
        return out

    except:
        return []


# ==========================================================
# DISCOVERY SCRAPER
# ==========================================================
def discover_review_pages(query):
    if ddg is None:
        return []

    sources = ["trustpilot", "sitejabber", "reddit", "producthunt", "glassdoor"]
    pages = []

    for s in sources:
        hits = ddg(f"{query} {s}", max_results=4)
        for h in hits or []:
            url = h.get("href") or h.get("url")
            if url:
                pages.append(url)

    return pages


def scrape_multiple_pages(query):
    pages = discover_review_pages(query)
    all_reviews = []

    for u in pages:
        r = safe_get(u)
        if not r:
            continue
        revs = extract_reviews_from_html_generic(u, r.text)
        all_reviews.extend(revs)

    return all_reviews


# ==========================================================
# AI PROMPT
# ==========================================================
def build_ai_prompt(business, domain, google, scraped):
    return f"""
You are a due-diligence analyst. Produce a full one-page structured JSON report.

Business: {business}
Domain: {domain}

Google sample reviews: {google}
Scraped sample reviews: {scraped}

Return ONLY valid JSON with fields:
title, executive_summary, overall_score, strengths, weaknesses,
customer_sentiment, red_flags, recommendations, next_steps, data_summary
"""


def call_openai(openai_key, prompt):
    if not openai_key:
        return None

    try:
        openai.api_key = openai_key
        r = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=900
        )
        raw = r["choices"][0]["message"]["content"]

        try:
            return json.loads(raw)
        except:
            m = re.search(r"(\{[\s\S]*\})", raw)
            if m:
                return json.loads(m.group(1))
            return {"raw_unparsed": raw}

    except Exception as e:
        return {"error": str(e)}


# ==========================================================
# EXCEL BUILDER (FIXED — NO writer.save())
# ==========================================================
def build_excel_bytes(df_google, df_api, df_scrape, ai):
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_google.to_excel(writer, sheet_name="Google_Reviews", index=False)
        df_api.to_excel(writer, sheet_name="API_Reviews", index=False)
        df_scrape.to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)

        # AI structured sheet
        if isinstance(ai, dict):
            rows = [{"section": k, "content": str(v)} for k, v in ai.items()]
            pd.DataFrame(rows).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
        else:
            pd.DataFrame([{"raw": str(ai)}]).to_excel(
                writer, sheet_name="AI_Full_Business_Report", index=False
            )

    output.seek(0)
    return output.getvalue()


# ==========================================================
# STREAMLIT UI
# ==========================================================
st.sidebar.header("API Keys (optional)")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password")
serpapi_key = st.sidebar.text_input("SerpAPI Key", type="password")

query = st.text_input("Business name OR website URL")
run = st.button("Run Analysis")


if run:
    if not query.strip():
        st.error("Enter a business name or URL.")
    else:
        with st.spinner("Running full analysis..."):

            domain = get_domain_from_input(query)
            st.write("Domain:", domain)

            google_reviews = serpapi_google_reviews(domain, serpapi_key)
            df_google = pd.DataFrame(google_reviews)

            api_df = pd.DataFrame([], columns=["source","site","reviewer","rating","date","text"])

            scraped = scrape_multiple_pages(query)
            df_scrape = pd.DataFrame(scraped)

            # AI
            prompt = build_ai_prompt(query, domain, df_google.head(5).to_dict("records"), df_scrape.head(5).to_dict("records"))
            ai_report = call_openai(openai_key, prompt) if openai_key else {"info": "OpenAI key not provided"}

            # excel
            excel_bytes = build_excel_bytes(df_google, api_df, df_scrape, ai_report)

            filename = f"report_{domain}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"

            st.download_button(
                "Download Excel (4 sheets)",
                data=excel_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            st.success("Completed.")
