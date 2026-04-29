#!/usr/bin/env python3
"""
setup_gmail_auth.py — one-time OAuth2 setup for Gmail draft creation.

Run this once locally:
    python setup_gmail_auth.py

It opens a browser for Google OAuth consent and saves token.json.
After that, daily_worker.py can create Gmail drafts without interaction.

Requirements:
    pip install google-auth-oauthlib google-api-python-client
"""

import pathlib
import sys

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
CREDS_PATH = pathlib.Path("credentials.json")
TOKEN_PATH = pathlib.Path("token.json")


def main():
    if not CREDS_PATH.exists():
        print(f"ERROR: {CREDS_PATH} not found.")
        print("Download it from Google Cloud Console > APIs & Services > Credentials.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib is not installed.")
        print("Run: pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"✓ token.json saved to {TOKEN_PATH.resolve()}")
    print("Gmail OAuth setup complete. daily_worker.py can now create drafts.")


if __name__ == "__main__":
    main()
