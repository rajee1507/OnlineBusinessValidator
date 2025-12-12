# app.py
# OnlineBusinessValidator - Streamlit app
# - SERPAPI (Google reviews) optional (enter key in sidebar)
# - Free scraping fallback (Trustpilot, SiteJabber, Reddit, ProductHunt, Glassdoor etc)
# - OpenAI optional (full AI formatted one-page report)
# - Excel export: one file with 4 sheets:
#    Sheet1: Google Reviews (SerpAPI)
#    Sheet2: API_Reviews (reserved for other paid API integrations - will be empty unless keys used)
#    Sheet3: Scraped_Free_Reviews (fallback)
#    Sheet4: AI_Full_Business_Report (structured)
#
# NOTE: Do not hardcode API keys in code. Paste keys into the sidebar when you run the app.

import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime
import time

# optional libs that may not be installed; handle gracefully
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

# -----------------------
# Helpers
# -----------------------
st.set_page_config(page_title="Online Business Validator", layout="wide")
st.title("🔍 OnlineBusinessValidator")

st.markdown(
    "Enter a business name or website URL. Optionally paste API keys (SerpAPI, OpenAI) in the sidebar. "
    "The app will fetch Google reviews (via SerpAPI if available), discover other review pages and scrape them, "
    "and produce a downloadable Excel workbook with 4 sheets."
)

def safe_get(url, timeout=12, headers=None):
    headers = headers or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        return r
    except Exception:
        return None

def is_url(text):
    return text.startswith("http://") or text.startswith("https://") or "." in text

def get_domain_from_input(q):
    if not q:
        return ""
    if q.startswith("http"):
        try:
            if tldextract:
                ext = tldextract.extract(q)
                return f"{ext.domain}.{ext.suffix}"
            else:
                # fallback
                parsed = re.sub(r'^https?://', '', q).split('/')[0]
                return parsed
        except Exception:
            return q
    if "." in q and " " not in q:
        return q
    return q.strip()

# review extraction generic (JSON-LD or heuristic)
def extract_reviews_from_html_generic(url, html):
    results = []
    if not html:
        return results
    soup = BeautifulSoup(html, "html.parser")
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict):
                # Product / Service with reviews
                if node.get("@type") in ("Product","Service") and node.get("review"):
                    revs = node.get("review")
                    if isinstance(revs, list):
                        for r in revs:
                            results.append({
                                "source": url,
                                "site": url,
                                "reviewer": (r.get("author") or {}).get("name") if isinstance(r.get("author"), dict) else r.get("author"),
                                "rating": (r.get("reviewRating") or {}).get("ratingValue") if r.get("reviewRating") else None,
                                "date": r.get("datePublished"),
                                "text": r.get("reviewBody") or r.get("description")
                            })
                elif node.get("@type") == "Review":
                    results.append({
                        "source": url,
                        "site": url,
                        "reviewer": (node.get("author") or {}).get("name") if isinstance(node.get("author"), dict) else node.get("author"),
                        "rating": (node.get("reviewRating") or {}).get("ratingValue") if node.get("reviewRating") else None,
                        "date": node.get("datePublished"),
                        "text": node.get("reviewBody") or node.get("description")
                    })
    # Heuristic extraction: common review classes and large paragraphs
    candidates = soup.find_all(class_=re.compile(r"review|testimonial|rating|comment|feedback|customer", re.I))
    if not candidates:
        candidates = soup.find_all(["article","li","blockquote","p"])
    seen = set()
    for c in candidates:
        text = c.get_text(separator=" ", strip=True)
        if not text or len(text) < 40:
            continue
        key = text[:150]
        if key in seen:
            continue
        seen.add(key)
        reviewer = None
        auth = c.find(class_=re.compile(r"author|user|name|reviewer", re.I))
        if auth:
            reviewer = auth.get_text(strip=True)
        rating = None
        m = re.search(r"(\d(\.\d)?)/5", text)
        if m:
            rating = m.group(1)
        results.append({
            "source": url,
            "site": url,
            "reviewer": reviewer,
            "rating": rating,
            "date": None,
            "text": text
        })
    return results

# -----------------------
# SerpAPI (Google reviews) - optional
# -----------------------
def serpapi_google_reviews(query, serpapi_key, max_results=50):
    """
    Uses SerpAPI (https://serpapi.com) to fetch Google Maps/Business reviews.
    If serpapi_key is empty or request fails, returns empty list.
    """
    if not serpapi_key:
        return []
    out = []
    try:
        # Use engine=google_maps_reviews (or google_maps)
        params = {
            "engine": "google_maps_reviews",
            "q": query,
            "api_key": serpapi_key,
            "hl": "en"
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        if resp.status_code != 200:
            # Try alternative engine
            params_alt = {"engine":"google_maps","q":query,"api_key":serpapi_key}
            resp_alt = requests.get("https://serpapi.com/search.json", params=params_alt, timeout=20)
            if resp_alt.status_code == 200:
                data = resp_alt.json()
            else:
                return []
        else:
            data = resp.json()
        # SerpAPI returns 'reviews' or 'local_results' depending on engine
        reviews = data.get("reviews") or []
        # some results put reviews under 'local_results' -> 'reviews' etc.
        if not reviews:
            # try to extract nested reviews
            for k in ("local_results","local_results","places_results","place"):
                if isinstance(data.get(k), dict) and data.get(k).get("reviews"):
                    reviews = data.get(k).get("reviews")
                    break
        for r in reviews:
            out.append({
                "source": "SerpAPI_Google",
                "site": "google",
                "reviewer": r.get("user_name") or r.get("author_name") or r.get("username") or r.get("author"),
                "rating": r.get("rating") or r.get("score"),
                "date": r.get("time") or r.get("date") or r.get("relative_time_description"),
                "text": r.get("text") or r.get("snippet") or r.get("review"),
                "link": r.get("source") or None
            })
    except Exception:
        return []
    return out

# -----------------------
# Free scrape: discover pages with ddg and scrape common review sites
# -----------------------
def discover_review_pages(query, sources=["trustpilot","sitejabber","reddit","producthunt","glassdoor","complaints","reviews"]):
    urls = []
    if ddg is None:
        return urls
    try:
        for s in sources:
            q = f"{query} {s}"
            hits = ddg(q, max_results=4)
            if hits:
                for h in hits:
                    u = h.get("href") or h.get("url")
                    if u and u not in urls:
                        urls.append({"source_hint": s, "url": u, "title": h.get("title")})
            time.sleep(0.3)
    except Exception:
        pass
    return urls

def scrape_multiple_review_pages(query):
    pages = discover_review_pages(query)
    all_reviews = []
    for p in pages:
        u = p.get("url")
        if not u:
            continue
        r = safe_get(u)
        if not r:
            continue
        revs = extract_reviews_from_html_generic(u, r.text)
        # attach source_hint if provided
        for rv in revs:
            rv["discovered_from"] = p.get("source_hint")
        if revs:
            all_reviews.extend(revs)
    return all_reviews

# -----------------------
# AI Analysis - full formatted one page
# -----------------------
def build_ai_prompt_structured(business, domain, whois_info, google_sample, scraped_sample, totals):
    # Create a detailed prompt telling the model to return JSON with sections.
    prompt = {
        "instruction": (
            "You are a senior due-diligence analyst. Produce a full one-page business validation report in JSON. "
            "Return a JSON object with keys: title, executive_summary, overall_score (0-100), strengths (list), weaknesses (list), customer_sentiment (short paragraph), red_flags (list), recommendations (list), next_steps (list), data_summary (object). "
            "Use the data provided. Keep each list items short (max 20 words each). Use the 'data_summary' to include counts of reviews by source."
        ),
        "business": business,
        "domain": domain,
        "whois": whois_info,
        "google_sample": google_sample,
        "scraped_sample": scraped_sample,
        "totals": totals
    }
    # Return as single string prompt
    return json.dumps(prompt, indent=2)

def call_openai_for_report(openai_key, prompt_text):
    if not openai_key or openai is None:
        return None
    try:
        openai.api_key = openai_key
        # ask for JSON output
        system_msg = "You are a concise business due-diligence analyst. Output only valid JSON as described."
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt_text}
        ]
        resp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=messages, max_tokens=900)
        content = resp["choices"][0]["message"]["content"]
        # Try to parse JSON out of the response
        try:
            j = json.loads(content)
            return {"parsed": j, "raw": content}
        except Exception:
            # attempt to find JSON substring
            m = re.search(r"(\{[\s\S]*\})", content)
            if m:
                try:
                    j = json.loads(m.group(1))
                    return {"parsed": j, "raw": content}
                except Exception:
                    return {"parsed": None, "raw": content}
            return {"parsed": None, "raw": content}
    except Exception as e:
        return {"error": str(e)}

# -----------------------
# Excel builder: 4 sheets - Google, API_Reviews (placeholder), Scraped, AI_Report
# -----------------------
def build_excel_bytes(google_df, api_df, scraped_df, ai_report_structured):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # sheet 1 - Google Reviews
        try:
            google_df.to_excel(writer, sheet_name="Google_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text"]).to_excel(writer, sheet_name="Google_Reviews", index=False)
        # sheet 2 - API Reviews (placeholder)
        try:
            api_df.to_excel(writer, sheet_name="API_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text"]).to_excel(writer, sheet_name="API_Reviews", index=False)
        # sheet 3 - Scraped Free Reviews
        try:
            scraped_df.to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)
        except Exception:
            pd.DataFrame([], columns=["source","site","reviewer","rating","date","text"]).to_excel(writer, sheet_name="Scraped_Free_Reviews", index=False)
        # sheet 4 - AI Full Business Report: structured layout
        # ai_report_structured is expected to be dict (parsed JSON) or raw text
        if isinstance(ai_report_structured, dict):
            # Create a DataFrame with two columns: section, content
            rows = []
            # flatten known keys in preferred order
            order = ["title","executive_summary","overall_score","strengths","weaknesses","customer_sentiment","red_flags","recommendations","next_steps","data_summary"]
            for k in order:
                if k in ai_report_structured:
                    val = ai_report_structured[k]
                    if isinstance(val, list):
                        rows.append({"section": k, "content": "; ".join([str(x) for x in val])})
                    else:
                        rows.append({"section": k, "content": str(val)})
            # any other keys
            for k,v in ai_report_structured.items():
                if k not in order:
                    rows.append({"section": k, "content": str(v)})
            df_ai = pd.DataFrame(rows)
            df_ai.to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
        else:
            # place raw text into single cell
            pd.DataFrame([{"report": str(ai_report_structured)}]).to_excel(writer, sheet_name="AI_Full_Business_Report", index=False)
    writer.save()
    output.seek(0)
    return output.getvalue()

# -----------------------
# Streamlit UI - Sidebar for API keys / options
# -----------------------
st.sidebar.header("API Keys & Options (Optional)")
openai_key = st.sidebar.text_input("OpenAI API Key (optional)", type="password")
serpapi_key = st.sidebar.text_input("SerpAPI Key (optional)", type="password")
# placeholder for other future API keys
other_api_note = st.sidebar.text_input("Other API Key (optional)", type="password")

st.sidebar.markdown("---")
st.sidebar.markdown("Options:")
use_serpapi = st.sidebar.checkbox("Use SerpAPI for Google reviews (recommended)", value=bool(serpapi_key))
max_serp_records = st.sidebar.number_input("Max SerpAPI reviews to fetch", min_value=5, max_value=200, value=50, step=5)
st.sidebar.markdown("Free scrapers will always run as fallback/discovery.")

st.header("Run Business Validation")
query = st.text_input("Enter business name or website URL (e.g. LeadSquared or https://www.leadsquared.com)")

col1, col2 = st.columns(2)
with col1:
    run_btn = st.button("Run Analysis")
with col2:
    download_when_ready = st.checkbox("Show download button after run (checked)", value=True)

if run_btn:
    if not query or not str(query).strip():
        st.error("Enter a business name or URL to proceed.")
    else:
        with st.spinner("Collecting data... this may take 10-80s depending on APIs and scraping"):
            q = str(query).strip()
            domain = get_domain_from_input(q)
            st.subheader("Business / Domain")
            st.write(domain)

            # WHOIS (lightweight) - we won't fail if whois import missing
            whois_info = {}
            try:
                if 'whois' in globals():
                    import whois as whois_mod
                    try:
                        who = whois_mod.whois(domain)
                        whois_info = {
                            "domain": domain,
                            "creation_date": str(getattr(who, "creation_date", None)),
                            "registrar": str(getattr(who, "registrar", None)),
                            "org": str(getattr(who, "org", None))
                        }
                    except Exception as e:
                        whois_info = {"error": str(e)}
                else:
                    whois_info = {"note": "whois lib not installed"}
            except Exception as e:
                whois_info = {"error": str(e)}
            st.json(whois_info)

            # 1) Google Reviews via SerpAPI (if key and enabled)
            google_reviews = []
            if use_serpapi and serpapi_key:
                try:
                    serp_query = domain if "." in domain else q
                    google_reviews = serpapi_google_reviews(serp_query, serpapi_key, max_results=max_serp_records)
                    st.write(f"SerpAPI Google reviews: {len(google_reviews)}")
                except Exception as e:
                    st.warning("SerpAPI call failed: " + str(e))
                    google_reviews = []
            else:
                st.info("SerpAPI not used (key missing or disabled).")

            # 2) Other API reviews placeholder (empty unless you add integrations)
            api_reviews = []  # reserved for future API aggregation (e.g., other paid review APIs)
            st.write(f"API-based reviews collected: {len(api_reviews)}")

            # 3) Free scraped pages discovery + extraction
            st.write("Discovering review pages (Trustpilot, SiteJabber, Reddit, ProductHunt, Glassdoor etc.)")
            scraped_reviews = scrape_multiple_review_pages(q)
            st.write(f"Scraped review snippets found: {len(scraped_reviews)}")

            # Convert to DataFrames
            df_google = pd.DataFrame(google_reviews) if google_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text","link"])
            df_api = pd.DataFrame(api_reviews) if api_reviews else pd.DataFrame(columns=["source","site","reviewer","rating","date","text"])
            # normalize scraped reviews
            if scraped_reviews:
                # ensure columns presence
                for r in scraped_reviews:
                    for k in ["source","site","reviewer","rating","date","text","discovered_from"]:
                        if k not in r:
                            r[k] = None
                df_scraped = pd.DataFrame(scraped_reviews)
            else:
                df_scraped = pd.DataFrame(columns=["source","site","reviewer","rating","date","text","discovered_from"])

            st.subheader("Preview - Google Reviews (top 10)")
            if not df_google.empty:
                st.dataframe(df_google.head(10))
            else:
                st.info("No Google reviews collected this run.")

            st.subheader("Preview - Scraped (top 10)")
            if not df_scraped.empty:
                st.dataframe(df_scraped.head(10))
            else:
                st.info("No scraped reviews found this run.")

            # AI full report generation (structured)
            st.subheader("AI Full Business Report")
            totals = {
                "google_reviews": len(df_google),
                "api_reviews": len(df_api),
                "scraped_reviews": len(df_scraped)
            }
            google_sample = df_google.head(5).to_dict(orient="records") if not df_google.empty else []
            scraped_sample = df_scraped.head(8).to_dict(orient="records") if not df_scraped.empty else []

            ai_prompt_struct = build_ai_prompt_structured(q, domain, whois_info, google_sample, scraped_sample, totals)

            ai_result = None
            if openai_key:
                ai_result = call_openai_for_report(openai_key, ai_prompt_struct)
                if ai_result and "parsed" in ai_result and ai_result["parsed"]:
                    st.success("AI full report generated (structured)")
                    # show parts
                    parsed = ai_result["parsed"]
                    st.markdown("**Executive Summary:**")
                    st.write(parsed.get("executive_summary") or parsed.get("summary") or "")
                    st.markdown("**Overall score:**")
                    st.write(parsed.get("overall_score"))
                else:
                    st.warning("AI returned unstructured or parse-failed output; raw output shown.")
                    st.code(ai_result.get("raw") if isinstance(ai_result, dict) else str(ai_result))
            else:
                st.info("OpenAI key not provided. Generating a basic auto-summary instead.")
                # simple basic non-AI summary
                basic_score = 50
                if totals["google_reviews"] > 5:
                    basic_score += 10
                if totals["scraped_reviews"] > 5:
                    basic_score += 5
                ai_result = {"parsed": {
                    "title": f"Basic Report for {q}",
                    "executive_summary": f"Found {totals['google_reviews']} Google reviews and {totals['scraped_reviews']} scraped reviews. This is a basic non-AI summary.",
                    "overall_score": basic_score,
                    "strengths": ["Public reviews present"],
                    "weaknesses": ["No deep AI analysis without key"],
                    "customer_sentiment": "Mixed - basic heuristics",
                    "red_flags": [],
                    "recommendations": ["Collect more reviews", "Consider paid API for better results"],
                    "next_steps": ["Provide API keys", "Re-run analysis"],
                    "data_summary": totals
                }}

            # Build Excel bytes
            bytes_xlsx = build_excel_bytes(df_google, df_api, df_scraped, ai_result.get("parsed") if isinstance(ai_result, dict) else ai_result)

            if download_when_ready:
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                filename = f"validation_{re.sub(r'[^0-9a-zA-Z_-]', '_', q)[:40]}_{timestamp}.xlsx"
                st.success("Report ready — download below")
                st.download_button(label="Download Excel (4 sheets)", data=bytes_xlsx, file_name=filename,
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.info("Download disabled by option; toggle 'Show download button' if you want to download.")
