#!/usr/bin/env python3
"""
EyeClick Reseller Finder — Web App v2.0
Features: Search · Contact Enrichment · Website Links · Email Editor
          Signature · Gmail/Outlook Integration · Sent Tracking · Follow-up Reminders
Run with:  streamlit run app.py
"""

import re, json, time, io, requests, anthropic, os
import html as html_lib
import urllib.parse
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# ================================================================
# 🔑  API KEYS
# ================================================================
APP_PASSWORD      = st.secrets["APP_PASSWORD"]
ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
SERPER_API_KEY    = st.secrets["SERPER_API_KEY"]
HUNTER_API_KEY    = st.secrets["HUNTER_API_KEY"]

SENT_LOG_FILE         = "sent_log.json"
SEEN_COMPANIES_FILE   = "seen_companies.json"

# ================================================================
# PAGE SETUP
# ================================================================
st.set_page_config(
    page_title = "EyeClick · Reseller Finder",
    page_icon  = "🎯",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

st.markdown("""
<style>
  #MainMenu, footer, header {visibility: hidden;}
  .block-container {padding-top: 2rem;}
  .eyeclick-header {
      background: linear-gradient(135deg, #0057A8 0%, #003d7a 100%);
      padding: 1.8rem 2rem; border-radius: 12px;
      color: white; margin-bottom: 1.8rem;
  }
  .eyeclick-header h1 {margin:0; font-size:2rem; font-weight:700;}
  .eyeclick-header p  {margin:.3rem 0 0; opacity:.85; font-size:1rem;}
  .result-card {
      background:#fff; border:1px solid #dde3ee;
      border-radius:10px; padding:1.1rem 1.3rem;
      margin-bottom:.4rem; box-shadow:0 2px 6px rgba(0,0,0,.06);
  }
  .badge-healthcare    {background:#e8f5e9;color:#2e7d32;border-radius:20px;padding:2px 10px;font-size:.78rem;font-weight:600;}
  .badge-education     {background:#e3f2fd;color:#1565c0;border-radius:20px;padding:2px 10px;font-size:.78rem;font-weight:600;}
  .badge-entertainment {background:#fff3e0;color:#e65100;border-radius:20px;padding:2px 10px;font-size:.78rem;font-weight:600;}
  .score-pill   {display:inline-block;background:#0057A8;color:white;border-radius:20px;padding:2px 10px;font-size:.8rem;font-weight:700;}
  .sent-badge   {display:inline-block;background:#2e7d32;color:white;border-radius:20px;padding:2px 10px;font-size:.78rem;font-weight:600;}
  .reminder-box {background:#fff8e1;border:1px solid #ffb300;border-radius:10px;padding:1rem 1.3rem;margin-bottom:1rem;}
  .stButton>button {
      background:#0057A8;color:white;border:none;border-radius:8px;
      padding:.5rem 1rem;font-size:.95rem;font-weight:600;width:100%;
  }
  .stButton>button:hover {background:#003d7a;}
  div[data-testid="stExpander"] {border:1px solid #e0e6f0;border-radius:8px;margin-bottom:.8rem;}
  .stLinkButton a {background:#0057A8!important;color:white!important;border-radius:8px!important;
      padding:.45rem 1rem!important;font-weight:600!important;font-size:.9rem!important;}
</style>
""", unsafe_allow_html=True)

# ================================================================
# SENT LOG HELPERS
# ================================================================
def load_sent_log() -> list:
    try:
        if os.path.exists(SENT_LOG_FILE):
            with open(SENT_LOG_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []

def append_sent_log(entry: dict):
    log = load_sent_log()
    log.append(entry)
    try:
        with open(SENT_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass

def mark_followup_done(company: str):
    log = load_sent_log()
    for e in log:
        if e.get("company") == company and not e.get("follow_up_done"):
            e["follow_up_done"] = True
    try:
        with open(SENT_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass

def get_due_followups() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    return [e for e in load_sent_log()
            if e.get("follow_up_date","") <= today and not e.get("follow_up_done")]

def already_sent(company_name: str) -> bool:
    return any(e.get("company") == company_name for e in load_sent_log())

# ================================================================
# SEEN COMPANIES  (cross-session deduplication)
# ================================================================
def load_seen_companies() -> list:
    try:
        if os.path.exists(SEEN_COMPANIES_FILE):
            with open(SEEN_COMPANIES_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []

def is_recently_seen(website: str, days: int) -> bool:
    if not website or days == 0:
        return False
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for e in load_seen_companies():
        if (e.get("website","").lower() == website.lower()
                and e.get("date_found","") >= cutoff):
            return True
    return False

def add_to_seen_log(companies: list):
    existing      = load_seen_companies()
    existing_sites = {e.get("website","").lower() for e in existing}
    today         = datetime.now().strftime("%Y-%m-%d")
    for c in companies:
        site = c.get("website","").lower()
        if site and site not in existing_sites:
            existing.append({
                "website"      : c.get("website",""),
                "company_name" : c.get("company_name",""),
                "vertical"     : c.get("vertical",""),
                "date_found"   : today,
            })
            existing_sites.add(site)
    try:
        with open(SEEN_COMPANIES_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

# ================================================================
# PASSWORD GATE
# ================================================================
def login_page():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style='text-align:center;margin-bottom:1.5rem;'>
          <span style='font-size:3rem;'>🎯</span>
          <h2 style='color:#0057A8;margin:.4rem 0 .2rem;'>EyeClick</h2>
          <p style='color:#666;margin:0;'>Reseller Finder · Team Access</p>
        </div>""", unsafe_allow_html=True)
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
# SIDEBAR
# ================================================================
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    # Signature
    st.markdown("**📝 Your Email Signature**")
    if "signature" not in st.session_state:
        st.session_state["signature"] = ""
    new_sig = st.text_area(
        "sig", value=st.session_state["signature"], height=130,
        placeholder="Best regards,\nYour Name\nEyeClick | Business Development\n+1 234 567 8900",
        label_visibility="collapsed",
    )
    if new_sig != st.session_state["signature"]:
        st.session_state["signature"] = new_sig
        st.success("Signature saved!")

    st.markdown("---")
    st.markdown("**🔄 Deduplication Window**")
    st.caption("Skip companies already found within:")
    dedup_days = st.selectbox(
        "dedup", [7, 14, 30, 60, 90, 0],
        index=2,
        format_func=lambda x: f"{x} days" if x > 0 else "Off (show all)",
        label_visibility="collapsed",
        key="dedup_days",
    )

    # Show seen companies count
    seen_total = len(load_seen_companies())
    if seen_total:
        st.caption(f"📋 {seen_total} companies in history log")

    st.markdown("---")

    # Sent History
    st.markdown("## 📬 Sent History")
    sent_log = load_sent_log()
    if sent_log:
        for entry in reversed(sent_log[-15:]):
            done = entry.get("follow_up_done", False)
            icon = "✅" if done else "⏰"
            fu   = entry.get("follow_up_date","")
            st.markdown(
                f"**{entry.get('company','')}**  \n"
                f"📅 {entry.get('sent_date','')}  \n"
                f"{icon} Follow-up: {fu}"
            )
            if not done:
                if st.button("Mark follow-up done", key=f"sb_fu_{entry.get('company','')}"):
                    mark_followup_done(entry.get("company",""))
                    st.rerun()
            st.markdown("---")
    else:
        st.info("No emails sent yet.")

    st.markdown("---")
    if st.sidebar.button("🔓 Sign Out"):
        st.session_state["authenticated"] = False
        st.rerun()
    st.markdown("*EyeClick Reseller Finder v2.0*")

# ================================================================
# HEADER
# ================================================================
st.markdown("""
<div class="eyeclick-header">
  <h1>🎯 EyeClick Reseller Finder</h1>
  <p>AI-powered search · Worldwide reseller discovery · Email outreach with follow-up tracking</p>
</div>
""", unsafe_allow_html=True)

# ================================================================
# FOLLOW-UP REMINDERS BANNER
# ================================================================
due_followups = get_due_followups()
if due_followups:
    names = " · ".join(f"**{e.get('company','')}**" for e in due_followups)
    st.markdown(f"""
    <div class="reminder-box">
      ⏰ <strong>{len(due_followups)} follow-up(s) due today</strong> — {names.replace('**','')}
    </div>
    """, unsafe_allow_html=True)
    with st.expander(f"📋 View {len(due_followups)} due follow-up(s)"):
        for entry in due_followups:
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.markdown(f"**{entry.get('company','')}**  \n{entry.get('email','')}")
            c2.markdown(f"First email: {entry.get('sent_date','')}  \nSubject: *{entry.get('subject','')}*")
            if c3.button("✅ Done", key=f"due_{entry.get('company','')}"):
                mark_followup_done(entry.get("company",""))
                st.rerun()
        st.markdown("---")

# ================================================================
# EYECLICK PROFILE
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
    "🌍  Worldwide"                          : "",
    "🇺🇸  North America"                      : "USA Canada",
    "🇬🇧  Europe"                             : "Europe",
    "🇩🇪  DACH (Germany/Austria/Switzerland)" : "Germany Austria Switzerland",
    "🇫🇷  France & Benelux"                   : "France Belgium Netherlands",
    "🇬🇧  United Kingdom"                     : "United Kingdom",
    "🌏  Asia Pacific"                        : "Asia Pacific",
    "🇦🇺  Australia & New Zealand"            : "Australia New Zealand",
    "🌎  Latin America"                       : "Latin America",
    "🇮🇱  Middle East"                        : "Middle East Israel",
}

# ================================================================
# BACKEND
# ================================================================
@st.cache_resource
def get_anthropic_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def serper_search(query: str, n: int = 6) -> list:
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": n}, timeout=15,
        )
        r.raise_for_status()
        return [{"title": i.get("title",""), "link": i.get("link",""), "snippet": i.get("snippet","")}
                for i in r.json().get("organic", [])]
    except Exception:
        return []

def analyse_companies(client, results: list, vertical: str, query: str, region_label: str) -> list:
    prompt = f"""You are a business development expert for EyeClick finding reseller partners.

{EYECLICK_PROFILE}

Search query: "{query}"  |  Vertical: {vertical}  |  Region: {region_label}

Search results:
{json.dumps(results, indent=2)}

Identify REAL companies (not articles, directories, Wikipedia).
Be GENEROUS — distributors, dealers, suppliers, integrators all qualify. Score fit 1-10.

Return JSON with key "companies" → array of:
{{
  "company_name" : "...",
  "website"      : "full URL including https://",
  "country"      : "...",
  "vertical"     : "{vertical}",
  "description"  : "One sentence: what they sell and to whom.",
  "fit_score"    : <5-10>,
  "fit_reason"   : "Why they could resell EyeClick (2-3 sentences).",
  "contact_role" : "CEO / VP Sales / Managing Director",
  "email_subject": "Compelling outreach subject line",
  "email_body"   : "Personalised 150-200 word outreach email. Sign off as EyeClick Business Development team."
}}

Include all real companies with fit_score >= 5. Return valid JSON only."""
    raw = ""
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
        # Strict C-level / owner priority — Sales Manager and below are last resort
        priority = [
            "Owner", "Co-Founder", "Founder", "CEO", "Chief Executive",
            "President", "Managing Director", "Managing Partner",
            "VP Sales", "VP Business", "Vice President", "Director of Sales",
            "Sales Director", "Commercial Director", "Head of Sales",
            "General Manager", "Country Manager", "Regional Manager",
        ]
        low_level = ["Sales Manager","Account Manager","Sales Representative",
                     "Sales Executive","Business Development Manager","BDM"]
        def score(e):
            pos = (e.get("position") or "").upper()
            # Penalise low-level roles heavily
            for lw in low_level:
                if lw.upper() in pos:
                    return (-1, e.get("confidence",0))
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
        f'site:linkedin.com/in "{company_name}" CEO OR "Managing Director" OR "VP Sales" OR President', 4)
    if not results:
        return {}
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=256,
            messages=[{"role": "user", "content":
                f'From these results about "{company_name}", extract the most senior person.\n'
                f'{json.dumps(results)}\n'
                'Return JSON only: {{"name":"","title":"","linkedin":"https://linkedin.com/in/..."}}'}],
        )
        m = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
        return json.loads(m.group()) if m else {}
    except Exception:
        return {}

def enrich_contact(client, company: dict) -> dict:
    contact = {"name":"","title":"","email":"","confidence":"","linkedin":""}
    h = hunter_search(company.get("website",""))
    if h:
        contact.update({"name": h.get("name",""), "title": h.get("title",""),
                        "email": h.get("email",""),
                        "confidence": f"{h.get('confidence',0)}%" if h.get("confidence") else "",
                        "linkedin": h.get("linkedin","")})
    if not contact["name"] or not contact["linkedin"]:
        li = linkedin_search(client, company.get("company_name",""))
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
               "Email Confidence","LinkedIn","Email Subject","Email Body","Sent?"]
    hfill  = PatternFill(start_color="0057A8", end_color="0057A8", fill_type="solid")
    hfont  = Font(color="FFFFFF", bold=True)
    widths = [11,25,32,14,14,45,9,45,20,20,30,14,35,40,80,8]
    for ci,(h,w) in enumerate(zip(headers,widths),1):
        c = ws.cell(1,ci,h); c.fill=hfill; c.font=hfont
        c.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    vcol = {"Healthcare":"E8F5E9","Education":"E3F2FD","Entertainment":"FFF3E0"}
    sent_companies = {e.get("company") for e in load_sent_log()}
    for r in rows:
        contact = r.get("contact",{})
        ws.append([
            datetime.now().strftime("%Y-%m-%d"),
            r.get("company_name",""), r.get("website",""),
            r.get("country",""), r.get("vertical",""),
            r.get("description",""), r.get("fit_score",""), r.get("fit_reason",""),
            contact.get("name",""), contact.get("title",""),
            contact.get("email",""), contact.get("confidence",""), contact.get("linkedin",""),
            r.get("email_subject",""), r.get("email_body",""),
            "Yes" if r.get("company_name") in sent_companies else "No",
        ])
        ri   = ws.max_row
        fill = PatternFill(start_color=vcol.get(r.get("vertical",""),"FFFFFF"),
                           end_color=vcol.get(r.get("vertical",""),"FFFFFF"), fill_type="solid")
        for ci in range(1,len(headers)+1):
            ws.cell(ri,ci).fill = fill
            ws.cell(ri,ci).alignment = Alignment(vertical="top",wrap_text=True)
        ws.row_dimensions[ri].height = 75
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# ================================================================
# RESULT CARD v2.0
# ================================================================
def result_card(r: dict, idx: int, key_prefix: str = "all"):
    contact          = r.get("contact", {})
    vertical         = r.get("vertical","")
    badge_cls        = f"badge-{vertical.lower()}"
    score            = r.get("fit_score", 0)
    score_color      = "#2e7d32" if score >= 8 else "#e65100" if score >= 6 else "#999"
    company_name_raw = r.get("company_name","")
    website_raw      = r.get("website","")
    linkedin_raw     = contact.get("linkedin","")
    email_raw        = contact.get("email","")
    sent             = already_sent(company_name_raw)

    def e(v): return html_lib.escape(str(v)) if v else ""

    company_name  = e(company_name_raw)
    country       = e(r.get("country",""))
    description   = e(r.get("description",""))
    fit_reason    = e(r.get("fit_reason",""))
    contact_name  = e(contact.get("name","—"))
    contact_title = e(contact.get("title",""))
    confidence    = e(contact.get("confidence",""))

    country_html  = f'&nbsp;<span style="color:#666;font-size:.85rem;">🌐 {country}</span>' if country else ""
    conf_html     = f'<span style="color:#888;font-size:.85rem;">{confidence} confidence</span>' if confidence else ""
    sent_html     = '&nbsp;<span class="sent-badge">✅ Email Sent</span>' if sent else ""
    email_link    = (f'<a href="mailto:{e(email_raw)}" style="color:#0057A8;">{e(email_raw)}</a>'
                     if email_raw else "<em style='color:#999;'>not found</em>")
    website_link  = (f'<a href="{e(website_raw)}" target="_blank" style="color:#0057A8;font-size:.88rem;">'
                     f'🌐 {e(website_raw)}</a>' if website_raw else "")

    # ── Main card ──
    st.markdown(f"""
    <div class="result-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.4rem;">
        <div>
          <strong style="font-size:1.08rem;">{idx}. {company_name}</strong>
          &nbsp;<span class="{badge_cls}">{vertical}</span>
          {country_html}{sent_html}
        </div>
        <span class="score-pill" style="background:{score_color};">{score}/10</span>
      </div>
      {('<div style="margin:.25rem 0 .4rem;">' + website_link + '</div>') if website_link else ''}
      <p style="margin:.4rem 0 .25rem;color:#444;font-size:.92rem;">{description}</p>
      <p style="margin:0;color:#555;font-size:.85rem;"><em>{fit_reason}</em></p>
      <hr style="margin:.55rem 0;border-color:#eee;">
      <div style="display:flex;gap:1.4rem;flex-wrap:wrap;font-size:.9rem;align-items:center;">
        <span>👤 <strong>{contact_name}</strong>{(" · " + contact_title) if contact_title else ""}</span>
        <span>📧 {email_link}</span>
        {conf_html}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── LinkedIn + action row ──
    has_linkedin = linkedin_raw and linkedin_raw.startswith("http")
    if has_linkedin:
        st.markdown(f"&nbsp;&nbsp;&nbsp;[🔗 LinkedIn Profile]({linkedin_raw})", unsafe_allow_html=True)

    # ── Email editor expander ──
    email_label = "✉️  Edit & Send Email" + (" — ✅ Sent" if sent else "")
    with st.expander(f"{email_label} · {company_name_raw}"):

        # Subject
        subj_key  = f"subj_{key_prefix}_{hash(website_raw)}"
        if subj_key not in st.session_state:
            st.session_state[subj_key] = r.get("email_subject","")
        subject = st.text_input("Subject line", key=subj_key)

        # Body — draft only, NO signature baked in (signature added live below)
        body_key = f"body_{key_prefix}_{hash(website_raw)}"
        if body_key not in st.session_state:
            st.session_state[body_key] = r.get("email_body","")
        body = st.text_area("Email body (fully editable)", key=body_key, height=220)

        # Signature — always reflects current sidebar value, never baked into body
        sig = st.session_state.get("signature","")
        if sig:
            st.markdown("**✍️ Signature** *(edit in Settings panel)*")
            st.code(sig, language=None)
        else:
            st.caption("💡 Add your signature in the ⚙️ **Settings** panel on the left — it will appear here automatically.")

        # Full email = body + signature (combined only for sending)
        full_email = body + ("\n\n" + sig if sig else "")

        # ── 3 action buttons ──
        a1, a2, a3 = st.columns(3)

        # Open in email client (mailto)
        if email_raw:
            mailto = ("mailto:" + email_raw
                      + "?subject=" + urllib.parse.quote(subject)
                      + "&body="    + urllib.parse.quote(full_email))
            a1.link_button("📨 Open in Email Client", mailto, use_container_width=True)
        else:
            a1.info("No email found")

        # Mark as sent + set follow-up
        if not sent:
            if a2.button("✅ Mark as Sent + Reminder", key=f"mark_{key_prefix}_{hash(website_raw)}", use_container_width=True):
                fu_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
                append_sent_log({
                    "company"        : company_name_raw,
                    "website"        : website_raw,
                    "email"          : email_raw,
                    "subject"        : subject,
                    "sent_date"      : datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "follow_up_date" : fu_date,
                    "follow_up_done" : False,
                })
                st.success(f"✅ Logged! Follow-up reminder set for **{fu_date}**")
                st.rerun()
        else:
            a2.success("✅ Already sent")

        # Visit LinkedIn
        if has_linkedin:
            a3.link_button("👁 Visit LinkedIn", linkedin_raw, use_container_width=True)

        # Follow-up email (if already sent)
        if sent:
            st.markdown("---")
            st.markdown("**🔄 Send Follow-up Email**")
            fu_subj_key = f"fu_subj_{key_prefix}_{hash(website_raw)}"
            fu_body_key = f"fu_body_{key_prefix}_{hash(website_raw)}"
            if fu_subj_key not in st.session_state:
                st.session_state[fu_subj_key] = f"Following up: {subject}"
            if fu_body_key not in st.session_state:
                sig = st.session_state.get("signature","")
                st.session_state[fu_body_key] = (
                    f"Hi {contact.get('name','').split()[0] if contact.get('name') else 'there'},\n\n"
                    f"I wanted to follow up on my previous message regarding EyeClick's interactive "
                    f"projection systems. Did you get a chance to review it?\n\n"
                    f"I'd love to schedule a quick 15-minute call to explore if there's a potential "
                    f"fit for a reseller partnership.\n\n"
                    f"Looking forward to hearing from you.\n\n"
                    + (sig or "EyeClick Business Development Team")
                )
            fu_subj = st.text_input("Follow-up subject", key=fu_subj_key)
            fu_body = st.text_area("Follow-up body", key=fu_body_key, height=200)
            if email_raw:
                fu_mailto = ("mailto:" + email_raw
                             + "?subject=" + urllib.parse.quote(fu_subj)
                             + "&body="    + urllib.parse.quote(fu_body))
                b1, b2 = st.columns(2)
                b1.link_button("📨 Open Follow-up in Email Client", fu_mailto, use_container_width=True)
                if b2.button("✅ Mark Follow-up Sent", key=f"fu_done_{key_prefix}_{hash(website_raw)}", use_container_width=True):
                    mark_followup_done(company_name_raw)
                    st.success("Follow-up marked as done!")
                    st.rerun()

# ================================================================
# SEARCH FORM
# ================================================================
with st.container():
    col1, col2, col3, col4 = st.columns([2, 2, 1.2, 1])
    with col1:
        st.markdown("**Vertical (market segment)**")
        sel_h = st.checkbox("🏥 Healthcare",    value=True)
        sel_e = st.checkbox("🏫 Education",     value=True)
        sel_n = st.checkbox("🎯 Entertainment", value=False)
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

selected_verticals = (["Healthcare"] if sel_h else []) + \
                     (["Education"]  if sel_e else []) + \
                     (["Entertainment"] if sel_n else [])

st.markdown("---")

# ================================================================
# SEARCH LOGIC
# ================================================================
if search_clicked:
    if not selected_verticals:
        st.warning("Please select at least one vertical.")
        st.stop()

    import itertools
    client       = get_anthropic_client()
    all_companies: list = []
    seen_sites  : set  = set()
    today        = datetime.now().strftime("%Y-%m-%d")
    status_box   = st.empty()
    progress_bar = st.progress(0)
    log_box      = st.empty()
    log_lines: list = []

    v_cycle = itertools.cycle(selected_verticals)
    q_pool  = {v: [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
               for v in selected_verticals}
    attempt = 0

    while len(all_companies) < num_results and attempt < 40:
        v = next(v_cycle)
        if not q_pool[v]:
            q_pool[v] = [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
        query = q_pool[v].pop(0)
        attempt += 1
        pct = min(int((len(all_companies) / num_results) * 70), 70)
        progress_bar.progress(pct)
        status_box.info(f"🔍 Searching ({v}): *{query}* — {len(all_companies)}/{num_results} found…")
        results   = serper_search(query, 6)
        if not results:
            continue
        companies = analyse_companies(client, results, v, query, region_label)
        dedup     = st.session_state.get("dedup_days", 30)
        new       = [c for c in companies
                     if c.get("website","") not in seen_sites
                     and not is_recently_seen(c.get("website",""), dedup)]
        for c in new:
            seen_sites.add(c.get("website",""))
        all_companies.extend(new)
        log_lines.append(f"✅ {v} · {len(new)} co. — `{query}`")
        log_box.markdown("\n".join(log_lines[-6:]))
        time.sleep(0.8)

    final = all_companies[:num_results]
    status_box.info(f"📇 Enriching contacts for {len(final)} companies…")
    for i, company in enumerate(final):
        progress_bar.progress(70 + int((i / max(len(final),1)) * 28))
        status_box.info(f"📇 Finding contact: **{company.get('company_name','')}** ({i+1}/{len(final)})…")
        company["contact"] = enrich_contact(client, company)
        time.sleep(0.6)

    progress_bar.progress(100)
    status_box.success(f"✅ Done! **{len(final)} reseller candidates** found with contact details.")
    log_box.empty()

    # Save to seen-companies log so future searches skip these
    add_to_seen_log(final)

    # Store results in session so they survive reruns (e.g. mark-as-sent buttons)
    st.session_state["last_results"] = final
    st.session_state["last_date"]    = today
    st.session_state["last_region"]  = region_label

# ================================================================
# DISPLAY RESULTS (from session state — survives reruns)
# ================================================================
final = st.session_state.get("last_results")
if final:
    today        = st.session_state.get("last_date", datetime.now().strftime("%Y-%m-%d"))
    region_label = st.session_state.get("last_region","")

    st.markdown(f"## Results · {region_label.strip()} · {today}")
    tabs   = st.tabs(["📋 All Results", "🏥 Healthcare", "🏫 Education", "🎯 Entertainment"])
    groups = {"Healthcare":[], "Education":[], "Entertainment":[]}
    for r in final:
        groups.get(r.get("vertical",""), []).append(r)

    with tabs[0]:
        for i, r in enumerate(final, 1):
            result_card(r, i, key_prefix="all")

    for tab, vertical in zip(tabs[1:], ["Healthcare","Education","Entertainment"]):
        with tab:
            vlist = groups[vertical]
            if vlist:
                for i, r in enumerate(vlist, 1):
                    result_card(r, i, key_prefix=vertical.lower())
            else:
                st.info(f"No {vertical} companies found in this search.")

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
    <div style='text-align:center;padding:3rem;color:#888;'>
      <span style='font-size:3rem;'>🔍</span>
      <p style='font-size:1.1rem;margin-top:1rem;'>
        Select your verticals and region above, then hit <strong>SEARCH</strong><br>
        to discover ideal EyeClick reseller partners worldwide.
      </p>
    </div>
    """, unsafe_allow_html=True)
