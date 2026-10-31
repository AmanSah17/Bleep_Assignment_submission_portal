from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from typing import Optional
from services.auth_service import require_student
from services.google_service import google_service

router = APIRouter(prefix="/api/student", tags=["Student Portal"])

ASSIGNMENTS = [
    {
        "project_id": "P01",
        "title": "Project_01_EDA",
        "description": "Exploratory Data Analysis: Data cleaning, univariate/bivariate analysis, outliers, and visualization.",
        "allowed_duration_minutes": 120,
        "max_marks": 100,
    },
    {
        "project_id": "P02",
        "title": "Project_02_ML",
        "description": "Supervised Machine Learning: Feature engineering, model training, cross-validation, and metrics.",
        "allowed_duration_minutes": 180,
        "max_marks": 100,
    },
    {
        "project_id": "P03",
        "title": "Project_03_DeepLearning",
        "description": "Neural Networks & CUDA: PyTorch training pipeline, GPU tensor operations, and performance tuning.",
        "allowed_duration_minutes": 240,
        "max_marks": 100,
    }
]

@router.get("/me")
async def get_my_profile(user: dict = Depends(require_student)):
    """Retrieve logged-in student's identity."""
    student_id = user.get("student_id")
    email = user.get("sub")
    name = user.get("name")
    
    student_record = await google_service.get_student_by_email(email)
    return {
        "student_id": student_id or (student_record.get("student_id") if student_record else "N/A"),
        "name": name,
        "email": email,
        "drive_folder_id": student_record.get("drive_folder_id") if student_record else None,
    }

@router.get("/dashboard-data")
async def get_student_dashboard_data(user: dict = Depends(require_student)):
    """Retrieve all available projects, live state, timeline events, and marks."""
    student_id = user.get("student_id")
    student_name = user.get("name")
    
    # Enrich project states
    enriched_projects = []
    for p in ASSIGNMENTS:
        state = await google_service.get_or_create_project_state(
            student_id=student_id,
            student_name=student_name,
            project_title=p["title"],
            duration_minutes=p["allowed_duration_minutes"],
        )
        enriched = p.copy()
        enriched["state"] = state
        enriched_projects.append(enriched)

    timeline_events = await google_service.get_audit_events(student_id=student_id)
    
    return {
        "student": {
            "student_id": student_id,
            "name": student_name,
            "email": user.get("sub"),
        },
        "projects": enriched_projects,
        "timeline_events": timeline_events,
    }

@router.post("/timer/start")
async def start_project_timer(
    project_title: str = Form(...),
    user: dict = Depends(require_student),
):
    """
    Tracks project selection & start time:
    Starts timer, calculates deadline, logs PROJECT_SELECTED and TIMER_STARTED events.
    """
    student_id = user.get("student_id")
    student_name = user.get("name")

    # Find project duration
    duration = 120
    for p in ASSIGNMENTS:
        if p["title"] == project_title:
            duration = p["allowed_duration_minutes"]
            break

    state = await google_service.start_project_timer(
        student_id=student_id,
        student_name=student_name,
        project_title=project_title,
        duration_minutes=duration,
    )
    return {"status": "success", "state": state}

@router.post("/submit")
async def submit_assignment_notebook(
    project_title: str = Form(...),
    student_remarks: str = Form(""),
    file: UploadFile = File(...),
    user: dict = Depends(require_student),
):
    """
    Handles notebook uploads and resubmissions:
    - Automatically streams notebook to student's dedicated folder in Google Drive.
    - Tracks versioning (v1, v2, v3).
    - Appends student remarks.
    - Logs NOTEBOOK_UPLOADED / NOTEBOOK_RESUBMITTED events with drive links.
    """
    student_id = user.get("student_id")
    student_name = user.get("name")

    if not file.filename.endswith(".ipynb") and not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Please upload a Jupyter Notebook (.ipynb) or archive (.zip)."
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    # Get student's personal Google Drive folder
    student_folder_id = await google_service.get_or_create_student_folder(student_id, student_name)

    # Get current project state to compute version
    current_state = await google_service.get_or_create_project_state(student_id, student_name, project_title)
    next_version = current_state["current_version"] + 1
    version_tag = f"v{next_version}"
    clean_filename = f"{student_id}_{project_title}_{version_tag}.ipynb"

    # Upload to Admin's Google Drive
    drive_upload = await google_service.upload_notebook_to_drive(
        file_bytes=file_bytes,
        filename=clean_filename,
        student_folder_id=student_folder_id,
        project_title=project_title,
    )

    # Update project state & audit log
    updated_state = await google_service.record_submission(
        student_id=student_id,
        student_name=student_name,
        project_title=project_title,
        drive_file_id=drive_upload.get("file_id", ""),
        drive_file_url=drive_upload.get("web_view_url", ""),
        student_remarks=student_remarks,
    )

    return {
        "status": "success",
        "message": f"Notebook successfully submitted as {version_tag}!",
        "version": version_tag,
        "state": updated_state,
        "drive_url": drive_upload.get("web_view_url"),
    }
