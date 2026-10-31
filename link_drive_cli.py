import os
import sys
import json
import urllib.parse
from config import settings
from services.google_service import google_service, SCOPES

def main():
    print("=" * 70)
    print("GOOGLE DRIVE VAULT LINKING UTILITY FOR AMAN SAH")
    print("=" * 70)
    print("This utility authorizes your Google account (amansah1717@gmail.com)")
    print("to create dedicated student folders and store notebook submissions.")
    print("=" * 70)

    # Use the local callback configured in your OAuth Client
    redirect_uri = "http://localhost:8000/auth/admin/oauth-callback"
    flow = google_service.create_flow(scopes=SCOPES, redirect_uri=redirect_uri)
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    print("\n👉 STEP 1: Copy and open this URL in your web browser:\n")
    print(auth_url)
    print("\n" + "-" * 70)
    print("👉 STEP 2: Sign in with amansah1717@gmail.com and click 'Allow'.")
    print("After approving, your browser will redirect to a URL starting with:")
    print("http://localhost:8000/auth/admin/oauth-callback?code=4/0A...")
    print("-" * 70)

    code_input = input("\n👉 STEP 3: Paste the full redirect URL (or just the code parameter) here:\n> ").strip()
    if not code_input:
        print("Error: No input provided.")
        return

    # Extract code if full URL was pasted
    if "code=" in code_input:
        parsed = urllib.parse.urlparse(code_input)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
    else:
        code = code_input

    if not code:
        print("Error: Could not extract authorization code from input.")
        return

    print("\nExchanging code for permanent refresh token...")
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        google_service._save_credentials(creds)
        print("\n" + "=" * 70)
        print("🎉 SUCCESS! GOOGLE DRIVE IS NOW CONNECTED!")
        print("=" * 70)
        print(f"Token cached to: {settings.TOKEN_CACHE_FILE}")
        print(f"Refresh Token: {creds.refresh_token}")
        print("\n👉 IMPORTANT FOR RENDER DEPLOYMENT:")
        print("Copy the Refresh Token above and add it in your Render Dashboard:")
        print("Key:   GOOGLE_REFRESH_TOKEN")
        print(f"Value: {creds.refresh_token}")
        print("=" * 70)
    except Exception as e:
        print(f"Failed to exchange code: {e}")

if __name__ == "__main__":
    main()
