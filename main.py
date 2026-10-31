import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routes.auth_routes import router as auth_router
from routes.student_routes import router as student_router
from routes.admin_routes import router as admin_router

app = FastAPI(
    title=settings.APP_NAME,
    description="Student Assignment Management System with Google OpenID, Drive Uploads & Google Sheets Metadata Tracking.",
    version="2.0.0",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Template Engine
templates = Jinja2Templates(directory="templates")

# Include Modular Routers
app.include_router(auth_router)
app.include_router(student_router)
app.include_router(admin_router)

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Unified Student & Admin Login Page (Google SSO + Password)."""
    return templates.TemplateResponse(request=request, name="login.html", context={"app_name": settings.APP_NAME})

@app.get("/student/dashboard", response_class=HTMLResponse)
async def student_dashboard_page(request: Request):
    """Student Workspace with live timer, .ipynb upload dropzone, and evaluation ledger."""
    return templates.TemplateResponse(request=request, name="student_dashboard.html", context={"app_name": settings.APP_NAME})

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request):
    """Instructor Control Center for Aman Sah (amansah1717@gmail.com)."""
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context={"app_name": settings.APP_NAME})

@app.get("/health")
async def health_check():
    """Health check endpoint for Render service monitoring."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "google_client_id_loaded": bool(settings.GOOGLE_CLIENT_ID),
        "admin_email": settings.ADMIN_EMAIL,
        "google_sheet_id": settings.GOOGLE_SHEET_ID,
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting {settings.APP_NAME} on http://localhost:{port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
