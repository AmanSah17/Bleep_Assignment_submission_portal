"""
Run this script ONCE locally to get a Google Drive refresh token.
It will open your browser → sign in as amansah1717@gmail.com → approve Drive + Sheets access.
The refresh token is then saved to google_admin_tokens.json AND printed to the console.

Usage:
  cd D:\CUDA_ENV\Assignment_submission
  & "D:\CUDA_ENV\CUDA_ENV\Scripts\python.exe" get_refresh_token.py
"""
import json
import os
import webbrowser
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_SECRETS_FILE = r"D:\CUDA_ENV\Assignment_submission\client_secret_676271340037-antv7v05emdfumpsu76a5qh2foq3oal0.apps.googleusercontent.com.json"
TOKEN_FILE = "google_admin_tokens.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

def main():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"ERROR: Client secrets file not found at:\n  {CLIENT_SECRETS_FILE}")
        return

    print("=" * 60)
    print("Bleep Portal — Google Drive Authorization")
    print("=" * 60)
    print("Sign in as: amansah1717@gmail.com")
    print("Scopes: Drive (full) + Sheets + OpenID")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
    )

    # Run local server on port 8080 to capture the callback
    creds = flow.run_local_server(
        port=8080,
        prompt="consent",
        access_type="offline",
    )

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

    print()
    print("=" * 60)
    print(f"SUCCESS! Token saved to: {TOKEN_FILE}")
    print()
    print("REFRESH TOKEN (copy this for Render env var GOOGLE_REFRESH_TOKEN):")
    print()
    print(f"  {creds.refresh_token}")
    print()
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Add to Render Dashboard -> Environment -> GOOGLE_REFRESH_TOKEN")
    print("  2. The local server will now automatically use google_admin_tokens.json")
    print("  3. File uploads will go to:")
    print("     https://drive.google.com/drive/folders/1TlQK2zmq1IaFhkavyjlapOtcglOOB9oS")


if __name__ == "__main__":
    main()
