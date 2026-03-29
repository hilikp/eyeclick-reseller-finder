#!/usr/bin/env python3
"""
EyeClick Reseller Finder — Web App v2.9
Features: Search · Contact Enrichment · Website Links · Email Editor
          Signature · Gmail/Outlook Integration · Sent Tracking · Follow-up Reminders
Run with:  streamlit run app.py
"""

import re, json, time, io, requests, anthropic, os, base64
import html as html_lib
import urllib.parse
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# ================================================================
# LOGO HELPER  — loads local file as base64; falls back to CDN
# ================================================================
def _logo_img_tag(dark_bg: bool = True) -> str:
    """Return an <img> tag for the EyeClick logo.
    Tries eyeclick_logo.png in the app folder first (works on Cloud too if
    committed); falls back to the official CDN URL."""
    local = os.path.join(os.path.dirname(__file__), "eyeclick_logo.png")
    if os.path.exists(local):
        with open(local, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        src = f"data:image/png;base64,{b64}"
    else:
        src = ("https://cdn.eyeclick.com/logo-light.png" if dark_bg
               else "https://cdn.eyeclick.com/logo-dark.png")
    height = "38px" if dark_bg else "42px"
    return f'<img src="{src}" style="height:{height};object-fit:contain;" alt="EyeClick">'

# ================================================================
# 🔑  API KEYS
# ================================================================
APP_PASSWORD      = st.secrets["APP_PASSWORD"]
ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
SERPER_API_KEY    = st.secrets["SERPER_API_KEY"]
HUNTER_API_KEY    = st.secrets["HUNTER_API_KEY"]

SENT_LOG_FILE         = "sent_log.json"
SEEN_COMPANIES_FILE   = "seen_companies.json"
FEEDBACK_LOG_FILE     = "feedback_log.json"

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
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  html, body, [class*="css"], [data-testid] {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  }
  #MainMenu, footer, header {visibility: hidden;}
  .block-container {padding-top: 1.5rem !important;}

  /* ── Page background ── */
  [data-testid="stAppViewContainer"] > .main {background: #F5F7F9;}

  /* ── Main header bar ── */
  .ec-header {
      background: linear-gradient(135deg, #101820 0%, #1a1030 100%);
      padding: 1.2rem 1.8rem; border-radius: 14px;
      margin-bottom: 1.6rem;
      display: flex; align-items: center; gap: 1.4rem;
      box-shadow: 0 6px 28px rgba(16,24,32,0.28),
                  0 -2px 0 0 #FF6B9D inset,
                  inset 4px 0 0 0 #CC44DD;
  }
  .ec-header img  {height: 38px; object-fit: contain; flex-shrink: 0;}
  .ec-header-text {line-height: 1.3;}
  .ec-header-text .title {
      font-size: 1.15rem; font-weight: 700; color: #fff; letter-spacing: -.01em;
  }
  .ec-header-text .sub   {font-size: .82rem; color: rgba(255,255,255,.50); margin-top:.15rem;}

  /* ── Result card ── */
  .result-card {
      background: #fff;
      border: 1px solid rgba(16,24,32,0.08);
      border-left: 4px solid #CC44DD;
      border-radius: 12px; padding: 1.1rem 1.4rem;
      margin-bottom: .5rem;
      box-shadow: 0 2px 10px rgba(204,68,221,0.07);
  }

  /* ── Vertical badges ── */
  .badge-seniors       {background:#fce4ec;color:#c2185b;border-radius:20px;padding:2px 10px;font-size:.74rem;font-weight:600;}
  .badge-education     {background:#EEEEF9;color:#5B5CD6;border-radius:20px;padding:2px 10px;font-size:.74rem;font-weight:600;}
  .badge-entertainment {background:#fff3e0;color:#e65100;border-radius:20px;padding:2px 10px;font-size:.74rem;font-weight:600;}
  .badge-healthcare    {background:#e8f5e9;color:#2e7d32;border-radius:20px;padding:2px 10px;font-size:.74rem;font-weight:600;}

  /* ── Score / sent pills ── */
  .score-pill {display:inline-block;background:#5B5CD6;color:#fff;border-radius:20px;padding:2px 11px;font-size:.8rem;font-weight:700;}
  .sent-badge {display:inline-block;background:#1b8a4a;color:#fff;border-radius:20px;padding:2px 10px;font-size:.74rem;font-weight:600;}

  /* ── Follow-up reminder banner ── */
  .reminder-box {
      background:#EEEEF9; border:1px solid #5B5CD6;
      border-left:4px solid #5B5CD6;
      border-radius:10px; padding:.9rem 1.2rem; margin-bottom:1rem;
  }

  /* ── Buttons — pill shape matching eyeclick.com CTAs ── */
  .stButton>button {
      background: #5B5CD6 !important; color: #fff !important;
      border: none !important; border-radius: 200px !important;
      padding: .48rem 1.2rem !important; font-size: .9rem !important;
      font-weight: 600 !important; width: 100% !important;
      letter-spacing: .01em !important;
      transition: background .18s ease, transform .1s ease !important;
  }
  .stButton>button:hover  {background: #4748C4 !important;}
  .stButton>button:active {transform: scale(.97) !important;}

  /* ── Link buttons ── */
  .stLinkButton a {
      background: #5B5CD6 !important; color: #fff !important;
      border-radius: 200px !important; padding: .44rem 1.1rem !important;
      font-weight: 600 !important; font-size: .88rem !important;
      border: none !important; text-decoration: none !important;
      transition: background .18s ease !important;
  }
  .stLinkButton a:hover {background: #4748C4 !important;}

  /* ── Expanders ── */
  div[data-testid="stExpander"] {
      border: 1px solid rgba(16,24,32,0.09) !important;
      border-radius: 10px !important; margin-bottom: .7rem !important;
  }
  div[data-testid="stExpander"] summary {
      font-weight: 500 !important;
  }

  /* ── Metric tiles ── */
  [data-testid="metric-container"] {
      background: #fff !important;
      border: 1px solid rgba(16,24,32,0.08) !important;
      border-radius: 10px !important;
  }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {border-right: 1px solid rgba(16,24,32,0.08);}
  [data-testid="stSidebar"] .stButton>button {border-radius:200px !important;}
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
# FEEDBACK LOG  (user-reported issues)
# ================================================================
def load_feedback_log() -> list:
    try:
        if os.path.exists(FEEDBACK_LOG_FILE):
            with open(FEEDBACK_LOG_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_feedback(company_name: str, website: str, reason_code: str):
    """Save user feedback. reason_code: 'details' | 'linkedin' | 'industry'"""
    log = load_feedback_log()
    log.append({
        "company_name": company_name,
        "website"     : website,
        "reason"      : reason_code,
        "date"        : datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    try:
        with open(FEEDBACK_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass

def is_flagged_wrong_industry(website: str) -> bool:
    """True if this site was previously flagged as wrong industry by a user."""
    if not website:
        return False
    return any(
        e.get("website","").lower() == website.lower() and e.get("reason") == "industry"
        for e in load_feedback_log()
    )

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
        st.markdown(f"""
        <div style='text-align:center;margin-bottom:1.8rem;'>
          <div style='background:#101820;display:inline-block;padding:1rem 2rem;
                      border-radius:14px;margin-bottom:1rem;'>
            {_logo_img_tag(dark_bg=True)}
          </div>
          <p style='color:#717171;margin:0;font-size:.95rem;'>Reseller Finder &nbsp;·&nbsp; Team Access</p>
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
    st.markdown(f"""
    <div style='background:#101820;border-radius:10px;padding:.7rem 1rem;
                margin-bottom:1.2rem;text-align:center;'>
      {_logo_img_tag(dark_bg=True)}
    </div>""", unsafe_allow_html=True)
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
    st.markdown("**🚫 Blocked Territories**")
    st.caption("Hard-coded: Israel (ALL) · Canada (Seniors)")
    if "extra_blocked" not in st.session_state:
        st.session_state["extra_blocked"] = []
    new_block_country  = st.text_input("Country to block", placeholder="e.g. Germany", key="nb_country")
    new_block_vertical = st.selectbox("Vertical to block", ["ALL","Seniors","Education","Entertainment"], key="nb_vertical")
    if st.button("➕ Add Block", use_container_width=True):
        if new_block_country.strip():
            st.session_state["extra_blocked"].append(
                {"country": new_block_country.strip(), "vertical": new_block_vertical}
            )
            st.success(f"Blocked: {new_block_country.strip()} + {new_block_vertical}")
    if st.session_state["extra_blocked"]:
        for i, b in enumerate(st.session_state["extra_blocked"]):
            c1, c2 = st.columns([3,1])
            c1.caption(f"🚫 {b['country']} · {b['vertical']}")
            if c2.button("✕", key=f"rmblk_{i}"):
                st.session_state["extra_blocked"].pop(i)
                st.rerun()

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
    st.markdown("*EyeClick Reseller Finder v2.9*")

# ================================================================
# HEADER
# ================================================================
st.markdown(f"""
<div class="ec-header">
  {_logo_img_tag(dark_bg=True)}
  <div class="ec-header-text">
    <div class="title">Reseller Finder</div>
    <div class="sub">AI-powered worldwide reseller discovery &nbsp;·&nbsp; email outreach &nbsp;·&nbsp; follow-up tracking</div>
  </div>
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
# EYECLICK PROFILE  +  ICP  +  PER-VERTICAL VALUE PROPOSITIONS
# ================================================================
EYECLICK_PROFILE = """
COMPANY: EyeClick (eyeclick.com)
PRODUCT: Interactive projection systems — projects games & activities onto floors/walls.
PRICE RANGE: $5,000–$30,000+ per system.
SALES MODEL: Sold exclusively through resellers / distributors worldwide.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IDEAL CUSTOMER PROFILE (ICP) — RESELLER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Company size: 5–500 employees
• Already sells equipment / technology / solutions to one of EyeClick's verticals
• Has an established sales force calling on facilities in those sectors
• Looking to expand product portfolio or add recurring revenue
• Strong regional presence or national distribution network
• BONUS signals: recently hired sales staff · expanding to new regions ·
  launched new product lines · raised funding · opened new offices

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VERTICALS · IDEAL RESELLERS · VALUE PROPOSITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SENIORS
  End customers : senior/assisted-living facilities, nursing homes, memory care units,
                  dementia care centres, rehabilitation centres, occupational therapy clinics.
  Ideal resellers: senior-care product distributors, cognitive stimulation equipment suppliers,
                   sensory room providers, rehab/OT equipment companies, nursing home tech suppliers.
  VALUE PROPOSITION FOR EMAIL:
    "EyeClick's interactive projection system is purpose-built for senior engagement —
     it projects games and activities directly onto floors and walls, requiring no
     hand-held devices, making it ideal for residents with limited mobility or cognitive
     decline. Facilities report measurable improvements in social engagement and motor
     activity. It's a natural complement to your existing senior care product portfolio."

EDUCATION
  End customers : K-12 schools, elementary schools, early-education/preschools,
                  daycare centres, special-education programmes.
  Ideal resellers: EdTech companies, school AV/furniture/playground equipment suppliers,
                   special-education technology providers, early childhood learning distributors.
  VALUE PROPOSITION FOR EMAIL:
    "EyeClick transforms any floor into an interactive learning environment — no screens,
     no devices, just pure physical play that develops motor skills, literacy and numeracy.
     Schools see measurable improvements in engagement and physical activity. It fits
     perfectly alongside your existing furniture, AV, or playground product lines."

ENTERTAINMENT
  End customers : trampoline parks, family entertainment centres (FECs),
                  QSRs with play areas, indoor playgrounds, bowling alleys, leisure centres.
  Ideal resellers: amusement/FEC equipment suppliers, playground equipment distributors,
                   entertainment technology companies, arcade/attractions dealers, leisure tech firms.
  VALUE PROPOSITION FOR EMAIL:
    "EyeClick adds a unique, high-margin interactive attraction that drives repeat visits
     and longer dwell time. FEC operators report 20–35% increase in repeat customers after
     installing EyeClick zones. With a typical ROI under 12 months, it's one of the
     strongest upsells you can offer your FEC and trampoline park clients."
"""

# ================================================================
# GOLD EXAMPLES — real EyeClick resellers used as pattern-matching
# ================================================================
GOLD_EXAMPLES = {
    "Seniors": [
        {
            "name"    : "CDS Boutique",
            "website" : "https://cdsboutique.com/en/",
            "country" : "Canada",
            "summary" : "Distributor of cognitive stimulation, sensory and activity products "
                        "for senior care facilities, nursing homes and memory care units in Canada.",
        },
        {
            "name"    : "Fu Kang Healthcare",
            "website" : "https://fukanghealthcare.com/",
            "country" : "Singapore",
            "summary" : "Healthcare equipment and assistive technology distributor serving elderly "
                        "care facilities, rehabilitation centres and nursing homes across Singapore.",
        },
        {
            "name"    : "Pro Senectute",
            "website" : "https://www.pro-senectute.it/",
            "country" : "Italy",
            "summary" : "Italian organisation supplying products and services for senior "
                        "well-being, cognitive engagement and active ageing in care facilities.",
        },
    ],
    "Education": [
        {
            "name"    : "Kaplan Early Learning",
            "website" : "https://www.kaplanco.com/",
            "country" : "USA",
            "summary" : "National distributor of early childhood and K-12 educational materials, "
                        "classroom furniture, learning toys and STEM supplies for schools and daycares.",
        },
        {
            "name"    : "Jonti-Craft",
            "website" : "https://www.jonti-craft.com/",
            "country" : "USA",
            "summary" : "Manufacturer and distributor of children's furniture, storage and "
                        "educational equipment for K-12 schools, preschools and daycare centres.",
        },
        {
            "name"    : "Southpaw Enterprises",
            "website" : "https://www.southpaw.com/",
            "country" : "USA",
            "summary" : "Distributor of sensory integration, occupational therapy and special "
                        "education equipment for schools and therapy clinics.",
        },
    ],
    "Entertainment": [
        {
            "name"    : "Zone Leisure Technology",
            "website" : "https://www.facebook.com/ZoneLeisureTechnology/",
            "country" : "United Kingdom",
            "summary" : "UK-based leisure technology company supplying interactive attractions, "
                        "entertainment equipment and digital play solutions to FECs and leisure venues.",
        },
    ],
}

# ================================================================
# BLOCKED TERRITORIES — hard-coded defaults + user-configurable
# ================================================================
DEFAULT_BLOCKED = [
    {"country": "Israel",  "vertical": "ALL"},
    {"country": "Canada",  "vertical": "Seniors"},
]

def get_blocked_territories() -> list:
    """Merge hard-coded defaults with any user-added blocks from sidebar."""
    base  = list(DEFAULT_BLOCKED)
    extra = st.session_state.get("extra_blocked", [])
    return base + extra

def is_blocked(country: str, vertical: str, blocked: list) -> bool:
    c = country.strip().lower()
    for b in blocked:
        bc = b["country"].strip().lower()
        bv = b["vertical"].strip().lower()
        if bc == c and (bv == "all" or bv == vertical.lower()):
            return True
    return False

# ================================================================
# SEARCH QUERY TEMPLATES  (standard + growth-signal queries)
# ================================================================
QUERY_TEMPLATES = {
    "Seniors": [
        "senior care technology equipment distributor dealer {region}",
        "nursing home assistive technology B2B supplier {region}",
        "assisted living equipment reseller sales force {region}",
        "dementia care sensory equipment specialist distributor {region}",
        "occupational therapy senior care equipment dealer company {region}",
        "senior living engagement technology B2B distributor {region}",
        "care home activity technology supplier company {region}",
    ],
    "Education": [
        "educational technology B2B reseller K12 schools distributor {region}",
        "special education equipment specialist supplier {region}",
        "early childhood education equipment B2B dealer {region}",
        "school interactive AV equipment reseller VAR {region}",
        "EdTech distributor company elementary schools {region}",
        "school furniture equipment dealer expanding technology {region}",
        "sensory playground inclusive equipment distributor {region}",
    ],
    "Entertainment": [
        "trampoline park FEC equipment supplier B2B {region}",
        "family entertainment center attractions equipment distributor {region}",
        "indoor playground equipment specialist supplier {region}",
        "amusement park attractions equipment dealer {region}",
        "leisure technology interactive attractions B2B supplier {region}",
        "FEC equipment dealer expanding interactive portfolio {region}",
        "entertainment venue technology equipment reseller {region}",
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
    "🌍  Middle East (excl. Israel)"          : "Middle East UAE Saudi Arabia",
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

def analyse_companies(client, results: list, vertical: str, query: str,
                      region_label: str, blocked: list) -> list:
    # Build gold examples block for this vertical
    examples = GOLD_EXAMPLES.get(vertical, [])
    gold_block = ""
    if examples:
        gold_block = f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nGOLD EXAMPLES — find companies SIMILAR to these known EyeClick resellers:\n"
        for ex in examples:
            gold_block += f"  • {ex['name']} ({ex['country']}) — {ex['website']}\n    {ex['summary']}\n"

    # Build blocked territories warning
    blocked_str = "\n".join(
        f"  • {b['country']} + {b['vertical']}" for b in blocked
    )
    blocked_block = f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nBLOCKED TERRITORIES — NEVER return companies from:\n{blocked_str}\n(EyeClick already has exclusive distributors there)\n" if blocked_str else ""

    prompt = f"""You are a senior business development expert for EyeClick, identifying ideal reseller partners.

{EYECLICK_PROFILE}
{gold_block}{blocked_block}
Search query: "{query}"  |  Vertical: {vertical}  |  Region: {region_label}

Search results:
{json.dumps(results, indent=2)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORING RUBRIC (use for fit_score)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start at 5. Add points for:
+2  Already sells equipment/technology to EyeClick's exact end-customers
+1  Has established sales force / distribution network
+1  Growth signals detected (hiring, expanding, new locations, new product lines)
+1  Strong regional/national presence
-1  Very large enterprise (500+ employees)
-2  No clear connection to EyeClick's end-customer verticals

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IDEAL RESELLER PROFILE: A company with a dedicated B2B sales force that regularly
calls on {vertical} end-customers (care homes, schools, FECs, etc.) and actively
resells/distributes equipment or technology products — NOT a single venue or end-user.

1. HARD REJECT the following — do NOT include them even if they mention seniors/education/entertainment:
   • Articles, blogs, news sites, directories, Wikipedia, LinkedIn profiles, job boards
   • Finance, banking, insurance, legal, real estate, HR, unrelated software
   • Single end-customer venues (one school, one nursing home, one FEC venue)
   • Catalog / mail-order / online-only retailers and party supply companies
     (e.g. S&S Worldwide, Lakeshore Learning storefront, Oriental Trading)
   • General merchandise / promotional products distributors
   • Companies whose primary business is consumables, crafts, or party supplies
   • Large consumer e-commerce companies (Amazon, Walmart, etc.)
2. HARD REJECT any company from the BLOCKED TERRITORIES listed above.
3. PRIORITISE: specialist distributors, equipment dealers, and VARs that have physical
   sales reps visiting {vertical} facilities and already carry comparable equipment.
4. Score each qualifying company. Look for similarity to the GOLD EXAMPLES.
5. For companies scoring 5+, draft a personalised email referencing their
   specific business. Use the {vertical} VALUE PROPOSITION above.

Return JSON with key "companies" → array:
{{
  "company_name"      : "...",
  "website"           : "full URL including https://",
  "country"           : "...",
  "vertical"          : "{vertical}",
  "description"       : "One sentence: what they sell and to whom.",
  "fit_score"         : <integer 5-10>,
  "fit_reason"        : "2-3 sentences: ICP match + similarity to gold examples.",
  "growth_signals"    : "Growth signals found, or 'None detected'.",
  "evidence_snippets" : ["Short paraphrased evidence point 1 from search results",
                         "Short paraphrased evidence point 2"],
  "contact_role"      : "CEO / Owner / VP Sales / Managing Director — most senior only",
  "email_subject"     : "Specific, compelling subject line",
  "email_body"        : "150-200 word personalised outreach. Open with something specific about their business. Do NOT include sign-off or signature."
}}

Include all real companies with fit_score >= 5. Return valid JSON only."""
    raw = ""
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929",
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

def validate_website(url: str) -> bool:
    """Return True if the URL is reachable (HTTP < 400). Uses HEAD then GET fallback."""
    if not url or not url.startswith("http"):
        return False
    headers = {"User-Agent": "Mozilla/5.0 (compatible; EyeClickBot/1.0)"}
    try:
        r = requests.head(url, timeout=4, allow_redirects=True, headers=headers)
        return r.status_code < 400
    except Exception:
        pass
    try:
        r = requests.get(url, timeout=4, allow_redirects=True, headers=headers, stream=True)
        return r.status_code < 400
    except Exception:
        return False

def linkedin_search(client, company_name: str) -> dict:
    """Search for the most senior person at company_name on LinkedIn.
    Verifies the result actually mentions the company before returning it."""
    query   = (f'site:linkedin.com/in "{company_name}" '
               f'CEO OR "Managing Director" OR "VP" OR Owner OR President OR Founder')
    results = serper_search(query, 8)
    if not results:
        return {}

    # ── Verification pass: keep snippets that mention the company name ──
    co_lower  = company_name.lower()
    verified  = [r for r in results
                 if co_lower in (r.get("snippet","") + r.get("title","")).lower()]
    unverified_flag = len(verified) == 0          # no result explicitly mentioned the company
    use_results     = verified if verified else results   # fall back to all if nothing verified

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role": "user", "content":
                f'From these LinkedIn search results, find the most senior person who actually '
                f'WORKS AT "{company_name}". If no result clearly shows someone at that company, '
                f'set works_at_company to false.\n'
                f'{json.dumps(use_results)}\n'
                'Return JSON only (no markdown): '
                '{{"name":"","title":"","linkedin":"https://linkedin.com/in/...","works_at_company":true}}'}],
        )
        m = re.search(r'\{.*?\}', resp.content[0].text, re.DOTALL)
        if not m:
            return {}
        data = json.loads(m.group())
        if not data.get("works_at_company", True):
            return {}                              # Haiku itself flagged the match as wrong
        data["linkedin_unverified"] = unverified_flag
        return data
    except Exception:
        return {}

def enrich_contact(client, company: dict) -> dict:
    contact = {"name":"","title":"","email":"","confidence":"","linkedin":"","linkedin_unverified":False}
    h = hunter_search(company.get("website",""))
    if h:
        contact.update({"name"      : h.get("name",""),
                        "title"     : h.get("title",""),
                        "email"     : h.get("email",""),
                        "confidence": f"{h.get('confidence',0)}%" if h.get("confidence") else "",
                        "linkedin"  : h.get("linkedin","")})
    if not contact["name"] or not contact["linkedin"]:
        li = linkedin_search(client, company.get("company_name",""))
        if li:
            if not contact["name"]:
                contact["name"]  = li.get("name","")
                contact["title"] = li.get("title","")
            if not contact["linkedin"]:
                contact["linkedin"]            = li.get("linkedin","")
                contact["linkedin_unverified"] = li.get("linkedin_unverified", False)
    return contact

def generate_followup_email(client, company: dict, contact: dict, original_subject: str) -> str:
    """Ask Claude to write a personalised follow-up email for a company that has not replied."""
    first_name = contact.get("name","").split()[0] if contact.get("name") else "there"
    prompt = (
        f"You are a business development expert for EyeClick (eyeclick.com), "
        f"an interactive projection system sold exclusively through resellers worldwide.\n\n"
        f"Company: {company.get('company_name','')}\n"
        f"What they do: {company.get('description','')}\n"
        f"Why they fit: {company.get('fit_reason','')}\n"
        f"Contact first name: {first_name}\n"
        f"Original email subject: {original_subject}\n\n"
        f"Write a short (80-120 word), friendly follow-up email for someone who has not replied "
        f"to the first outreach. Reference that it is a follow-up. Be specific to their business. "
        f"Ask for a 15-minute call. Do NOT include any sign-off, greeting opener beyond 'Hi {first_name},' "
        f"or signature — just the body text starting with 'Hi {first_name},'.\n"
        f"Return only the email body text, no extra commentary."
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return ""

# ================================================================
# EXCEL EXPORT
# ================================================================
def build_excel(rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Reseller Prospects"
    headers = ["Date","Company","Website","Country","Vertical","Description",
               "Fit Score","Fit Reason","Growth Signals","Contact Name","Title","Email",
               "Email Confidence","LinkedIn","Email Subject","Email Body","Sent?"]
    hfill  = PatternFill(start_color="0057A8", end_color="0057A8", fill_type="solid")
    hfont  = Font(color="FFFFFF", bold=True)
    widths = [11,25,32,14,14,45,9,45,35,20,20,30,14,35,40,80,8]
    for ci,(h,w) in enumerate(zip(headers,widths),1):
        c = ws.cell(1,ci,h); c.fill=hfill; c.font=hfont
        c.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    vcol = {"Seniors":"FCE4EC","Healthcare":"E8F5E9","Education":"E3F2FD","Entertainment":"FFF3E0"}
    sent_companies = {e.get("company") for e in load_sent_log()}
    for r in rows:
        contact = r.get("contact",{})
        ws.append([
            datetime.now().strftime("%Y-%m-%d"),
            r.get("company_name",""), r.get("website",""),
            r.get("country",""), r.get("vertical",""),
            r.get("description",""), r.get("fit_score",""), r.get("fit_reason",""),
            r.get("growth_signals",""),
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

    company_name   = e(company_name_raw)
    country        = e(r.get("country",""))
    description    = e(r.get("description",""))
    fit_reason     = e(r.get("fit_reason",""))
    growth_signals = e(r.get("growth_signals",""))
    contact_name   = e(contact.get("name","—"))
    contact_title  = e(contact.get("title",""))
    confidence     = e(contact.get("confidence",""))

    website_ok     = r.get("website_ok", None)   # None = not checked yet
    li_unverified  = contact.get("linkedin_unverified", False)

    country_html   = f'&nbsp;<span style="color:#666;font-size:.85rem;">🌐 {country}</span>' if country else ""
    conf_html      = f'<span style="color:#888;font-size:.85rem;">{confidence} confidence</span>' if confidence else ""
    sent_html      = '&nbsp;<span class="sent-badge">✅ Email Sent</span>' if sent else ""
    email_link     = (f'<a href="mailto:{e(email_raw)}" style="color:#0057A8;">{e(email_raw)}</a>'
                      if email_raw else "<em style='color:#999;'>not found</em>")
    web_warn       = ('&nbsp;<span style="color:#e65100;font-size:.78rem;font-weight:600;">⚠️ Site unreachable</span>'
                      if website_ok is False else "")
    website_link   = (f'<a href="{e(website_raw)}" target="_blank" style="color:#0057A8;font-size:.88rem;">'
                      f'🌐 {e(website_raw)}</a>{web_warn}' if website_raw else "")
    has_growth     = growth_signals and growth_signals.lower() not in ("none detected","none","")
    growth_html    = (f'<div style="margin:.3rem 0;background:#fff8e1;border-left:3px solid #ffb300;'
                      f'padding:.3rem .6rem;border-radius:4px;font-size:.82rem;color:#7a5800;">'
                      f'📈 <strong>Growth signal:</strong> {growth_signals}</div>'
                      if has_growth else "")

    # Evidence snippets
    snippets       = r.get("evidence_snippets", [])
    snippets_html  = ""
    if snippets:
        items = "".join(f'<li style="margin:.15rem 0;">{e(s)}</li>' for s in snippets[:2])
        snippets_html = (f'<div style="margin:.3rem 0;background:#f0f4fa;border-left:3px solid #0057A8;'
                         f'padding:.3rem .6rem;border-radius:4px;font-size:.82rem;color:#333;">'
                         f'🔍 <strong>Evidence:</strong><ul style="margin:.2rem 0;padding-left:1.2rem;">{items}</ul></div>')

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
      {('<div style="margin:.25rem 0 .3rem;">' + website_link + '</div>') if website_link else ''}
      <p style="margin:.4rem 0 .25rem;color:#444;font-size:.92rem;">{description}</p>
      <p style="margin:0 0 .25rem;color:#555;font-size:.85rem;"><em>{fit_reason}</em></p>
      {snippets_html}
      {growth_html}
      <hr style="margin:.5rem 0;border-color:#eee;">
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
        unverified_note = " ⚠️ *profile match unverified — please confirm*" if li_unverified else ""
        st.markdown(f"&nbsp;&nbsp;&nbsp;[🔗 LinkedIn Profile]({linkedin_raw}){unverified_note}",
                    unsafe_allow_html=True)

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

        # ── Copy full email preview ──
        full_preview = body + ("\n\n" + sig if sig else "")
        with st.expander("📋 Preview & copy full email"):
            st.code(full_preview, language=None)

        # Follow-up email (if already sent)
        if sent:
            st.markdown("---")
            st.markdown("**🔄 Send Follow-up Email**")
            fu_subj_key = f"fu_subj_{key_prefix}_{hash(website_raw)}"
            fu_body_key = f"fu_body_{key_prefix}_{hash(website_raw)}"
            if fu_subj_key not in st.session_state:
                st.session_state[fu_subj_key] = f"Following up: {subject}"
            if fu_body_key not in st.session_state:
                first = contact.get("name","").split()[0] if contact.get("name") else "there"
                st.session_state[fu_body_key] = (
                    f"Hi {first},\n\n"
                    f"I wanted to follow up on my previous message regarding EyeClick's interactive "
                    f"projection systems. Did you get a chance to review it?\n\n"
                    f"I'd love to schedule a quick 15-minute call to explore if there's a potential "
                    f"fit for a reseller partnership.\n\n"
                    f"Looking forward to hearing from you."
                )
            fu_subj = st.text_input("Follow-up subject", key=fu_subj_key)
            fu_body = st.text_area("Follow-up body (no signature — added automatically below)", key=fu_body_key, height=180)

            # AI generate button
            ai_gen_key = f"ai_gen_{key_prefix}_{hash(website_raw)}"
            if st.button("🤖 Generate AI Follow-up", key=ai_gen_key, use_container_width=True):
                with st.spinner("Writing personalised follow-up…"):
                    generated = generate_followup_email(
                        get_anthropic_client(), r, contact, subject
                    )
                if generated:
                    st.session_state[fu_body_key] = generated
                    st.rerun()
                else:
                    st.warning("Could not generate — try again.")

            # Signature (live, never baked into body)
            sig = st.session_state.get("signature","")
            fu_full = fu_body + ("\n\n" + sig if sig else "")

            # Full follow-up preview
            with st.expander("📋 Preview & copy follow-up email"):
                st.code(fu_full, language=None)

            if email_raw:
                fu_mailto = ("mailto:" + email_raw
                             + "?subject=" + urllib.parse.quote(fu_subj)
                             + "&body="    + urllib.parse.quote(fu_full))
                b1, b2 = st.columns(2)
                b1.link_button("📨 Open Follow-up in Email Client", fu_mailto, use_container_width=True)
                if b2.button("✅ Mark Follow-up Sent", key=f"fu_done_{key_prefix}_{hash(website_raw)}", use_container_width=True):
                    mark_followup_done(company_name_raw)
                    st.success("Follow-up marked as done!")
                    st.rerun()

    # ── Report Issue ──
    report_options = [
        "a. Incorrect details — website or contact info is wrong",
        "b. LinkedIn profile is not correct / couldn't be verified",
        "c. Wrong industry — this company is irrelevant (remove permanently)",
    ]
    with st.expander(f"🚩 Report an Issue · {company_name_raw}"):
        st.markdown("Help improve search quality by flagging a problem with this result:")
        chosen = st.radio("Issue type:", report_options,
                          key=f"report_radio_{key_prefix}_{hash(website_raw)}",
                          label_visibility="collapsed")
        if st.button("🚩 Submit Report", key=f"report_btn_{key_prefix}_{hash(website_raw)}",
                     use_container_width=True):
            code = "details" if chosen.startswith("a") else "linkedin" if chosen.startswith("b") else "industry"
            save_feedback(company_name_raw, website_raw, code)
            if code == "industry":
                current = st.session_state.get("last_results", [])
                st.session_state["last_results"] = [
                    c for c in current if c.get("website","") != website_raw
                ]
                st.success("🗑️ Removed from results. This company will be skipped in future searches.")
                st.rerun()
            elif code == "linkedin":
                st.success("✅ LinkedIn issue noted. Please use the correct profile if you find it.")
            else:
                st.success("✅ Details issue reported — thank you!")

# ================================================================
# SEARCH FORM
# ================================================================
with st.container():
    col1, col2, col3, col4 = st.columns([2, 2, 1.2, 1])
    with col1:
        st.markdown("**Vertical (market segment)**")
        sel_h = st.checkbox("👴 Seniors",        value=True)
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

selected_verticals = (["Seniors"]       if sel_h else []) + \
                     (["Education"]     if sel_e else []) + \
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
    blocked = get_blocked_territories()
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
        companies = analyse_companies(client, results, v, query, region_label, blocked)
        dedup     = st.session_state.get("dedup_days", 30)
        new       = [c for c in companies
                     if c.get("website","") not in seen_sites
                     and not is_recently_seen(c.get("website",""), dedup)
                     and not is_blocked(c.get("country",""), v, blocked)
                     and not is_flagged_wrong_industry(c.get("website",""))]
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
        company["contact"]    = enrich_contact(client, company)
        company["website_ok"] = validate_website(company.get("website",""))
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

    # Stats bar
    groups = {"Seniors":[], "Education":[], "Entertainment":[]}
    for r in final:
        groups.get(r.get("vertical",""), []).append(r)
    avg_score = round(sum(r.get("fit_score",0) for r in final) / max(len(final),1), 1)
    with_email = sum(1 for r in final if r.get("contact",{}).get("email"))
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("Total Found", len(final))
    s2.metric("👴 Seniors",       len(groups["Seniors"]))
    s3.metric("🏫 Education",     len(groups["Education"]))
    s4.metric("🎯 Entertainment", len(groups["Entertainment"]))
    s5.metric("Avg Fit Score",    f"{avg_score}/10")
    s6.metric("With Email",       with_email)
    st.markdown("---")

    tabs   = st.tabs(["📋 All Results", "👴 Seniors", "🏫 Education", "🎯 Entertainment"])

    with tabs[0]:
        for i, r in enumerate(final, 1):
            result_card(r, i, key_prefix="all")

    for tab, vertical in zip(tabs[1:], ["Seniors","Education","Entertainment"]):
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
