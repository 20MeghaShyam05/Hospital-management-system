"""
One-time Google OAuth2 setup script.
Run this ONCE from CMD to authenticate and generate token.json.

Usage:
    python google_auth_setup.py
"""
import os
import sys

# Ensure we can import from project root
sys.path.insert(0, os.path.dirname(__file__))

from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def main():
    creds_file = settings.GOOGLE_CREDENTIALS_FILE
    token_file = settings.GOOGLE_TOKEN_FILE

    if not os.path.exists(creds_file):
        print(f"ERROR: '{creds_file}' not found in project root.")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        return

    print(f"Using credentials: {creds_file}")
    print(f"Token will be saved to: {token_file}")
    print()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
    creds = flow.run_local_server(port=8090)

    with open(token_file, "w") as f:
        f.write(creds.to_json())

    print()
    print(f"✅ Authentication successful!")
    print(f"✅ Token saved to: {token_file}")
    print()
    print("You can now start the FastAPI server — Gmail, Drive, and Calendar will work.")


if __name__ == "__main__":
    main()
