# app.py
"""
OnlineBusinessValidator - Streamlit app
- Input: Business Name or Website URL
- Sources included (best-effort):
   * Google Reviews via SerpAPI (recommended; optional API key)
   * Free discovery & scraping (Trustpilot, SiteJabber, G2, Capterra, Reviews.io, Reddit, Glassdoor, ProductHunt, Yelp, BBB, etc.)
   * AI structured report via OpenAI (optional API key)
- Output: single Excel workbook w/ 4 sheets:
   1) Google_Reviews
   2) API_Reviews (placeholder)
   3) Scraped_Free_Reviews
   4) AI_Full_Business_Report
Notes:
- Do not commit API keys to GitHub. Paste into the Streamlit sidebar.
- Scraping is best-effort; some sites block bots or use heavy JS. The app attempts JSON-LD, CSS selectors and heuristics.
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

# discovery
try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None

# domain extraction
try:
    import tldextract
except Exception:
    tldextract = None

# openai new client
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

st.set_page_config(page_title="OnlineBusinessValidator", layout="wide")
st.title("🔍 OnlineBusinessValidator")

st.markdown(
    "Enter a Business Name or Website URL. Optional: paste SerpAPI and OpenAI keys in sidebar. "
    "App will discover and scrape public review sources and produce a 4-sheet Excel report."
)

# ---------------------------
# Sidebar - API keys & options
# ---------------------------
st.sidebar.header("API Keys & Options (optional)")
OPENAI_KEY = st.sidebar.text_input("OpenAI API Key (optional)", type="password")
SERPAPI_KEY = st.sidebar.text_input("SerpAPI Key (optional)", type="password")
use_serpapi = st.sidebar.checkbox("Use SerpAPI for Google reviews (recommended)", value=bool(SERPAPI_KEY))
max_serp = st.sidebar.number_input("Max SerpAPI reviews", min_value=5, max_value=200, value=50, step=5)
st.sidebar.markdown("---")
st.sidebar.info("If SerpAPI key is not provided the app will rely on free discovery scraping as fallback.")

# ---------------------------
# Utilities
# ---------------------------
def safe_get(url, timeout=12):
    try:
        return requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=timeout)
    except Exception:
        return None

def normalize_input(q):
    q = q.strip()
    is_url = False
    if q.lower().startswith("http://") or q.lower().startswith("https://"):
        is_url = True
    elif "." in q and " " not in q:
        # domain-like
        is_url = True
    return q, is_url

def extract_domain(q):
    if q.lower().startswith("http://") or q.lower().startswith("https://"):
        if tldextract:
            ext = tldextract.extract(q)
            return f"{ext.domain}.{ext.suffix}"
        return re.sub(r"^https?://", "", q).split("/")[0]
    return q

# ---------------------------
# SerpAPI - Google Reviews
# ---------------------------
def serpapi_google_reviews(query, api_key, max_results=50):
    """
    Uses SerpAPI search.json engine google_maps_reviews or google_maps.
    Returns list of dicts: reviewer, rating, date, text, link, source
    """
    if not api_key:
        return []
    out = []
    try:
        params = {
            "engine": "google_maps_reviews",
            "q": query,
            "api_key": api_key,
            "hl": "en"
        }
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        if r.status_code != 200:
            # try google_maps engine fallback
            params["engine"] = "google_maps"
            r = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
            if r.status_code != 200:
                return []
        data = r.json()
        # primary place
        reviews = data.get("reviews") or []
        # some responses nest reviews
        if not reviews:
            for k in ("local_results", "places_results", "place"):
                node = data.get(k)
                if isinstance(node, dict):
                    if node.get("reviews"):
                        reviews = node.get("reviews")
                        break
                    # some nodes have 'reviews' list deeper
                    for v in node.values():
                        if isinstance(v, dict) and v.get("reviews"):
                            reviews = v.get("reviews")
                            break
        for rv in reviews[:max_results]:
            out.append({
                "source": "SerpAPI_Google",
                "site": "google",
                "reviewer": rv.get("user_name") or rv.get("author_name") or rv.get("username") or rv.get("author"),
                "rating": rv.get("rating") or rv.get("score"),
                "date": rv.get("date") or rv.get("relative_time_description") or rv.get("time"),
                "text": rv.get("text") or rv.get("snippet") or rv.get("review"),
                "link": rv.get("source") or None
            })
    except Exception:
        return []
    return out

# ---------------------------
# Discovery: DuckDuckGo search
# ---------------------------
def ddg_discover(query, sites=None, max_results=6):
    """
    Discover likely review pages using DuckDuckGo and site keywords.
    """
    if DDGS is None:
        return []
    if sites is None:
        sites = ["trustpilot", "sitejabber", "g2", "capterra", "reviews.io", "reddit", "glassdoor", "producthunt", "yelp", "bbb"]
    urls = []
    try:
        with DDGS() as ddgs:
            for s in sites:
                q = f"{query} {s}"
                for r in ddgs.text(q, max_results=max_results):
                    url = r.get("href") or r.get("url")
                    if url and url not in urls:
                        urls.append(url)
                time.sleep(0.1)
    except Exception:
        pass
    return urls

# ---------------------------
# Parsers for specific sites
# ---------------------------
def parse_trustpilot(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # Trustpilot changes classes frequently; attempt heuristics
    cards = soup.select("article") or soup.select(".review") or soup.select(".styles_reviewCard__")
    for c in cards:
        text = c.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        rating = None
        rtag = c.select_one("[data-rating]")
        if rtag:
            rating = rtag.get("data-rating")
        out.append({"source": "Trustpilot", "site": url, "reviewer": None, "rating": rating, "date": None, "text": text})
    return out

def parse_sitejabber(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".sitejabber-review") or soup.select(".review")
    for c in cards:
        text = c.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        out.append({"source": "SiteJabber", "site": url, "reviewer": None, "rating": None, "date": None, "text": text})
    return out

def parse_g2(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".paper_review, .review, .styles_review__")
    for c in cards:
        text = c.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        out.append({"source": "G2", "site": url, "reviewer": None, "rating": None, "date": None, "text": text})
    return out

def parse_capterra(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".review-card") or soup.select(".testimonial")
    for c in cards:
        text = c.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        out.append({"source": "Capterra", "site": url, "reviewer": None, "rating": None, "date": None, "text": text})
    return out

def parse_glassdoor(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # Glassdoor often hides content behind JS; we try to find review text in meta or in script tags
    # Look for JSON embedded or review text blocks
    # Heuristic: paragraphs containing 'work' 'salary' 'interview' etc.
    blocks = soup.find_all(["p","div","span"])
    for b in blocks:
        text = b.get_text(" ", strip=True)
        if len(text) < 80:
            continue
        if re.search(r"(work|salary|interview|manager|team|culture|benefit|office|feedback)", text, re.I):
            out.append({"source": "Glassdoor", "site": url, "reviewer": None, "rating": None, "date": None, "text": text})
    return out

def parse_reddit(html, url):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # Reddit pages often include post titles and comments as <p>, extract long ones
    posts = soup.find_all(["p","div"])
    for p in posts:
        text = p.get_text(" ", strip=True)
        if len(text) > 80 and re.search(r"(review|experience|scam|recommend|not recommend|service)", text, re.I):
            out.append({"source": "Reddit", "site": url, "reviewer": None, "rating": None, "date": None, "text": text})
    return out

def generic_extract(url, html):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    # JSON-LD reviews
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
                    t = r.get("reviewBody") or r.get("description") or ""
                    if len(t) < 30:
                        continue
                    out.append({"source": url, "site": url, "reviewer": (r.get("author") or {}).get("name") if isinstance(r.get("author"), dict) else r.get("author"), "rating": (r.get("reviewRating") or {}).get("ratingValue") if r.get("reviewRating") else None, "date": r.get("datePublished"), "text": t})
    # fallback heuristics
    paragraphs = soup.find_all(["p","li","div"])
    for p in paragraphs:
        txt = p.get_text(" ", strip=True)
        if len(txt) > 120 and re.search(r"(review|recommend|scam|refund|service|support|quality|experience)", txt, re.I):
            out.append({"source": url, "site": url, "reviewer": None, "rating": None, "date": None, "text": txt})
    return out

# router to pick parser
def parse_url_by_host(url, html):
    lower = url.lower()
    if "trustpilot.com" in lower:
        return parse_trustpilot(html, url)
    if "sitejabber.com" in lower:
        return parse_sitejabber(html, url)
    if "g2.com" in lower:
        return parse_g2(html, url)
    if "capterra.com" in lower:
        return parse_capterra(html, url)
    if "glassdoor.com" in lower:
        return parse_glassdoor(html, url)
    if "reddit.com" in lower:
        return parse_reddit(html, url)
    # fallback generic
    return generic_extract(url, html)

# ---------------------------
# Full page discovery + scraping
# ---------------------------
def scrape_discovered_pages(query):
    urls = ddg_discover(query, max_results=6)
    results = []
    for u in urls:
        r = safe_get(u)
        if not r or not r.text:
            continue
        try:
            parsed = parse_url_by_host(u, r.text)
            for item in parsed:
                item["discovered_url"] = u
            results.extend(parsed)
        except Exception:
            # generic fallback
            try:
                parsed = generic_extract(u, r.text)
                for item in parsed:
                    item["discovered_url"] = u
                results.extend(parsed)
            except Exception:
                continue
    return results

# ---------------------------
# OpenAI structured report
# ---------------------------
def build_prompt(business, domain, google_sample, scraped_sample, totals):
    return {
        "instruction": "You are a senior due-diligence analyst. Produce a one-page structured JSON report with fields: title, executive_summary, overall_score (0-100), strengths (list), weaknesses (list), customer_sentiment (short paragraph), red_flags (list), recommendations (list), next_steps (list), data_summary (object). Keep lists concise.",
        "business": business,
        "domain": domain,
        "google_sample": google_sample,
        "scraped_sample": scraped_sample,
        "totals": totals
    }

def call_openai_structured(api_key, prompt_obj):
    if OpenAI is None:
        return {"error": "OpenAI client not installed"}
    try:
        client = OpenAI(api_key=api_key)
        content = json.dumps(prompt_obj, default=str)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":"Return only valid JSON according to the instruction."},
                      {"role":"user","content":content}],
            max_tokens=900
        )
        # new client returns .choices[0].message.content
        raw = resp.choices[0].message.content
        try:
            return json.loads(raw)
        except Exception:
            m = re.search(r"(\{[\s\S]*\})", raw)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    return {"raw": raw}
            return {"raw": raw}
    except Exception as e:
        return {"error": str(e)}

# ---------------------------
# Excel builder
# ---------------------------
def build_excel_bytes(df_google, df_api, df_scraped, ai_report):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        # Google sheet
        try:
            df_google.to_excel(writer, sheet_name="Google_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text","link"]).to_excel(writer, sheet_name="Google_Reviews", index=False)
        # API placeholder
        try:
            df_api.to_excel(writer, sheet_name="API_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text"]).to_excel(writer, sheet_name="API_Reviews", index=False)
        # Scraped reviews
        try:
            df_scraped.to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text","discovered_url"]).to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)
        # AI sheet: structured key/value rows
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
            # extra keys
            for k,v in ai_report.items():
                if k not in order:
                    rows.append({"section": k, "content": str(v)})
            pd.DataFrame(rows).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
        else:
            pd.DataFrame([{"report": str(ai_report)}]).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
    out.seek(0)
    return out.getvalue()

# ---------------------------
# Streamlit main
# ---------------------------
st.header("Run Validation")
query = st.text_input("Enter Business name or website URL (e.g., LeadSquared or https://www.leadsquared.com)")
run = st.button("Run Analysis")

if run:
    if not query or not query.strip():
        st.error("Please enter a business name or URL.")
    else:
        with st.spinner("Collecting reviews and building report (this may take 20-90s)..."):
            q = query.strip()
            q_norm, is_url = normalize_input(q)
            domain = extract_domain(q_norm) if is_url else q_norm
            # 1) SerpAPI google reviews (if enabled)
            google_reviews = serpapi_google_reviews(domain if is_url else q_norm, SERPAPI_KEY, max_results=max_serp) if use_serpapi and SERPAPI_KEY else []
            # 2) API reviews placeholder (empty for now)
            api_reviews = []
            # 3) Free discovery + scraping
            scraped_reviews = scrape_discovered_pages(q)
            # dataframes
            df_google = pd.DataFrame(google_reviews) if google_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text","link"])
            df_api = pd.DataFrame(api_reviews) if api_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text"])
            df_scraped = pd.DataFrame(scraped_reviews) if scraped_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text","discovered_url"])
            # previews
            st.subheader("Google Reviews (preview)")
            if not df_google.empty:
                st.dataframe(df_google.head(10))
            else:
                st.info("No Google reviews collected. (If SerpAPI key provided and still empty, try different business name or check SerpAPI account.)")
            st.subheader("Scraped Free Reviews (preview)")
            if not df_scraped.empty:
                st.dataframe(df_scraped.head(10))
            else:
                st.info("No scraped reviews found this run. (Some sites block scraping or require JS.)")
            # AI analysis
            totals = {"google": len(df_google), "api": len(df_api), "scraped": len(df_scraped)}
            sample_google = df_google.head(5).to_dict(orient="records") if not df_google.empty else []
            sample_scraped = df_scraped.head(8).to_dict(orient="records") if not df_scraped.empty else []
            ai_prompt = build_prompt(q, domain, sample_google, sample_scraped, totals)
            ai_report = call_openai_structured(OPENAI_KEY, ai_prompt) if OPENAI_KEY else {"note": "OpenAI key not provided - no AI analysis"}
            # build excel
            bytes_xlsx = build_excel_bytes(df_google, df_api, df_scraped, ai_report)
            filename = f"validation_{re.sub(r'[^0-9a-zA-Z_-]', '_', q)[:40]}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.success("Report ready")
            st.download_button("Download Excel (4 sheets)", data=bytes_xlsx, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
