# app.py
"""
OnlineBusinessValidator - Streamlit app
- Input: Business name OR website URL
- Sources:
    - Google Reviews via SerpAPI (optional; put key in sidebar)
    - Free discovery + scraping (DuckDuckGo discovery: Trustpilot, SiteJabber, Reviews.io, Reddit, Glassdoor, etc.)
    - API_Reviews sheet reserved for other paid APIs (kept)
- AI full business report via OpenAI (optional; put key in sidebar)
- Output: single Excel file with 4 sheets:
    1) Google_Reviews
    2) API_Reviews
    3) Scraped_Free_Reviews
    4) AI_Full_Business_Report
"""

import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import json
import re
import time
from datetime import datetime

# optional libs
try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None

try:
    import tldextract
except Exception:
    tldextract = None

# new OpenAI client
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

st.set_page_config(page_title="OnlineBusinessValidator", layout="wide")
st.title("🔍 OnlineBusinessValidator")

st.markdown(
    "Enter a business **name** or **URL**. Optionally paste SerpAPI and OpenAI keys in the sidebar. "
    "App will collect reviews and generate one Excel file with 4 sheets."
)

# ----------------------------
# Sidebar - API keys & options
# ----------------------------
st.sidebar.header("API Keys & Options (optional)")
openai_key = st.sidebar.text_input("OpenAI API Key (optional)", type="password")
serpapi_key = st.sidebar.text_input("SerpAPI Key (optional)", type="password")
use_serp = st.sidebar.checkbox("Use SerpAPI for Google reviews (recommended)", value=bool(serpapi_key))
max_serp = st.sidebar.number_input("Max SerpAPI reviews", min_value=5, max_value=200, value=50, step=5)
st.sidebar.markdown("---")
st.sidebar.info("If you do not provide SerpAPI key the app will still run, using free discovery scraping as fallback.")

# ----------------------------
# Helpers
# ----------------------------
def safe_get(url, timeout=12):
    try:
        return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    except Exception:
        return None

def normalize_input(q):
    q = q.strip()
    if q.startswith("http://") or q.startswith("https://"):
        return q, True
    # heuristic: contains a dot and no spaces -> treat as url/domain
    if "." in q and " " not in q:
        return q, True
    return q, False

def extract_domain(q):
    if q.startswith("http"):
        if tldextract:
            ext = tldextract.extract(q)
            return f"{ext.domain}.{ext.suffix}"
        return re.sub(r"^https?://", "", q).split("/")[0]
    return q

# ----------------------------
# SerpAPI (Google Reviews)
# ----------------------------
def serpapi_google_reviews(query, key, max_results=50):
    if not key:
        return []
    out = []
    try:
        params = {
            "engine": "google_maps_reviews",
            "q": query,
            "api_key": key,
            "hl": "en"
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        if resp.status_code != 200:
            # try alternate engine
            params_alt = {"engine": "google_maps", "q": query, "api_key": key, "hl": "en"}
            resp = requests.get("https://serpapi.com/search.json", params=params_alt, timeout=20)
            if resp.status_code != 200:
                return []
        data = resp.json()
        reviews = data.get("reviews") or []
        # fallback nested
        if not reviews:
            for k in ("local_results", "places_results", "place_results"):
                node = data.get(k)
                if isinstance(node, dict) and node.get("reviews"):
                    reviews = node.get("reviews")
                    break
        for r in reviews[:max_results]:
            out.append({
                "source": "SerpAPI_Google",
                "site": "google",
                "reviewer": r.get("user_name") or r.get("author_name") or r.get("username") or r.get("author"),
                "rating": r.get("rating") or r.get("score"),
                "date": r.get("date") or r.get("relative_time_description") or r.get("time"),
                "text": r.get("text") or r.get("snippet") or r.get("review"),
                "link": r.get("source") or None
            })
    except Exception:
        return []
    return out

# ----------------------------
# Free discovery (DuckDuckGo) and scrapers for common sites
# ----------------------------
def ddg_discover(query, sites=None, max_results=5):
    if DDGS is None:
        return []
    if sites is None:
        sites = ["trustpilot", "sitejabber", "reviews", "reddit", "glassdoor", "producthunt", "yelp", "bbb"]
    urls = []
    try:
        with DDGS() as ddgs:
            for s in sites:
                q = f"{query} {s}"
                for r in ddgs.text(q, max_results=max_results):
                    href = r.get("href") or r.get("url")
                    if href and href not in urls:
                        urls.append(href)
                    time.sleep(0.1)
    except Exception:
        pass
    return urls

def parse_trustpilot(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # trustpilot uses review-card elements; selectors may vary; attempt multiple fallbacks
    cards = soup.select("article[data-businessunit-review-id], .review-card, .paper__content")
    if not cards:
        cards = soup.select(".styles_reviewCard__")  # try a class prefix
    for c in cards:
        text = c.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        rating = None
        rtag = c.select_one("[data-rating]")
        if rtag:
            try:
                rating = rtag.get("data-rating")
            except:
                rating = None
        out.append({"source": "Trustpilot", "site": url, "reviewer": None, "rating": rating, "date": None, "text": text})
    return out

def parse_sitejabber(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".sitejabber-review, .review")
    for c in cards:
        text = c.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        out.append({"source": "SiteJabber", "site": url, "reviewer": None, "rating": None, "date": None, "text": text})
    return out

def generic_extract(url, html):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict) and ("review" in node or node.get("@type") == "Review"):
                reviews = node.get("review") or [node]
                if not isinstance(reviews, list):
                    reviews = [reviews]
                for r in reviews:
                    text = r.get("reviewBody") or r.get("description") or ""
                    if len(text) < 20:
                        continue
                    out.append({"source": url, "site": url, "reviewer": (r.get("author") or {}).get("name") if isinstance(r.get("author"), dict) else r.get("author"), "rating": (r.get("reviewRating") or {}).get("ratingValue") if r.get("reviewRating") else None, "date": r.get("datePublished"), "text": text})
    # heuristic fallback: find large paragraphs containing likely review words
    paragraphs = soup.find_all(["p","div","li"])
    for p in paragraphs:
        txt = p.get_text(" ", strip=True)
        if len(txt) < 60:
            continue
        if re.search(r"(review|scam|refund|service|complaint|happy|poor|excellent|rating)", txt, re.I):
            out.append({"source": url, "site": url, "reviewer": None, "rating": None, "date": None, "text": txt})
    return out

def scrape_discovered_pages(query):
    urls = ddg_discover(query, max_results=6)
    all_reviews = []
    for u in urls:
        r = safe_get(u)
        if not r or not r.text:
            continue
        html = r.text
        # choose specific parsers for known sites
        lower = u.lower()
        parsed = []
        try:
            if "trustpilot.com" in lower:
                parsed = parse_trustpilot(html, u)
            elif "sitejabber.com" in lower:
                parsed = parse_sitejabber(html, u)
            else:
                parsed = generic_extract(u, html)
        except Exception:
            parsed = generic_extract(u, html)
        for p in parsed:
            p["discovered_url"] = u
        all_reviews.extend(parsed)
    return all_reviews

# ----------------------------
# AI structured report (OpenAI new client)
# ----------------------------
def build_prompt_structured(business, domain, google_sample, scraped_sample, totals):
    return {
        "instruction": "You are a senior due-diligence analyst. Produce a structured JSON one-page report with keys: title, executive_summary, overall_score (0-100), strengths (list), weaknesses (list), customer_sentiment (short paragraph), red_flags (list), recommendations (list), next_steps (list), data_summary (object). Keep list items concise.",
        "business": business,
        "domain": domain,
        "google_sample": google_sample,
        "scraped_sample": scraped_sample,
        "totals": totals
    }

def call_openai_structured(openai_key, prompt_obj):
    if OpenAI is None:
        return {"error": "OpenAI client library not installed"}
    try:
        client = OpenAI(api_key=openai_key)
        # convert prompt_obj to a readable string for the model
        content = json.dumps(prompt_obj, default=str)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":"Return only valid JSON according to the instructions."},
                      {"role":"user","content":content}],
            max_tokens=900
        )
        text = resp.choices[0].message.content
        # try to parse json from model
        try:
            parsed = json.loads(text)
            return parsed
        except Exception:
            m = re.search(r"(\{[\s\S]*\})", text)
            if m:
                try:
                    return json.loads(m.group(1))
                except:
                    return {"raw": text}
            return {"raw": text}
    except Exception as e:
        return {"error": str(e)}

# ----------------------------
# Excel builder (4 sheets)
# ----------------------------
def build_excel_bytes(df_google, df_api, df_scraped, ai_report):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        try:
            df_google.to_excel(writer, sheet_name="Google_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text","link"]).to_excel(writer, sheet_name="Google_Reviews", index=False)
        try:
            df_api.to_excel(writer, sheet_name="API_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text"]).to_excel(writer, sheet_name="API_Reviews", index=False)
        try:
            df_scraped.to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text","discovered_url"]).to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)
        # AI sheet - structured
        if isinstance(ai_report, dict):
            rows = []
            order = ["title","executive_summary","overall_score","strengths","weaknesses","customer_sentiment","red_flags","recommendations","next_steps","data_summary"]
            for k in order:
                if k in ai_report:
                    v = ai_report[k]
                    if isinstance(v, list):
                        rows.append({"section": k, "content": "; ".join([str(x) for x in v])})
                    else:
                        rows.append({"section": k, "content": str(v)})
            for k,v in ai_report.items():
                if k not in order:
                    rows.append({"section": k, "content": str(v)})
            pd.DataFrame(rows).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
        else:
            pd.DataFrame([{"report": str(ai_report)}]).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
    out.seek(0)
    return out.getvalue()

# ----------------------------
# Streamlit UI main
# ----------------------------
st.header("Run Validation")
query = st.text_input("Enter Business Name or Website URL (Example: LeadSquared or https://www.leadsquared.com)")
run = st.button("Run Analysis")

if run:
    if not query or not query.strip():
        st.error("Please enter a business name or URL.")
    else:
        with st.spinner("Collecting reviews and building report..."):
            q = query.strip()
            is_url = q.startswith("http://") or q.startswith("https://") or ("." in q and " " not in q)
            domain = extract_domain(q) if is_url else q
            # 1) Google reviews via SerpAPI
            google_reviews = serpapi_google_reviews(domain if is_url else q, serpapi_key, max_results=max_serp) if use_serp else []
            # 2) API Reviews placeholder - kept empty for now (we reserved for future APIs)
            api_reviews = []
            # 3) Free discovery + scraping
            scraped_reviews = scrape_discovered_pages(q)
            # normalize dataframes
            df_google = pd.DataFrame(google_reviews) if google_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text","link"])
            df_api = pd.DataFrame(api_reviews) if api_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text"])
            df_scraped = pd.DataFrame(scraped_reviews) if scraped_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text","discovered_url"])
            # show previews
            st.subheader("Google Reviews (preview)")
            if not df_google.empty:
                st.dataframe(df_google.head(10))
            else:
                st.info("No Google reviews collected. (If SerpAPI key provided and still empty, try different business name.)")
            st.subheader("Scraped Free Reviews (preview)")
            if not df_scraped.empty:
                st.dataframe(df_scraped.head(10))
            else:
                st.info("No scraped reviews found this run.")
            # AI analysis
            totals = {"google": len(df_google), "api": len(df_api), "scraped": len(df_scraped)}
            sample_google = df_google.head(5).to_dict(orient="records") if not df_google.empty else []
            sample_scraped = df_scraped.head(8).to_dict(orient="records") if not df_scraped.empty else []
            ai_input = build_prompt_structured(q, domain, sample_google, sample_scraped, totals)
            ai_report = call_openai_structured(openai_key, ai_input) if openai_key else {"note": "OpenAI key not provided - no AI analysis"}
            # prepare excel
            bytes_xlsx = build_excel_bytes(df_google, df_api, df_scraped, ai_report)
            filename = f"validation_{re.sub(r'[^0-9a-zA-Z_-]', '_', q)[:40]}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.success("Report ready")
            st.download_button("Download Excel (4 sheets)", data=bytes_xlsx, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
