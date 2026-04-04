#!/usr/bin/env python3
"""
daily_worker.py — EyeClick Reseller Finder daily automation worker.
Runs via Windows Task Scheduler (daily at 8 AM).
Finds new leads, enriches contacts, queues emails, sends you a notification.

Setup:
  1. Add GMAIL_USER + GMAIL_APP_PASSWORD to .streamlit/secrets.toml
  2. Run once: schtasks /create /tn "EyeClickDailyOutreach"
       /tr "cmd /c python C:\\Users\\ypola\\eyeclick_agent\\daily_worker.py >> C:\\Users\\ypola\\eyeclick_agent\\worker_log.txt 2>&1"
       /sc daily /st 08:00 /f
  3. Test: schtasks /run /tn "EyeClickDailyOutreach"
"""

import os, sys, pathlib, tomllib, uuid, time, itertools, anthropic
from datetime import datetime

# ── Always run from the project directory so relative file paths work ──
os.chdir(pathlib.Path(__file__).parent)

# ── Import all shared logic from backend.py ──
from backend import (
    serper_search, analyse_companies, enrich_contact, validate_website,
    is_recently_seen, is_flagged_wrong_industry, is_blocked, already_sent,
    get_due_followups, generate_followup_email,
    add_to_queue, load_queue, add_to_seen_log, append_sent_log, mark_followup_done,
    send_gmail,
    QUERY_TEMPLATES, REGIONS, DEFAULT_BLOCKED,
)

# ================================================================
# USER CONFIGURATION — edit these to control daily search behaviour
# ================================================================
VERTICALS_TO_SEARCH = ["Seniors", "Education", "Entertainment"]
REGION_LABEL        = "🌍  Worldwide"          # must match a key in REGIONS dict
RESULTS_PER_RUN     = 10                        # companies to find per day
DEDUP_DAYS          = 30                        # skip companies seen in last N days
MIN_FIT_SCORE       = 6                         # minimum fit score to queue
APP_URL             = "https://eyeclick-reseller-finder-l6f3ifv45q8tah2lec9dlg.streamlit.app"
# ================================================================

def load_secrets() -> dict:
    secrets_path = pathlib.Path(".streamlit") / "secrets.toml"
    if not secrets_path.exists():
        print(f"ERROR: secrets file not found at {secrets_path.resolve()}")
        sys.exit(1)
    with open(secrets_path, "rb") as f:
        return tomllib.load(f)

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # encode to CP1252 (Windows CMD default) replacing unknown chars
    safe = msg.encode("cp1252", errors="replace").decode("cp1252")
    print(f"[{ts}] {safe}", flush=True)

def run():
    log("=== EyeClick Daily Worker starting ===")
    secrets = load_secrets()

    required = ["ANTHROPIC_API_KEY", "SERPER_API_KEY",
                "GMAIL_USER", "GMAIL_APP_PASSWORD"]
    for key in required:
        if not secrets.get(key):
            log(f"ERROR: Missing secret: {key}")
            sys.exit(1)

    client     = anthropic.Anthropic(api_key=secrets["ANTHROPIC_API_KEY"])
    region_kw  = REGIONS.get(REGION_LABEL, "")
    blocked    = list(DEFAULT_BLOCKED)
    email_keys = {
        "hunter_api_key"    : secrets.get("HUNTER_API_KEY", ""),
        "apollo_api_key"    : secrets.get("APOLLO_API_KEY", ""),
        "snov_client_id"    : secrets.get("SNOV_CLIENT_ID", ""),
        "snov_client_secret": secrets.get("SNOV_CLIENT_SECRET", ""),
        "prospeo_api_key"   : secrets.get("PROSPEO_API_KEY", ""),
    }
    seen_sites : set = set()
    all_companies   : list = []

    # ── Quick Serper connectivity test ────────────────────────────────────
    log("Connectivity test: pinging Serper API…")
    test_results = serper_search("senior care equipment distributor", 2, secrets["SERPER_API_KEY"])
    if not test_results:
        log("ERROR: Serper API returned no results on test query.")
        log("Possible causes: (1) SERPER_API_KEY quota exhausted — check serper.dev dashboard")
        log("                 (2) Wrong key in secrets.toml — verify SERPER_API_KEY value")
        log("Aborting — no point running searches if Serper is down.")
        send_gmail(
            to=secrets["GMAIL_USER"],
            subject="EyeClick Worker ERROR: Serper API not working",
            body="The daily worker could not get results from Serper.\n\n"
                 "Please check:\n"
                 "1. Your Serper quota at https://serper.dev (free = 2,500 searches/month)\n"
                 "2. That SERPER_API_KEY in secrets.toml is correct\n\n"
                 "Worker aborted — no emails queued today.",
            signature="",
            gmail_user=secrets["GMAIL_USER"],
            gmail_app_password=secrets["GMAIL_APP_PASSWORD"],
        )
        sys.exit(1)
    log(f"  ✓ Serper OK — got {len(test_results)} test result(s)")

    # ── Phase 1: Search + analyse ──────────────────────────────────────────
    log(f"Phase 1: Searching for {RESULTS_PER_RUN} companies in [{', '.join(VERTICALS_TO_SEARCH)}] / {REGION_LABEL}")
    v_cycle = itertools.cycle(VERTICALS_TO_SEARCH)
    q_pool  = {v: [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
               for v in VERTICALS_TO_SEARCH}
    attempt = 0

    while len(all_companies) < RESULTS_PER_RUN and attempt < 40:
        v = next(v_cycle)
        if not q_pool[v]:
            q_pool[v] = [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
        query = q_pool[v].pop(0)
        attempt += 1

        log(f"  Searching ({v}): {query}")
        results   = serper_search(query, 6, secrets["SERPER_API_KEY"])
        if not results:
            log(f"    ⚠ Serper returned 0 results")
            continue
        log(f"    Serper: {len(results)} results → analysing with Claude…")
        companies = analyse_companies(client, results, v, query, REGION_LABEL, blocked)
        log(f"    Claude: {len(companies)} qualifying companies")
        new = [c for c in companies
               if c.get("website","") not in seen_sites
               and not is_recently_seen(c.get("website",""), DEDUP_DAYS)
               and not is_blocked(c.get("country",""), v, blocked)
               and not is_flagged_wrong_industry(c.get("website",""))]
        for c in new:
            seen_sites.add(c.get("website",""))
        all_companies.extend(new)
        log(f"    → {len(new)} new ({len(all_companies)}/{RESULTS_PER_RUN} total)")
        time.sleep(0.8)

    final = all_companies[:RESULTS_PER_RUN]
    log(f"Phase 1 done: {len(final)} companies found")

    # ── Phase 2: Enrich + validate ─────────────────────────────────────────
    log(f"Phase 2: Enriching contacts for {len(final)} companies…")
    for i, company in enumerate(final):
        log(f"  [{i+1}/{len(final)}] {company.get('company_name','')}")
        company["contact"]    = enrich_contact(client, company,
                                               secrets["SERPER_API_KEY"],
                                               email_keys)
        company["website_ok"] = validate_website(company.get("website",""))
        time.sleep(0.6)

    add_to_seen_log(final)

    # ── Phase 3: Queue qualified companies ────────────────────────────────
    log(f"Phase 3: Queuing companies with score >= {MIN_FIT_SCORE}…")
    initial_count = 0
    no_email_count = 0
    for company in final:
        score   = company.get("fit_score", 0)
        contact = company.get("contact", {})
        email   = contact.get("email","")
        if score < MIN_FIT_SCORE:
            log(f"  ✗ Below score threshold: {company.get('company_name','')} (score={score})")
            continue
        # Queue even without email — user can review and manually find contact
        item = {
            "id"            : str(uuid.uuid4()),
            "type"          : "initial",
            "company_name"  : company.get("company_name",""),
            "website"       : company.get("website",""),
            "vertical"      : company.get("vertical",""),
            "contact_name"  : contact.get("name",""),
            "contact_title" : contact.get("title",""),
            "contact_email" : email,
            "fit_score"     : score,
            "description"   : company.get("description",""),
            "fit_reason"    : company.get("fit_reason",""),
            "growth_signals": company.get("growth_signals",""),
            "subject"       : company.get("email_subject",""),
            "body"          : company.get("email_body",""),
            "queued_date"   : datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status"        : "pending",
            "sent_date"     : None,
        }
        if add_to_queue(item):
            initial_count += 1
            if email:
                log(f"  ✓ Queued: {company.get('company_name','')} → {email} (score {score})")
            else:
                no_email_count += 1
                log(f"  ✓ Queued (no email): {company.get('company_name','')} (score {score}) — manual contact needed")
        else:
            log(f"  ⏭ Already queued: {company.get('company_name','')})")
    if no_email_count:
        log(f"  ℹ {no_email_count} companies queued without email — check Hunter.io quota or find contacts manually")

    # ── Phase 4: Queue due follow-ups ──────────────────────────────────────
    log("Phase 4: Checking for due follow-ups…")
    followup_count = 0
    for entry in get_due_followups():
        company_mock = {
            "company_name": entry.get("company",""),
            "description" : "",
            "fit_reason"  : "",
        }
        contact_mock = {"name": "", "email": entry.get("email","")}
        body = generate_followup_email(
            client, company_mock, contact_mock, entry.get("subject","")
        )
        if body and entry.get("email"):
            item = {
                "id"           : str(uuid.uuid4()),
                "type"         : "followup",
                "company_name" : entry.get("company",""),
                "website"      : entry.get("website",""),
                "vertical"     : "",
                "contact_name" : "",
                "contact_email": entry.get("email",""),
                "subject"      : f"Following up: {entry.get('subject','')}",
                "body"         : body,
                "queued_date"  : datetime.now().strftime("%Y-%m-%d %H:%M"),
                "status"       : "pending",
                "sent_date"    : None,
            }
            if add_to_queue(item):
                followup_count += 1
                log(f"  ✓ Follow-up queued: {entry.get('company','')}")

    # ── Phase 5: Send notification email to self ───────────────────────────
    log("Phase 5: Sending notification email…")
    with_email    = initial_count - no_email_count
    notif_subject = (f"EyeClick Daily Batch Ready: "
                     f"{initial_count} companies + {followup_count} follow-up(s)")
    notif_body = (
        f"Good morning!\n\n"
        f"Today's outreach batch is ready for your review:\n\n"
        f"  • {with_email} companies with email — ready to send\n"
        f"  • {no_email_count} companies queued without email — need manual contact\n"
        f"  • {followup_count} follow-up email(s)\n\n"
        + (f"NOTE: {no_email_count} companies had no email found.\n"
           f"This usually means Hunter.io quota is exhausted (check hunter.io dashboard)\n"
           f"or these companies are not in Hunter's database.\n\n"
           if no_email_count else "")
        + f"Open the app and go to the Outreach Queue tab to review and send:\n"
          f"{APP_URL}\n\n"
          f"---\nThis message was sent automatically by EyeClick Daily Worker."
    )
    ok = send_gmail(
        to=secrets["GMAIL_USER"],
        subject=notif_subject,
        body=notif_body,
        signature="",
        gmail_user=secrets["GMAIL_USER"],
        gmail_app_password=secrets["GMAIL_APP_PASSWORD"],
    )
    if ok:
        log(f"  ✓ Notification sent to {secrets['GMAIL_USER']}")
    else:
        log("  ✗ Notification email failed — check GMAIL_USER / GMAIL_APP_PASSWORD")

    log(f"=== Done: {initial_count} initial + {followup_count} follow-ups queued ===")

if __name__ == "__main__":
    run()
