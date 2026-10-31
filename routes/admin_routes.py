from fastapi import APIRouter, Depends, Form, HTTPException, status
from typing import Optional, List
import json
from config import settings
from services.auth_service import require_admin, generate_student_password, get_password_hash
from services.google_service import google_service

router = APIRouter(prefix="/api/admin", tags=["Admin Portal"])


@router.get("/overview")
async def get_admin_overview(admin: dict = Depends(require_admin)):
    """Fetch administrative metrics, integration status, and pending reviews."""
    students = await google_service.get_all_students()
    project_states = await google_service.get_all_project_states()
    all_events = await google_service.get_audit_events()

    graded_count = sum(1 for s in project_states if s.get("status") in ["GRADED", "COMPLETED"])
    submitted_count = sum(1 for s in project_states if s.get("status") in ["SUBMITTED", "RESUBMITTED"])
    in_progress_count = sum(1 for s in project_states if s.get("status") == "IN_PROGRESS")

    return {
        "admin_email": admin.get("sub"),
        "admin_name": admin.get("name", "Aman Sah"),
        "google_connected": google_service.is_google_connected(),
        "total_students": len(students),
        "in_progress": in_progress_count,
        "awaiting_grading": submitted_count,
        "graded": graded_count,
        "total_events_logged": len(all_events),
    }


@router.get("/students")
async def list_students(admin: dict = Depends(require_admin)):
    """List all students registered in the database/sheet."""
    students = await google_service.get_all_students()
    return {"students": students}


@router.post("/students/generate-passwords")
async def generate_passwords_for_students(admin: dict = Depends(require_admin)):
    """
    Bulk generates secure passwords for all students, hashes them with bcrypt,
    and updates Google Sheets with temp_password and password_hash.
    """
    students = await google_service.get_all_students()
    updated_students = []

    for s in students:
        temp_pass = generate_student_password(length=10)
        p_hash = get_password_hash(temp_pass)

        s["temp_password"] = temp_pass
        s["password_hash"] = p_hash
        updated_students.append(s)

    await google_service.save_students_roster(updated_students)

    return {
        "status": "success",
        "message": f"Generated new secure passwords for {len(updated_students)} students.",
        "students": [
            {
                "student_id": s["student_id"],
                "full_name": s["full_name"],
                "email": s["email"],
                "temp_password": s["temp_password"],
            }
            for s in updated_students
        ],
    }


@router.get("/projects")
async def list_all_project_states(admin: dict = Depends(require_admin)):
    """Returns live state of every student's project: status, timer, marks, remarks, and extensions."""
    states = await google_service.get_all_project_states()
    return {"project_states": states}


@router.get("/audit-events")
async def list_audit_events(
    student_id: Optional[str] = None,
    project_title: Optional[str] = None,
    admin: dict = Depends(require_admin),
):
    """Retrieve full audit log across all students or filtered by student/project."""
    events = await google_service.get_audit_events(student_id=student_id, project_title=project_title)
    return {"events": events}


@router.post("/extend-deadline")
async def extend_deadline(
    student_id: str = Form(...),
    project_title: str = Form(...),
    extension_minutes: int = Form(...),
    reason: str = Form(...),
    admin: dict = Depends(require_admin),
):
    """Grant deadline extension to a student, adjusting timer and logging the event."""
    admin_name = admin.get("name", "Aman Sah")
    updated_state = await google_service.extend_deadline(
        student_id=student_id,
        project_title=project_title,
        extension_minutes=extension_minutes,
        admin_note=reason,
        admin_name=admin_name,
    )
    return {
        "status": "success",
        "message": f"Extended deadline by {extension_minutes} minutes.",
        "state": updated_state,
    }


@router.post("/grade")
async def grade_submission(
    student_id: str = Form(...),
    project_title: str = Form(...),
    marks: str = Form(...),
    instructor_remarks: str = Form(...),
    mark_as_completed: bool = Form(False),
    admin: dict = Depends(require_admin),
):
    """
    Evaluates student project:
    - Sets marks and instructor feedback.
    - Preserves evaluation history for resubmissions.
    - Updates status to GRADED or COMPLETED.
    - Appends event to Audit Trail.
    """
    admin_name = admin.get("name", "Aman Sah")
    new_status = "COMPLETED" if mark_as_completed else "GRADED"

    updated_state = await google_service.evaluate_project(
        student_id=student_id,
        project_title=project_title,
        marks=int(marks) if marks.isdigit() else 0,
        instructor_remarks=instructor_remarks,
        new_status=new_status,
        admin_name=admin_name,
    )

    return {
        "status": "success",
        "message": "Evaluation and instructor feedback recorded successfully!",
        "state": updated_state,
    }


@router.post("/change-status")
async def change_status(
    student_id: str = Form(...),
    project_title: str = Form(...),
    new_status: str = Form(...),
    reason: str = Form(""),
    admin: dict = Depends(require_admin),
):
    """Change status directly (e.g. UNDER_REVIEW, REOPENED, COMPLETED)."""
    updated_state = await google_service.update_project_status(
        student_id=student_id,
        project_title=project_title,
        new_status=new_status,
        reason=reason,
        actor=admin.get("name", "Aman Sah"),
    )
    return {"status": "success", "state": updated_state}


@router.post("/set-token")
async def set_google_token(
    refresh_token: str = Form(...),
    admin: dict = Depends(require_admin),
):
    """Allows admin to directly store a Google refresh token."""
    clean_token = refresh_token.strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")

    settings.GOOGLE_REFRESH_TOKEN = clean_token
    token_data = {
        "token": None,
        "refresh_token": clean_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "scopes": [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
    }
    with open(settings.TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

    google_service._cached_creds = None
    is_valid = google_service.is_google_connected()
    return {
        "status": "success",
        "message": "Refresh token saved successfully!",
        "google_connected": is_valid,
    }
