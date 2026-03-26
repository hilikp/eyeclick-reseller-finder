#!/usr/bin/env python3
"""
EyeClick Reseller Finder — Web App  (app.py)
Run with:  streamlit run app.py
"""

import re, json, time, io, requests, anthropic
import html as html_lib
import streamlit as st
import pandas as pd
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# ================================================================
# 🔑  API KEYS — loaded securely from .streamlit/secrets.toml
#     (locally) or Streamlit Cloud Secrets (when deployed)
# ================================================================
APP_PASSWORD      = st.secrets["APP_PASSWORD"]
ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
SERPER_API_KEY    = st.secrets["SERPER_API_KEY"]
HUNTER_API_KEY    = st.secrets["HUNTER_API_KEY"]

# ================================================================
# PAGE SETUP
# ================================================================
st.set_page_config(
    page_title = "EyeClick · Reseller Finder",
    page_icon  = "🎯",
    layout     = "wide",
    initial_sidebar_state = "collapsed",
)

st.markdown("""
<style>
  #MainMenu, footer, header {visibility: hidden;}
  .block-container {padding-top: 2rem;}
  .eyeclick-header {
      background: linear-gradient(135deg, #0057A8 0%, #003d7a 100%);
      padding: 1.8rem 2rem;
      border-radius: 12px;
      color: white;
      margin-bottom: 1.8rem;
  }
  .eyeclick-header h1 {margin:0; font-size:2rem; font-weight:700;}
  .eyeclick-header p  {margin:.3rem 0 0; opacity:.85; font-size:1rem;}
  .result-card {
      background:#fff;
      border:1px solid #dde3ee;
      border-radius:10px;
      padding:1.1rem 1.3rem;
      margin-bottom:.8rem;
      box-shadow: 0 2px 6px rgba(0,0,0,.06);
  }
  .badge-healthcare    {background:#e8f5e9; color:#2e7d32; border-radius:20px; padding:2px 10px; font-size:.78rem; font-weight:600;}
  .badge-education     {background:#e3f2fd; color:#1565c0; border-radius:20px; padding:2px 10px; font-size:.78rem; font-weight:600;}
  .badge-entertainment {background:#fff3e0; color:#e65100; border-radius:20px; padding:2px 10px; font-size:.78rem; font-weight:600;}
  .score-pill {
      display:inline-block;
      background:#0057A8; color:white;
      border-radius:20px; padding:2px 10px;
      font-size:.8rem; font-weight:700;
  }
  .stButton>button {
      background:#0057A8; color:white;
      border:none; border-radius:8px;
      padding:.6rem 2.2rem; font-size:1.05rem; font-weight:600;
      width:100%;
  }
  .stButton>button:hover {background:#003d7a;}
  div[data-testid="stExpander"] {border:1px solid #e0e6f0; border-radius:8px;}
</style>
""", unsafe_allow_html=True)

# ================================================================
# PASSWORD GATE
# ================================================================
def login_page():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style='text-align:center; margin-bottom:1.5rem;'>
          <span style='font-size:3rem;'>🎯</span>
          <h2 style='color:#0057A8; margin:.4rem 0 .2rem;'>EyeClick</h2>
          <p style='color:#666; margin:0;'>Reseller Finder · Team Access</p>
        </div>
        """, unsafe_allow_html=True)
        pwd = st.text_input("Password", type="password", placeholder="Enter team password")
        if st.button("Sign In", use_container_width=True):
            if pwd == APP_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")

if not st.session_state.get("authenticated"):
    login_page()
    st.stop()

# ================================================================
# EYECLICK COMPANY PROFILE
# ================================================================
EYECLICK_PROFILE = """
Company: EyeClick (eyeclick.com)
Product: Interactive projection systems — projects games & activities onto floors/walls.
Sales model: Sold exclusively through resellers / distributors worldwide.

VERTICALS & IDEAL RESELLERS
HEALTHCARE  → rehab centres, senior/assisted-living, memory care, hospital waiting rooms.
  Ideal resellers: medical/rehab equipment distributors, occupational-therapy suppliers.
EDUCATION   → K-12, elementary, early-education, preschools, special-education.
  Ideal resellers: EdTech companies, school AV/furniture suppliers, playground distributors.
ENTERTAINMENT → trampoline parks, FECs, QSRs with play areas, indoor playgrounds.
  Ideal resellers: amusement/FEC equipment suppliers, entertainment technology companies.
"""

# ================================================================
# SEARCH QUERY TEMPLATES  (region appended dynamically)
# ================================================================
QUERY_TEMPLATES = {
    "Healthcare": [
        "rehabilitation equipment distributor company {region}",
        "senior care activity products supplier company {region}",
        "occupational therapy equipment reseller {region}",
        "physical therapy clinic equipment supplier {region}",
        "assistive technology healthcare distributor {region}",
    ],
    "Education": [
        "educational technology reseller K12 schools {region}",
        "special education equipment supplier distributor {region}",
        "early childhood education equipment company {region}",
        "school interactive AV equipment distributor {region}",
        "EdTech reseller company elementary schools {region}",
    ],
    "Entertainment": [
        "trampoline park equipment supplier company {region}",
        "family entertainment center FEC equipment distributor {region}",
        "indoor playground equipment manufacturer supplier {region}",
        "amusement equipment distributor company {region}",
        "QSR restaurant play area interactive equipment {region}",
    ],
}

REGIONS = {
    "🌍  Worldwide"             : "",
    "🇺🇸  North America"         : "USA Canada",
    "🇬🇧  Europe"                : "Europe",
    "🇩🇪  DACH (Germany/Austria/Switzerland)" : "Germany Austria Switzerland",
    "🇫🇷  France & Benelux"      : "France Belgium Netherlands",
    "🇬🇧  United Kingdom"        : "United Kingdom",
    "🌏  Asia Pacific"           : "Asia Pacific",
    "🇦🇺  Australia & New Zealand": "Australia New Zealand",
    "🌎  Latin America"          : "Latin America",
    "🇮🇱  Middle East"           : "Middle East Israel",
}

# ================================================================
# BACKEND FUNCTIONS
# ================================================================
@st.cache_resource
def get_anthropic_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def serper_search(query: str, n: int = 6) -> list:
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": n},
            timeout=15,
        )
        r.raise_for_status()
        return [{"title": i.get("title",""), "link": i.get("link",""), "snippet": i.get("snippet","")}
                for i in r.json().get("organic", [])]
    except Exception as e:
        return []

def analyse_companies(client, results: list, vertical: str, query: str, region_label: str) -> list:
    prompt = f"""You are a business development expert for EyeClick finding reseller partners.

{EYECLICK_PROFILE}

Search query: "{query}"  |  Vertical: {vertical}  |  Region focus: {region_label}

Search results:
{json.dumps(results, indent=2)}

Identify REAL companies (not articles, directories, or Wikipedia).
Be GENEROUS — distributors, dealers, suppliers, integrators all qualify.
Score fit 1-10. Include every real company scoring 5+.

Return JSON object with key "companies" → array of:
{{
  "company_name" : "...",
  "website"      : "...",
  "country"      : "...",
  "vertical"     : "{vertical}",
  "description"  : "One sentence: what they sell and to whom.",
  "fit_score"    : <5-10>,
  "fit_reason"   : "Why they could resell EyeClick.",
  "contact_role" : "CEO / VP Sales / Managing Director / etc.",
  "email_subject": "Compelling subject line",
  "email_body"   : "Personalised outreach email 150-200 words, sign off as EyeClick Business Development team."
}}

Return valid JSON only."""
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw  = resp.content[0].text.strip()
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        for v in data.values():
            if isinstance(v, list):
                return v
        return []
    except Exception:
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
                for v in data.values():
                    if isinstance(v, list):
                        return v
        except Exception:
            pass
        return []

def hunter_search(domain: str) -> dict:
    domain = re.sub(r"https?://(www\.)?", "", domain).strip("/").split("/")[0]
    if not domain:
        return {}
    try:
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 10},
            timeout=15,
        )
        r.raise_for_status()
        emails = r.json().get("data", {}).get("emails", [])
        if not emails:
            return {}
        priority = ["CEO","Chief Executive","President","Managing Director",
                    "Founder","VP Sales","Vice President"]
        def score(e):
            pos = (e.get("position") or "").upper()
            for i, kw in enumerate(priority):
                if kw.upper() in pos:
                    return (len(priority)-i, e.get("confidence",0))
            return (0, e.get("confidence",0))
        best = sorted(emails, key=score, reverse=True)[0]
        return {
            "name"      : f"{best.get('first_name','')} {best.get('last_name','')}".strip(),
            "title"     : best.get("position",""),
            "email"     : best.get("value",""),
            "confidence": best.get("confidence",0),
            "linkedin"  : best.get("linkedin",""),
        }
    except Exception:
        return {}

def linkedin_search(client, company_name: str) -> dict:
    results = serper_search(
        f'site:linkedin.com/in "{company_name}" CEO OR "Managing Director" OR "VP Sales" OR President', 4
    )
    if not results:
        return {}
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content":
                f'From these results about "{company_name}", extract the most senior person.\n'
                f'{json.dumps(results)}\n'
                'Return JSON: {{"name":"","title":"","linkedin":"https://linkedin.com/in/..."}}'}],
        )
        m = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
        return json.loads(m.group()) if m else {}
    except Exception:
        return {}

def enrich_contact(client, company: dict) -> dict:
    website = company.get("website","")
    name    = company.get("company_name","")
    contact = {"name":"","title":"","email":"","confidence":"","linkedin":""}

    # Hunter.io first
    h = hunter_search(website)
    if h:
        contact.update({"name": h.get("name",""), "title": h.get("title",""),
                        "email": h.get("email",""),
                        "confidence": f"{h.get('confidence',0)}%" if h.get("confidence") else "",
                        "linkedin": h.get("linkedin","")})

    # Fill missing via LinkedIn search
    if not contact["name"] or not contact["linkedin"]:
        li = linkedin_search(client, name)
        if li:
            if not contact["name"]:
                contact["name"]  = li.get("name","")
                contact["title"] = li.get("title","")
            if not contact["linkedin"]:
                contact["linkedin"] = li.get("linkedin","")

    return contact

# ================================================================
# EXCEL EXPORT
# ================================================================
def build_excel(rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Reseller Prospects"
    headers = ["Date","Company","Website","Country","Vertical","Description",
               "Fit Score","Fit Reason","Contact Name","Title","Email",
               "Email Confidence","LinkedIn","Email Subject","Email Body"]
    hfill = PatternFill(start_color="0057A8", end_color="0057A8", fill_type="solid")
    hfont = Font(color="FFFFFF", bold=True)
    widths = [11,25,30,14,14,45,9,40,20,20,30,14,35,40,80]
    for ci, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(1, ci, h)
        c.fill = hfill; c.font = hfont
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    vcol = {"Healthcare":"E8F5E9","Education":"E3F2FD","Entertainment":"FFF3E0"}
    for r in rows:
        contact = r.get("contact",{})
        row_data = [
            datetime.now().strftime("%Y-%m-%d"),
            r.get("company_name",""), r.get("website",""),
            r.get("country",""), r.get("vertical",""),
            r.get("description",""), r.get("fit_score",""),
            r.get("fit_reason",""),
            contact.get("name",""), contact.get("title",""),
            contact.get("email",""), contact.get("confidence",""),
            contact.get("linkedin",""),
            r.get("email_subject",""), r.get("email_body",""),
        ]
        ws.append(row_data)
        ri   = ws.max_row
        fill = PatternFill(start_color=vcol.get(r.get("vertical",""),"FFFFFF"),
                           end_color=vcol.get(r.get("vertical",""),"FFFFFF"), fill_type="solid")
        for ci in range(1, len(headers)+1):
            ws.cell(ri, ci).fill = fill
            ws.cell(ri, ci).alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[ri].height = 75

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# ================================================================
# RESULT CARD
# ================================================================
def result_card(r: dict, idx: int):
    contact   = r.get("contact", {})
    vertical  = r.get("vertical","")
    badge_cls = f"badge-{vertical.lower()}"
    score     = r.get("fit_score", 0)
    score_color = "#2e7d32" if score >= 8 else "#e65100" if score >= 6 else "#999"

    # Escape all text values so special characters never break the HTML
    def e(v): return html_lib.escape(str(v)) if v else ""

    company_name  = e(r.get("company_name",""))
    country       = e(r.get("country",""))
    description   = e(r.get("description",""))
    fit_reason    = e(r.get("fit_reason",""))
    contact_name  = e(contact.get("name","—"))
    contact_title = e(contact.get("title",""))
    confidence    = e(contact.get("confidence",""))
    email_raw     = contact.get("email","")
    linkedin_raw  = contact.get("linkedin","")

    email_html = (f'<a href="mailto:{e(email_raw)}" style="color:#0057A8;">{e(email_raw)}</a>'
                  if email_raw else "—")
    has_linkedin = linkedin_raw and linkedin_raw.startswith("http")
    country_html  = (f'&nbsp;<span style="color:#666;font-size:.85rem;">🌐 {country}</span>'
                     if country else "")
    conf_html     = (f'<span style="color:#888;">{confidence} confidence</span>'
                     if confidence else "")

    st.markdown(f"""
    <div class="result-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.5rem;">
        <div>
          <strong style="font-size:1.08rem;">{idx}. {company_name}</strong>
          &nbsp;<span class="{badge_cls}">{vertical}</span>
          {country_html}
        </div>
        <span class="score-pill" style="background:{score_color};">{score}/10</span>
      </div>
      <p style="margin:.5rem 0 .3rem;color:#444;font-size:.92rem;">{description}</p>
      <p style="margin:0;color:#666;font-size:.85rem;"><em>{fit_reason}</em></p>
      <hr style="margin:.6rem 0;border-color:#eee;">
      <div style="display:flex;gap:1.5rem;flex-wrap:wrap;font-size:.9rem;align-items:center;">
        <span>👤 <strong>{contact_name}</strong>{(' · ' + contact_title) if contact_title else ''}</span>
        <span>📧 {email_html}</span>
        {conf_html}
      </div>
    </div>
    """, unsafe_allow_html=True)

    if has_linkedin:
        st.markdown(f'&nbsp;&nbsp;&nbsp;[🔗 LinkedIn]({linkedin_raw})', unsafe_allow_html=True)

    with st.expander(f"✉️  View draft email for {r.get('company_name','')}"):
        st.markdown(f"**Subject:** {r.get('email_subject','')}")
        st.markdown("---")
        st.write(r.get("email_body",""))

# ================================================================
# MAIN APP
# ================================================================
st.markdown("""
<div class="eyeclick-header">
  <h1>🎯 EyeClick Reseller Finder</h1>
  <p>AI-powered search · Find ideal reseller partners worldwide · Draft outreach emails instantly</p>
</div>
""", unsafe_allow_html=True)

# ---- SEARCH FORM ----
with st.container():
    col1, col2, col3, col4 = st.columns([2, 2, 1.2, 1])

    with col1:
        st.markdown("**Vertical (market segment)**")
        sel_healthcare    = st.checkbox("🏥 Healthcare",    value=True)
        sel_education     = st.checkbox("🏫 Education",     value=True)
        sel_entertainment = st.checkbox("🎯 Entertainment", value=False)

    with col2:
        st.markdown("**Region**")
        region_label = st.selectbox("", list(REGIONS.keys()), label_visibility="collapsed")
        region_kw    = REGIONS[region_label]

    with col3:
        st.markdown("**Number of results**")
        num_results = st.slider("", min_value=5, max_value=30, value=10, step=5,
                                label_visibility="collapsed")

    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button("🔍  SEARCH", use_container_width=True)

selected_verticals = []
if sel_healthcare:    selected_verticals.append("Healthcare")
if sel_education:     selected_verticals.append("Education")
if sel_entertainment: selected_verticals.append("Entertainment")

st.markdown("---")

# ---- SEARCH LOGIC ----
if search_clicked:
    if not selected_verticals:
        st.warning("Please select at least one vertical.")
        st.stop()

    client       = get_anthropic_client()
    all_companies: list = []
    seen_sites  : set  = set()
    today        = datetime.now().strftime("%Y-%m-%d")

    status_box  = st.empty()
    progress_bar = st.progress(0)
    log_box      = st.empty()

    # Build query pool
    import itertools
    v_cycle = itertools.cycle(selected_verticals)
    q_pool  = {v: [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
               for v in selected_verticals}
    attempts = total_queries = sum(len(q_pool[v]) for v in selected_verticals)
    attempt  = 0

    log_lines: list = []

    while len(all_companies) < num_results and attempt < 40:
        v     = next(v_cycle)
        if not q_pool[v]:
            q_pool[v] = [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
        query = q_pool[v].pop(0)
        attempt += 1

        pct = min(int((len(all_companies) / num_results) * 70), 70)
        progress_bar.progress(pct)
        status_box.info(f"🔍 Searching ({v}): *{query}* — found {len(all_companies)}/{num_results} so far…")

        results   = serper_search(query, 6)
        if not results:
            continue
        companies = analyse_companies(client, results, v, query, region_label)
        new       = [c for c in companies if c.get("website","") not in seen_sites]
        for c in new:
            seen_sites.add(c.get("website",""))
        all_companies.extend(new)
        log_lines.append(f"✅ {v} · {len(new)} companies — `{query}`")
        log_box.markdown("\n".join(log_lines[-6:]))
        time.sleep(0.8)

    # ---- ENRICHMENT ----
    final = all_companies[:num_results]
    status_box.info(f"📇 Enriching contacts for {len(final)} companies…")

    for i, company in enumerate(final):
        pct = 70 + int((i / len(final)) * 28)
        progress_bar.progress(pct)
        status_box.info(f"📇 Finding contact: **{company.get('company_name','')}** ({i+1}/{len(final)})…")
        company["contact"] = enrich_contact(client, company)
        time.sleep(0.6)

    progress_bar.progress(100)
    status_box.success(f"✅ Done! Found **{len(final)} reseller candidates** with contact details.")
    log_box.empty()

    # ---- RESULTS ----
    st.markdown(f"## Results · {region_label.strip()} · {today}")

    tabs = st.tabs(["📋 All Results", "🏥 Healthcare", "🏫 Education", "🎯 Entertainment"])
    groups = {"Healthcare":[], "Education":[], "Entertainment":[]}
    for r in final:
        groups.get(r.get("vertical",""), []).append(r)

    with tabs[0]:
        for i, r in enumerate(final, 1):
            result_card(r, i)

    for tab, vertical in zip(tabs[1:], ["Healthcare","Education","Entertainment"]):
        with tab:
            vlist = groups[vertical]
            if vlist:
                for i, r in enumerate(vlist, 1):
                    result_card(r, i)
            else:
                st.info(f"No {vertical} companies found in this search.")

    # ---- DOWNLOAD ----
    st.markdown("---")
    excel_bytes = build_excel(final)
    st.download_button(
        label     = "⬇️  Download Full Excel Report",
        data      = excel_bytes,
        file_name = f"eyeclick_resellers_{today}.xlsx",
        mime      = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width = True,
    )

else:
    st.markdown("""
    <div style='text-align:center; padding:3rem; color:#888;'>
        <span style='font-size:3rem;'>🔍</span>
        <p style='font-size:1.1rem; margin-top:1rem;'>
            Select your verticals and region above, then hit <strong>SEARCH</strong><br>
            to discover ideal EyeClick reseller partners worldwide.
        </p>
    </div>
    """, unsafe_allow_html=True)

# Logout
st.sidebar.markdown("---")
if st.sidebar.button("🔓 Sign Out"):
    st.session_state["authenticated"] = False
    st.rerun()
st.sidebar.markdown(f"*EyeClick Reseller Finder v1.0*")
