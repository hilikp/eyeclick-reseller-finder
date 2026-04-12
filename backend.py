#!/usr/bin/env python3
"""
backend.py — Shared business logic for app.py and daily_worker.py.
Zero Streamlit dependency. All API keys passed as explicit parameters.
"""

import re, json, os, time, requests, smtplib, ssl, uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# ================================================================
# LLM CLIENT — Gemini wrapper (drop-in replacement for Anthropic)
# ================================================================
class GeminiClient:
    """Drop-in replacement for anthropic.Anthropic() using Google Gemini (free tier)."""
    def __init__(self, api_key: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self._flash = genai.GenerativeModel("gemini-2.0-flash")
        self._pro   = genai.GenerativeModel("gemini-2.0-flash")  # use flash for all (free)
        self.messages = self  # allows client.messages.create(...)

    def create(self, model: str, max_tokens: int, messages: list) -> object:
        prompt = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        gem = self._pro if "sonnet" in model else self._flash
        resp = gem.generate_content(
            prompt,
            generation_config={"max_output_tokens": max_tokens, "temperature": 0.2},
        )
        text = resp.text if hasattr(resp, "text") else ""
        class _C:
            def __init__(self, t): self.text = t
        class _R:
            def __init__(self, t): self.content = [_C(t)]
        return _R(text)


def make_llm_client(gemini_api_key: str = "", anthropic_api_key: str = ""):
    """Return a GeminiClient if key provided, else fall back to Anthropic."""
    if gemini_api_key:
        return GeminiClient(gemini_api_key)
    import anthropic
    return anthropic.Anthropic(api_key=anthropic_api_key)

# ── File paths (relative to CWD — both app.py and daily_worker.py chdir first) ──
SENT_LOG_FILE       = "sent_log.json"
SEEN_COMPANIES_FILE = "seen_companies.json"
FEEDBACK_LOG_FILE   = "feedback_log.json"
QUEUE_FILE          = "outreach_queue.json"

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
# BLOCKED TERRITORIES
# ================================================================
DEFAULT_BLOCKED = [
    {"country": "Israel",  "vertical": "ALL"},
    {"country": "Canada",  "vertical": "Seniors"},
]

def is_blocked(country: str, vertical: str, blocked: list) -> bool:
    c = country.strip().lower()
    for b in blocked:
        bc = b["country"].strip().lower()
        bv = b["vertical"].strip().lower()
        if bc == c and (bv == "all" or bv == vertical.lower()):
            return True
    return False

# ================================================================
# SEARCH QUERY TEMPLATES
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
# FEEDBACK LOG
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
    existing       = load_seen_companies()
    existing_sites = {e.get("website","").lower() for e in existing}
    today          = datetime.now().strftime("%Y-%m-%d")
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
# OUTREACH QUEUE
# ================================================================
def load_queue() -> list:
    try:
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_queue(items: list):
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump(items, f, indent=2)
    except Exception:
        pass

def add_to_queue(item: dict) -> bool:
    """Add item to queue. Returns False if this email is already pending or sent."""
    queue = load_queue()
    existing_emails = {i["contact_email"] for i in queue
                       if i["status"] in ("pending", "sent") and i.get("contact_email")}
    if item.get("contact_email") in existing_emails:
        return False
    queue.append(item)
    save_queue(queue)
    return True

def mark_queue_item(item_id: str, status: str):
    """Set status to 'sent' or 'skipped' for a queue item."""
    queue = load_queue()
    for item in queue:
        if item["id"] == item_id:
            item["status"] = status
            if status == "sent":
                item["sent_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            break
    save_queue(queue)

# ================================================================
# GMAIL SEND  (stdlib only — smtplib + ssl)
# ================================================================
def send_gmail(to: str, subject: str, body: str, signature: str,
               gmail_user: str, gmail_app_password: str) -> bool:
    """Send a plain-text email via Gmail SMTP using an App Password.
    Returns True on success, False on any error."""
    if not gmail_user or not gmail_app_password or not to:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = gmail_user
        msg["To"]      = to
        msg["Subject"] = subject
        full_body = body + ("\n\n" + signature if signature else "")
        msg.attach(MIMEText(full_body, "plain"))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to, msg.as_string())
        return True
    except Exception:
        return False

# ================================================================
# SERPER SEARCH
# ================================================================
def serper_search(query: str, n: int, serper_api_key: str) -> list:
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_api_key, "Content-Type": "application/json"},
            json={"q": query, "num": n}, timeout=15,
        )
        r.raise_for_status()
        return [{"title": i.get("title",""), "link": i.get("link",""), "snippet": i.get("snippet","")}
                for i in r.json().get("organic", [])]
    except Exception:
        return []

# ================================================================
# ANALYSE COMPANIES
# ================================================================
def analyse_companies(client, results: list, vertical: str, query: str,
                      region_label: str, blocked: list) -> list:
    examples   = GOLD_EXAMPLES.get(vertical, [])
    gold_block = ""
    if examples:
        gold_block = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nGOLD EXAMPLES — find companies SIMILAR to these known EyeClick resellers:\n"
        for ex in examples:
            gold_block += f"  • {ex['name']} ({ex['country']}) — {ex['website']}\n    {ex['summary']}\n"

    blocked_str   = "\n".join(f"  • {b['country']} + {b['vertical']}" for b in blocked)
    blocked_block = (f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nBLOCKED TERRITORIES — NEVER return companies from:\n{blocked_str}\n"
                     f"(EyeClick already has exclusive distributors there)\n") if blocked_str else ""

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
  "email_body"        : "150-200 word personalised outreach. Open with something specific about their business. Do NOT include sign-off or signature. Use plain hyphens (-) instead of em dashes (—). No em dashes anywhere."
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
    except Exception as e:
        import sys
        print(f"[analyse_companies ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        if raw:
            print(f"[analyse_companies RAW] {raw[:300]}", file=sys.stderr)
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

# ================================================================
# EMAIL FINDER — shared title scoring used by all providers
# ================================================================
_PRIORITY_TITLES = [
    "Owner", "Co-Founder", "Founder", "CEO", "Chief Executive",
    "President", "Managing Director", "Managing Partner",
    "VP Sales", "VP Business", "Vice President", "Director of Sales",
    "Sales Director", "Commercial Director", "Head of Sales",
    "General Manager", "Country Manager", "Regional Manager",
]
_LOW_TITLES = [
    "Sales Manager", "Account Manager", "Sales Representative",
    "Sales Executive", "Business Development Manager", "BDM",
]

def _score_title(position: str, confidence: int = 0) -> tuple:
    pos = (position or "").upper()
    for lw in _LOW_TITLES:
        if lw.upper() in pos:
            return (-1, confidence)
    for i, kw in enumerate(_PRIORITY_TITLES):
        if kw.upper() in pos:
            return (len(_PRIORITY_TITLES) - i, confidence)
    return (0, confidence)

def _clean_domain(url: str) -> str:
    return re.sub(r"https?://(www\.)?", "", url).strip("/").split("/")[0]

# ── Hunter.io ──────────────────────────────────────────────────────────────
def hunter_search(domain: str, hunter_api_key: str) -> dict:
    domain = _clean_domain(domain)
    if not domain or not hunter_api_key:
        return {}
    try:
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": hunter_api_key, "limit": 10},
            timeout=12,
        )
        if r.status_code == 429 or r.status_code == 401:
            return {}          # quota exhausted or bad key — signal fallback
        r.raise_for_status()
        emails = r.json().get("data", {}).get("emails", [])
        if not emails:
            return {}
        best = sorted(emails,
                      key=lambda e: _score_title(e.get("position",""), e.get("confidence",0)),
                      reverse=True)[0]
        return {
            "name"      : f"{best.get('first_name','')} {best.get('last_name','')}".strip(),
            "title"     : best.get("position",""),
            "email"     : best.get("value",""),
            "confidence": best.get("confidence",0),
            "linkedin"  : best.get("linkedin",""),
            "source"    : "hunter",
        }
    except Exception:
        return {}

# ── Apollo.io ──────────────────────────────────────────────────────────────
def apollo_search(domain: str, apollo_api_key: str) -> dict:
    domain = _clean_domain(domain)
    if not domain or not apollo_api_key:
        return {}
    try:
        r = requests.post(
            "https://api.apollo.io/v1/people/match",
            headers={"Content-Type": "application/json",
                     "Cache-Control": "no-cache",
                     "X-Api-Key": apollo_api_key},
            json={"domain": domain,
                  "reveal_personal_emails": False,
                  "reveal_phone_number": False},
            timeout=12,
        )
        if r.status_code in (401, 403, 429):
            return {}
        r.raise_for_status()
        person = r.json().get("person") or {}
        email  = person.get("email","")
        if not email:
            # Try organization people list
            r2 = requests.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"Content-Type": "application/json", "X-Api-Key": apollo_api_key},
                json={"q_organization_domains": domain, "page": 1, "per_page": 10,
                      "person_seniorities": ["owner","founder","c_suite","vp","director","manager"]},
                timeout=12,
            )
            if r2.status_code == 200:
                people = r2.json().get("people", [])
                if people:
                    best = sorted(people,
                                  key=lambda p: _score_title(p.get("title",""), 0),
                                  reverse=True)[0]
                    email = best.get("email","")
                    return {
                        "name"      : best.get("name",""),
                        "title"     : best.get("title",""),
                        "email"     : email,
                        "confidence": 80 if email else 0,
                        "linkedin"  : best.get("linkedin_url",""),
                        "source"    : "apollo",
                    }
            return {}
        return {
            "name"      : person.get("name",""),
            "title"     : person.get("title",""),
            "email"     : email,
            "confidence": 80 if email else 0,
            "linkedin"  : person.get("linkedin_url",""),
            "source"    : "apollo",
        }
    except Exception:
        return {}

# ── Snov.io ────────────────────────────────────────────────────────────────
def snov_search(domain: str, snov_client_id: str, snov_client_secret: str) -> dict:
    domain = _clean_domain(domain)
    if not domain or not snov_client_id or not snov_client_secret:
        return {}
    try:
        # Step 1: get access token
        tok = requests.post(
            "https://api.snov.io/v1/oauth/access_token",
            json={"grant_type": "client_credentials",
                  "client_id": snov_client_id,
                  "client_secret": snov_client_secret},
            timeout=10,
        )
        if tok.status_code != 200:
            return {}
        token = tok.json().get("access_token","")
        if not token:
            return {}
        # Step 2: domain search
        r = requests.post(
            "https://api.snov.io/v2/domain-emails-with-info",
            headers={"Authorization": f"Bearer {token}"},
            json={"domain": domain, "type": "all", "limit": 10},
            timeout=12,
        )
        if r.status_code in (401, 403, 429):
            return {}
        r.raise_for_status()
        emails = r.json().get("emails", [])
        if not emails:
            return {}
        best = sorted(emails,
                      key=lambda e: _score_title(e.get("position",""), e.get("confidence",0)),
                      reverse=True)[0]
        email_addr = best.get("email","")
        return {
            "name"      : f"{best.get('firstName','')} {best.get('lastName','')}".strip(),
            "title"     : best.get("position",""),
            "email"     : email_addr,
            "confidence": best.get("confidence", 70) if email_addr else 0,
            "linkedin"  : best.get("linkedIn",""),
            "source"    : "snov",
        }
    except Exception:
        return {}

# ── Prospeo ────────────────────────────────────────────────────────────────
def prospeo_search(domain: str, prospeo_api_key: str) -> dict:
    domain = _clean_domain(domain)
    if not domain or not prospeo_api_key:
        return {}
    try:
        r = requests.get(
            "https://api.prospeo.io/domain-search",
            headers={"X-KEY": prospeo_api_key},
            params={"domain": domain, "limit": 10},
            timeout=12,
        )
        if r.status_code in (401, 403, 429):
            return {}
        r.raise_for_status()
        emails = r.json().get("response", {}).get("emails", [])
        if not emails:
            return {}
        best = sorted(emails,
                      key=lambda e: _score_title(e.get("seniority",""), 0),
                      reverse=True)[0]
        email_addr = best.get("email","")
        return {
            "name"      : f"{best.get('first_name','')} {best.get('last_name','')}".strip(),
            "title"     : best.get("position",""),
            "email"     : email_addr,
            "confidence": 75 if email_addr else 0,
            "linkedin"  : best.get("linkedin",""),
            "source"    : "prospeo",
        }
    except Exception:
        return {}

# ── Fallback chain: Hunter → Apollo → Snov → Prospeo ─────────────────────
def find_contact_email(domain: str, keys: dict) -> dict:
    """Try email finders in order until one returns a result.
    keys dict: hunter_api_key, apollo_api_key, snov_client_id,
               snov_client_secret, prospeo_api_key  (all optional)
    Returns same dict format as hunter_search, plus 'source' field."""
    result = hunter_search(domain, keys.get("hunter_api_key",""))
    if result.get("email"):
        return result

    result = apollo_search(domain, keys.get("apollo_api_key",""))
    if result.get("email"):
        return result

    result = snov_search(domain, keys.get("snov_client_id",""),
                         keys.get("snov_client_secret",""))
    if result.get("email"):
        return result

    result = prospeo_search(domain, keys.get("prospeo_api_key",""))
    if result.get("email"):
        return result

    return {}

# ================================================================
# VALIDATE WEBSITE
# ================================================================
def validate_website(url: str) -> bool:
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

# ================================================================
# LINKEDIN SEARCH
# ================================================================
def linkedin_search(client, company_name: str, serper_api_key: str) -> dict:
    query   = (f'site:linkedin.com/in "{company_name}" '
               f'CEO OR "Managing Director" OR "VP" OR Owner OR President OR Founder')
    results = serper_search(query, 8, serper_api_key)
    if not results:
        return {}

    co_lower        = company_name.lower()
    verified        = [r for r in results
                       if co_lower in (r.get("snippet","") + r.get("title","")).lower()]
    unverified_flag = len(verified) == 0
    use_results     = verified if verified else results

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
            return {}
        data["linkedin_unverified"] = unverified_flag
        return data
    except Exception:
        return {}

# ================================================================
# ENRICH CONTACT
# ================================================================
def enrich_contact(client, company: dict, serper_api_key: str,
                   email_keys) -> dict:
    """email_keys may be a plain hunter_api_key string (legacy) or a dict with
    hunter_api_key / apollo_api_key / snov_client_id / snov_client_secret /
    prospeo_api_key keys."""
    contact = {"name":"","title":"","email":"","confidence":"","linkedin":"","linkedin_unverified":False}
    # Normalise legacy callers that pass a plain string
    if isinstance(email_keys, str):
        email_keys = {"hunter_api_key": email_keys}

    h = find_contact_email(company.get("website",""), email_keys)
    if h and h.get("email"):
        contact.update({"name"      : h.get("name",""),
                        "title"     : h.get("title",""),
                        "email"     : h.get("email",""),
                        "confidence": f"{h.get('confidence',0)}%" if h.get("confidence") else "",
                        "linkedin"  : h.get("linkedin",""),
                        "email_source": h.get("source","")})
    if not contact["name"] or not contact["linkedin"]:
        li = linkedin_search(client, company.get("company_name",""), serper_api_key)
        if li:
            if not contact["name"]:
                contact["name"]  = li.get("name","")
                contact["title"] = li.get("title","")
            if not contact["linkedin"]:
                contact["linkedin"]            = li.get("linkedin","")
                contact["linkedin_unverified"] = li.get("linkedin_unverified", False)
    return contact

# ================================================================
# GENERATE FOLLOW-UP EMAIL
# ================================================================
def generate_followup_email(client, company: dict, contact: dict, original_subject: str) -> str:
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
        f"or signature — just the body text starting with 'Hi {first_name},'. "
        f"Use plain hyphens (-) instead of em dashes (—). No em dashes anywhere.\n"
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
