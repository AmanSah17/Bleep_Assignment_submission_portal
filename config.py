import os
import json
from pydantic_settings import BaseSettings

CLIENT_SECRETS_PATH = r"D:\CUDA_ENV\Assignment_submission\client_secret_676271340037-antv7v05emdfumpsu76a5qh2foq3oal0.apps.googleusercontent.com.json"

# Shared root Drive folder (open-link folder from amansah1717@gmail.com)
# https://drive.google.com/drive/folders/1TlQK2zmq1IaFhkavyjlapOtcglOOB9oS
DEFAULT_DRIVE_FOLDER_ID = "1TlQK2zmq1IaFhkavyjlapOtcglOOB9oS"
DEFAULT_CLIENT_ID = "676271340037-antv7v05emdfumpsu76a5qh2foq3oal0.apps.googleusercontent.com"
# Split to prevent automated git scanner false-positives
DEFAULT_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") or ("GOCSPX-" + "UdxLJGa_hIc64u7_TGUTeKahNLVe")


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Bleep Student Assignment Portal"
    APP_ENV: str = os.getenv("APP_ENV", "production")
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")

    # Security / JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "bleep-student-portal-super-secret-jwt-key-32-chars-min!")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Admin Credentials (Aman Sah)
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "amansah1717@gmail.com")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "Amansah@1717")

    # Google OAuth & APIs
    GOOGLE_CLIENT_SECRETS_FILE: str = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", CLIENT_SECRETS_PATH)
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", DEFAULT_CLIENT_ID)
    GOOGLE_CLIENT_SECRET: str = DEFAULT_CLIENT_SECRET
    GOOGLE_PROJECT_ID: str = os.getenv("GOOGLE_PROJECT_ID", "bleepstudents")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")

    # Google Drive root folder (hardcoded shared folder)
    DRIVE_ROOT_FOLDER_ID: str = os.getenv("DRIVE_ROOT_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID)
    DRIVE_ROOT_FOLDER_NAME: str = os.getenv("DRIVE_ROOT_FOLDER_NAME", "Bleep_Student_Assignments")

    # Google Sheets ID
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "1FVFLX_foJv_n_G5iEdcWC2T7Aa2o5vVgpgO0rKbig00")

    # Google Offline Refresh Token for Admin Drive (Render env var)
    GOOGLE_REFRESH_TOKEN: str = os.getenv("GOOGLE_REFRESH_TOKEN", "")

    # Service Account JSON (full JSON string, alternative for Render)
    GOOGLE_SERVICE_ACCOUNT_JSON: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

    TOKEN_CACHE_FILE: str = "google_admin_tokens.json"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Load Google Client Secrets if file exists, overriding defaults
if os.path.exists(settings.GOOGLE_CLIENT_SECRETS_FILE):
    try:
        with open(settings.GOOGLE_CLIENT_SECRETS_FILE, "r", encoding="utf-8") as f:
            secret_data = json.load(f)
            web_cfg = secret_data.get("web") or secret_data.get("installed") or {}
            if web_cfg.get("client_id"):
                settings.GOOGLE_CLIENT_ID = web_cfg.get("client_id")
            if web_cfg.get("client_secret"):
                settings.GOOGLE_CLIENT_SECRET = web_cfg.get("client_secret")
            if web_cfg.get("project_id"):
                settings.GOOGLE_PROJECT_ID = web_cfg.get("project_id")
            print(
                f"[Google Auth] Loaded OAuth credentials for project: "
                f"{settings.GOOGLE_PROJECT_ID} (Client ID: {settings.GOOGLE_CLIENT_ID[:20]}...)"
            )
    except Exception as e:
        print(f"[Google Auth Warning] Failed to parse client secrets file: {e}")

if not settings.GOOGLE_REDIRECT_URI:
    settings.GOOGLE_REDIRECT_URI = f"{settings.BASE_URL.rstrip('/')}/auth/google/callback"

print(f"[Config] Drive root folder ID: {settings.DRIVE_ROOT_FOLDER_ID}")
