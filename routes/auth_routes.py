from fastapi import APIRouter, Request, Response, Form, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from config import settings
from services.auth_service import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token,
)
from services.google_service import google_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_clean_redirect_uri(request: Request, path: str) -> str:
    """
    Computes a clean redirect URI that correctly handles reverse proxies (Render, Cloudflare, etc.).
    Always forces https for *.onrender.com.
    """
    if settings.BASE_URL and "localhost" not in settings.BASE_URL:
        return f"{settings.BASE_URL.rstrip('/')}{path}"

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    if "onrender.com" in str(host):
        proto = "https"
    return f"{proto}://{host}{path}"


@router.post("/login")
async def login_with_email_password(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
):
    """
    Direct Email + Password authentication for:
    1. Admin (Aman Sah)
    2. Students with generated or assigned passwords
    """
    clean_email = email.strip().lower()

    # 1. Check if Admin Login
    if clean_email == settings.ADMIN_EMAIL.lower():
        if password == settings.ADMIN_PASSWORD:
            token = create_access_token({"sub": clean_email, "role": "admin", "name": "Aman Sah (Admin)"})
            response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=86400)
            return {"status": "success", "role": "admin", "redirect_url": "/admin/dashboard", "token": token}
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials.")

    # 2. Check Student Login against Google Sheets roster
    student = await google_service.get_student_by_email(clean_email)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email address not found in registered student database. Please contact instructor Aman Sah.",
        )

    # Check bcrypt password_hash OR temp_password
    valid = False
    stored_hash = student.get("password_hash")
    temp_pass = student.get("temp_password")

    if stored_hash and verify_password(password, stored_hash):
        valid = True
    elif temp_pass and password == temp_pass:
        valid = True

    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect student password.")

    token = create_access_token({
        "sub": clean_email,
        "role": "student",
        "student_id": student.get("student_id"),
        "name": student.get("full_name"),
    })
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=86400)
    return {"status": "success", "role": "student", "redirect_url": "/student/dashboard", "token": token}


@router.get("/google")
async def login_with_google(request: Request):
    """Initiates Google OpenID Connect flow for students and instructor."""
    redirect_uri = get_clean_redirect_uri(request, "/auth/google/callback")
    flow = google_service.create_flow(
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(prompt="select_account")
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_auth_callback(request: Request, code: str):
    """
    Callback for Google OpenID Connect:
    1. Verifies Google identity token.
    2. Checks whether email exists in student database / Google Sheet.
    3. Issues JWT and logs student directly into their dashboard.
    """
    redirect_uri = get_clean_redirect_uri(request, "/auth/google/callback")
    try:
        flow = google_service.create_flow(
            scopes=[
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ],
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Verify the ID Token using Google Auth
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
        user_email = id_info.get("email", "").lower()
        user_name = id_info.get("name", "")

        # A: Check if Admin
        if user_email == settings.ADMIN_EMAIL.lower():
            token = create_access_token({"sub": user_email, "role": "admin", "name": user_name or "Aman Sah"})
            resp = RedirectResponse(url="/admin/dashboard")
            resp.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=86400)
            return resp

        # B: Check if Registered Student
        student = await google_service.get_student_by_email(user_email)
        if not student:
            return RedirectResponse(url="/?error=unregistered_email&email=" + user_email)

        token = create_access_token({
            "sub": user_email,
            "role": "student",
            "student_id": student.get("student_id"),
            "name": student.get("full_name") or user_name,
        })
        resp = RedirectResponse(url="/student/dashboard")
        resp.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=86400)
        return resp

    except Exception as e:
        print(f"Google Callback Error: {e}")
        return RedirectResponse(url=f"/?error=oauth_failed&detail={str(e)}")


@router.get("/admin/oauth-drive")
async def admin_oauth_drive(request: Request):
    """Admin endpoint to authorize full Drive & Sheets offline access."""
    redirect_uri = get_clean_redirect_uri(request, "/auth/admin/oauth-callback")
    auth_url = google_service.get_admin_auth_url(redirect_uri=redirect_uri)
    return RedirectResponse(url=auth_url)


@router.get("/admin/oauth-callback")
async def admin_oauth_callback(request: Request, code: str):
    """Captures and caches Admin's offline refresh token for Drive/Sheets operations."""
    redirect_uri = get_clean_redirect_uri(request, "/auth/admin/oauth-callback")
    try:
        creds = google_service.exchange_code_for_tokens(code=code, redirect_uri=redirect_uri)
        rt = creds.refresh_token or ""
        return RedirectResponse(url=f"/admin/dashboard?google_connected=true&rt={rt}")
    except Exception as e:
        return RedirectResponse(url=f"/admin/dashboard?google_error={str(e)}")


@router.get("/logout")
async def logout():
    """Clear cookies and redirect to home."""
    resp = RedirectResponse(url="/")
    resp.delete_cookie(key="access_token")
    return resp
