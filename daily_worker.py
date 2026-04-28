#!/usr/bin/env python3
"""
daily_worker.py — Daily prospecting automation via Windows Task Scheduler.
Finds prospects, enriches contacts, saves to daily_runs/YYYY-MM-DD.json,
then commits and pushes state files to GitHub automatically.

══════════════════════════════════════════════════════
WINDOWS TASK SCHEDULER SETUP
══════════════════════════════════════════════════════

GUI method:
  1. Open Task Scheduler  (Start → search "Task Scheduler")
  2. Action → Create Basic Task
  3. Name:     EyeClick Daily Worker
  4. Trigger:  Daily  at 08:00 (or preferred time)
  5. Action:   Start a program
       Program/script : python
       Arguments      : C:\\path\\to\\eyeclick-reseller-finder\\daily_worker.py >> C:\\path\\to\\eyeclick-reseller-finder\\worker_log.txt 2>&1
       Start in       : C:\\path\\to\\eyeclick-reseller-finder
  6. Finish → check "Open properties dialog" → tick "Run whether user is logged on or not"

Command-line method (run once as Administrator):
  schtasks /create /tn "EyeClickDailyWorker" /sc daily /st 08:00 /f ^
    /tr "cmd /c python C:\\path\\to\\eyeclick-reseller-finder\\daily_worker.py >> C:\\path\\to\\eyeclick-reseller-finder\\worker_log.txt 2>&1"

Test run (no scheduling):
  cd C:\\path\\to\\eyeclick-reseller-finder
  python daily_worker.py

══════════════════════════════════════════════════════
SECRETS
══════════════════════════════════════════════════════
API keys are read from .streamlit/secrets.toml in the project folder.
Required keys:
  SERPER_API_KEY, GEMINI_API_KEY (or ANTHROPIC_API_KEY),
  HUNTER_API_KEY, APOLLO_API_KEY, SNOV_CLIENT_ID, SNOV_CLIENT_SECRET,
  PROSPEO_API_KEY

══════════════════════════════════════════════════════
GIT PUSH
══════════════════════════════════════════════════════
After each run the script commits and pushes:
  - daily_runs/YYYY-MM-DD.json   (today's prospects)
  - seen_companies.json          (dedup log)
  - outreach_queue.json          (pending emails)
  - sent_log.json                (email history)

Requires git to be installed and the repo already cloned + authenticated
(e.g. via GitHub Desktop, git credential manager, or SSH key).
If push fails the results are still saved locally — error is logged only.
"""

import os, sys, pathlib, json, time, itertools
from datetime import datetime

os.chdir(pathlib.Path(__file__).parent)

from backend import (
    serper_search, analyse_companies, enrich_contact, validate_website,
    is_recently_seen, is_flagged_wrong_industry, is_blocked,
    add_to_seen_log, make_llm_client,
    QUERY_TEMPLATES, DEFAULT_BLOCKED,
)

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def load_secrets_from_toml() -> dict:
    """Load secrets from .streamlit/secrets.toml for local testing fallback."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # Python < 3.11

    secrets_path = pathlib.Path(".streamlit/secrets.toml")
    if not secrets_path.exists():
        return {}

    try:
        with open(secrets_path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        log(f"WARNING: Could not load secrets.toml: {e}")
        return {}

def get_secret(key: str, fallback: str = "") -> str:
    """Get a secret from environment variables, fall back to secrets.toml for local testing."""
    env_value = os.getenv(key)
    if env_value:
        return env_value

    # Fallback to secrets.toml for local testing
    if not hasattr(get_secret, "_secrets_cache"):
        get_secret._secrets_cache = load_secrets_from_toml()

    return get_secret._secrets_cache.get(key, fallback)

def git_push(today: str):
    """Stage state files, commit, and push to origin main.
    Logs errors but never raises — a git failure must not crash the worker."""
    import subprocess

    files_to_add = [
        f"daily_runs/{today}.json",
        "seen_companies.json",
        "outreach_queue.json",
        "sent_log.json",
    ]

    def _run(args: list) -> tuple[bool, str]:
        r = subprocess.run(["git"] + args, capture_output=True, text=True)
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    log("[git] Staging files…")
    ok, out = _run(["add"] + files_to_add)
    if not ok:
        log(f"[git] WARNING: git add failed: {out}")

    ok, out = _run(["commit", "-m", f"Daily run: {today}"])
    if not ok:
        if "nothing to commit" in out.lower():
            log("[git] Nothing new to commit — files unchanged since last run")
        else:
            log(f"[git] WARNING: git commit failed: {out}")
        return

    log("[git] Pushing to origin main…")
    ok, out = _run(["push", "origin", "main"])
    if ok:
        log("[git] ✅ Push successful")
    else:
        log(f"[git] ⚠ Push failed (results saved locally): {out}")


def write_daily_run(final: list, prefix: str = "") -> str:
    """Write final list to daily_runs/YYYY-MM-DD.json with debug logging.
    Returns the path of the file written, or empty string on failure."""
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = f"daily_runs/{today}.json"
    cwd = os.getcwd()

    log(f"{prefix}DEBUG: Current working directory: {cwd}")
    log(f"{prefix}DEBUG: Number of companies in final list: {len(final)}")
    log(f"{prefix}DEBUG: About to call os.makedirs('daily_runs', exist_ok=True)")

    try:
        os.makedirs("daily_runs", exist_ok=True)
        log(f"{prefix}DEBUG: ✓ os.makedirs completed")
        log(f"{prefix}DEBUG: daily_runs/ exists: {os.path.isdir('daily_runs')}")
    except Exception as e:
        log(f"{prefix}ERROR: os.makedirs failed: {type(e).__name__}: {e}")
        return ""

    log(f"{prefix}DEBUG: About to write to: {os.path.abspath(output_file)}")

    try:
        with open(output_file, "w") as f:
            json.dump(final, f, indent=2)
        log(f"{prefix}DEBUG: ✓ json.dump completed")

        # Verify the file actually exists and has content
        if os.path.exists(output_file):
            size = os.path.getsize(output_file)
            log(f"{prefix}DEBUG: ✓ File exists at {os.path.abspath(output_file)} ({size} bytes)")
        else:
            log(f"{prefix}ERROR: File does not exist after write!")
            return ""
        return output_file
    except Exception as e:
        log(f"{prefix}ERROR: json.dump failed: {type(e).__name__}: {e}")
        return ""

def run():
    log("=== EyeClick Daily Worker starting ===")

    num_results = int(os.getenv("NUM_RESULTS", "10"))
    region_label = os.getenv("REGION", "🌍  Worldwide")
    region_kw = ""

    serper_api_key     = get_secret("SERPER_API_KEY")
    gemini_api_key     = get_secret("GEMINI_API_KEY")
    anthropic_api_key  = get_secret("ANTHROPIC_API_KEY")
    hunter_api_key     = get_secret("HUNTER_API_KEY")
    apollo_api_key     = get_secret("APOLLO_API_KEY")
    snov_client_id     = get_secret("SNOV_CLIENT_ID")
    snov_client_secret = get_secret("SNOV_CLIENT_SECRET")
    prospeo_api_key    = get_secret("PROSPEO_API_KEY")

    if not serper_api_key:
        log("ERROR: SERPER_API_KEY not set (env var or secrets.toml)")
        return False

    if not gemini_api_key and not anthropic_api_key:
        log("ERROR: GEMINI_API_KEY or ANTHROPIC_API_KEY required")
        return False

    email_keys = {
        "hunter_api_key"    : hunter_api_key,
        "apollo_api_key"    : apollo_api_key,
        "snov_client_id"    : snov_client_id,
        "snov_client_secret": snov_client_secret,
        "prospeo_api_key"   : prospeo_api_key,
    }

    client = make_llm_client(gemini_api_key, anthropic_api_key)

    verticals = ["Seniors", "Education", "Entertainment"]
    all_companies = []
    seen_sites = set()
    blocked = list(DEFAULT_BLOCKED)

    log(f"Target: {num_results} companies across {verticals}")
    log(f"Region: {region_label}")

    v_cycle = itertools.cycle(verticals)
    q_pool = {v: [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
              for v in verticals}
    attempt = 0

    while len(all_companies) < num_results and attempt < 40:
        v = next(v_cycle)
        if not q_pool[v]:
            q_pool[v] = [q.format(region=region_kw).strip() for q in QUERY_TEMPLATES[v]]
        query = q_pool[v].pop(0)
        attempt += 1

        log(f"[{v}] Query: {query}")
        results = serper_search(query, 6, serper_api_key)

        if not results:
            log(f"[{v}] No results")
            continue

        companies = analyse_companies(client, results, v, query, region_label, blocked)
        new = [c for c in companies
               if c.get("website","") not in seen_sites
               and not is_recently_seen(c.get("website",""), 30)
               and not is_blocked(c.get("country",""), v, blocked)
               and not is_flagged_wrong_industry(c.get("website",""))]

        for c in new:
            seen_sites.add(c.get("website",""))
        all_companies.extend(new)
        log(f"[{v}] Added {len(new)} companies ({len(all_companies)}/{num_results})")
        time.sleep(0.8)

    final = all_companies[:num_results]
    log(f"Enriching {len(final)} companies…")

    for i, company in enumerate(final):
        log(f"[{i+1}/{len(final)}] {company.get('company_name','')}")
        company["contact"] = enrich_contact(client, company, serper_api_key, email_keys)
        company["website_ok"] = validate_website(company.get("website",""))
        time.sleep(0.6)

    log("=== Phase 3: Writing daily_runs JSON file ===")
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = write_daily_run(final, prefix="[main] ")
    if output_file:
        log(f"✅ Done! {len(final)} prospects saved to {output_file}")
    else:
        log("⚠ Main write failed — guaranteed write below will retry")
    add_to_seen_log(final)

    log("=== Phase 4: Committing and pushing to GitHub ===")
    git_push(today)

    return True

if __name__ == "__main__":
    # Wrap in try/except + guaranteed write so we ALWAYS produce a daily_runs file
    final_companies = []
    success = False
    try:
        success = run()
    except Exception as e:
        log(f"FATAL ERROR in run(): {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # GUARANTEED WRITE — even if run() crashed or returned no companies
    log("=== Guaranteed write at script end ===")
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = f"daily_runs/{today}.json"
    if not os.path.exists(output_file):
        log(f"[guaranteed] No file at {output_file} — writing empty list as marker")
        write_daily_run(final_companies, prefix="[guaranteed] ")
        git_push(today)
    else:
        log(f"[guaranteed] File already exists at {output_file} — skipping")

    sys.exit(0 if success else 1)
