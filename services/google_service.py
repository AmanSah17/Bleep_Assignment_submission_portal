import os
import io
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

class GoogleWorkspaceService:
    def __init__(self):
        self.lock = asyncio.Lock()
        self._cached_creds: Optional[Credentials] = None
        self._root_folder_id: Optional[str] = None
        
        # 1. Mock Student Roster
        self._mock_students: List[Dict[str, Any]] = [
            {
                "student_id": "STU0001",
                "full_name": "Manas M",
                "email": "manas@gmail.com",
                "password_hash": "",
                "temp_password": "Bleep#9x2K",
                "drive_folder_id": "",
                "status": "ACTIVE",
            },
            {
                "student_id": "STU0002",
                "full_name": "Balikarthik S",
                "email": "balikarthik@gmail.com",
                "password_hash": "",
                "temp_password": "Bleep#7m1L",
                "drive_folder_id": "",
                "status": "ACTIVE",
            },
            {
                "student_id": "STU0003",
                "full_name": "Ashika VV",
                "email": "ashika@gmail.com",
                "password_hash": "",
                "temp_password": "Bleep#4n8Q",
                "drive_folder_id": "",
                "status": "ACTIVE",
            },
            {
                "student_id": "STU0004",
                "full_name": "Surya S",
                "email": "surya@gmail.com",
                "password_hash": "",
                "temp_password": "Bleep#3p9Z",
                "drive_folder_id": "",
                "status": "ACTIVE",
            }
        ]

        # 2. Project State Matrix (Tracks Current Status, Timer, Deadline, Marks, Extensions)
        self._project_states: Dict[str, Dict[str, Any]] = {}

        # 3. Append-only Event / Audit Log (Tracks every single activity)
        self._audit_events: List[Dict[str, Any]] = []

    def _state_key(self, student_id: str, project_title: str) -> str:
        return f"{student_id}::{project_title.replace(' ', '_')}"

    def get_client_config(self) -> dict:
        return {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        }

    def create_flow(self, scopes: List[str], redirect_uri: str) -> Flow:
        r"""
        Loads OAuth2 flow directly from client secret JSON:
        D:\CUDA_ENV\Assignment_submission\client_secret_676271340037-antv7v05emdfumpsu76a5qh2foq3oal0.apps.googleusercontent.com.json
        """
        if os.path.exists(settings.GOOGLE_CLIENT_SECRETS_FILE):
            return Flow.from_client_secrets_file(
                settings.GOOGLE_CLIENT_SECRETS_FILE,
                scopes=scopes,
                redirect_uri=redirect_uri,
            )
        return Flow.from_client_config(
            self.get_client_config(),
            scopes=scopes,
            redirect_uri=redirect_uri,
        )

    def get_admin_auth_url(self, redirect_uri: str) -> str:
        flow = self.create_flow(scopes=SCOPES, redirect_uri=redirect_uri)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> Credentials:
        flow = self.create_flow(scopes=SCOPES, redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        self._save_credentials(creds)
        self._cached_creds = creds
        return creds

    def _save_credentials(self, creds: Credentials):
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token or settings.GOOGLE_REFRESH_TOKEN,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        try:
            with open(settings.TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save tokens file: {e}")

    def get_credentials(self) -> Optional[Credentials]:
        if self._cached_creds and self._cached_creds.valid:
            return self._cached_creds

        if os.path.exists(settings.TOKEN_CACHE_FILE):
            try:
                with open(settings.TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    creds = Credentials(
                        token=data.get("token"),
                        refresh_token=data.get("refresh_token") or settings.GOOGLE_REFRESH_TOKEN,
                        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                        client_id=settings.GOOGLE_CLIENT_ID,
                        client_secret=settings.GOOGLE_CLIENT_SECRET,
                        scopes=SCOPES,
                    )
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(GoogleRequest())
                        self._save_credentials(creds)
                    if creds and creds.valid:
                        self._cached_creds = creds
                        return creds
            except Exception as e:
                print(f"Could not load cached tokens: {e}")

        if settings.GOOGLE_REFRESH_TOKEN:
            try:
                creds = Credentials(
                    token=None,
                    refresh_token=settings.GOOGLE_REFRESH_TOKEN,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.GOOGLE_CLIENT_ID,
                    client_secret=settings.GOOGLE_CLIENT_SECRET,
                    scopes=SCOPES,
                )
                creds.refresh(GoogleRequest())
                self._cached_creds = creds
                return creds
            except Exception as e:
                print(f"Could not refresh from env GOOGLE_REFRESH_TOKEN: {e}")

        return None

    def is_google_connected(self) -> bool:
        creds = self.get_credentials()
        return creds is not None and creds.valid

    # ==========================================
    # Google Drive Operations
    # ==========================================
    async def get_or_create_root_folder(self) -> str:
        if self._root_folder_id:
            return self._root_folder_id

        creds = self.get_credentials()
        if not creds:
            return "mock-root-folder-id"

        service = build("drive", "v3", credentials=creds)
        folder_name = settings.DRIVE_ROOT_FOLDER_NAME
        query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and trashed = false"
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            self._root_folder_id = files[0]["id"]
        else:
            file_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            folder = service.files().create(body=file_metadata, fields="id").execute()
            self._root_folder_id = folder.get("id")

        return self._root_folder_id

    async def get_or_create_student_folder(self, student_id: str, student_name: str) -> str:
        creds = self.get_credentials()
        clean_name = f"{student_id}_{student_name.replace(' ', '_')}"
        if not creds:
            return f"mock-folder-{clean_name}"

        root_id = await self.get_or_create_root_folder()
        service = build("drive", "v3", credentials=creds)
        query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{clean_name}' and '{root_id}' in parents and trashed = false"
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        metadata = {
            "name": clean_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_id],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder.get("id")

    async def get_or_create_project_folder(self, student_folder_id: str, project_title: str) -> str:
        creds = self.get_credentials()
        clean_title = project_title.replace(" ", "_")
        if not creds:
            return f"mock-folder-{clean_title}"

        service = build("drive", "v3", credentials=creds)
        query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{clean_title}' and '{student_folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        metadata = {
            "name": clean_title,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [student_folder_id],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder.get("id")

    async def upload_notebook_to_drive(
        self,
        file_bytes: bytes,
        filename: str,
        student_folder_id: str,
        project_title: str,
    ) -> Dict[str, str]:
        creds = self.get_credentials()
        if not creds:
            return {
                "file_id": f"mock-file-id-{filename}",
                "web_view_url": f"https://drive.google.com/file/d/mock-file-{filename}/view",
            }

        project_folder_id = await self.get_or_create_project_folder(student_folder_id, project_title)
        service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": filename,
            "parents": [project_folder_id],
        }
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/x-ipynb+json", resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()

        return {
            "file_id": uploaded.get("id"),
            "web_view_url": uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{uploaded.get('id')}/view",
        }

    # ==========================================
    # Event Logging & Audit Trail Engine
    # ==========================================
    async def log_event(
        self,
        student_id: str,
        student_name: str,
        project_title: str,
        event_type: str,
        description: str,
        actor: str = "STUDENT",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record an immutable event in the audit trail:
        - PROJECT_SELECTED
        - TIMER_STARTED
        - NOTEBOOK_UPLOADED
        - NOTEBOOK_RESUBMITTED
        - DEADLINE_EXTENDED
        - STATUS_CHANGED
        - REMARKS_ADDED
        - MARKS_EVALUATED
        - PROJECT_COMPLETED
        """
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        event_id = f"EVT-{len(self._audit_events) + 1:05d}"
        
        event = {
            "event_id": event_id,
            "student_id": student_id,
            "student_name": student_name,
            "project_title": project_title,
            "event_type": event_type,
            "description": description,
            "actor": actor,
            "timestamp": now_str,
            "metadata": metadata or {},
        }
        self._audit_events.append(event)
        
        # Sync to Google Sheets tab Activity_Audit_Log asynchronously
        asyncio.create_task(self._sync_event_to_sheet(event))
        return event

    async def _sync_event_to_sheet(self, event: Dict[str, Any]):
        creds = self.get_credentials()
        if not creds:
            return
        try:
            service = build("sheets", "v4", credentials=creds)
            row = [
                event["event_id"],
                event["student_id"],
                event["student_name"],
                event["project_title"],
                event["event_type"],
                event["description"],
                event["actor"],
                event["timestamp"],
                json.dumps(event.get("metadata", {})),
            ]
            service.spreadsheets().values().append(
                spreadsheetId=settings.GOOGLE_SHEET_ID,
                range="Activity_Audit_Log!A2:I",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
        except Exception as e:
            print(f"Error syncing event to Google Sheets: {e}")

    async def get_audit_events(self, student_id: Optional[str] = None, project_title: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return event log, optionally filtered by student and project."""
        events = self._audit_events
        if student_id:
            events = [e for e in events if e["student_id"] == student_id]
        if project_title:
            events = [e for e in events if e["project_title"] == project_title]
        return list(reversed(events))  # Newest first

    # ==========================================
    # Project State & Lifecycle Tracking
    # ==========================================
    async def get_or_create_project_state(
        self,
        student_id: str,
        student_name: str,
        project_title: str,
        duration_minutes: int = 120,
    ) -> Dict[str, Any]:
        key = self._state_key(student_id, project_title)
        if key not in self._project_states:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            self._project_states[key] = {
                "student_id": student_id,
                "student_name": student_name,
                "project_title": project_title,
                "status": "NOT_STARTED",  # NOT_STARTED, IN_PROGRESS, SUBMITTED, RESUBMITTED, UNDER_REVIEW, GRADED, COMPLETED
                "timer_start": None,
                "timer_end": None,
                "deadline": None,
                "allowed_duration_minutes": duration_minutes,
                "extension_minutes_total": 0,
                "extension_history": [],
                "current_version": 0,
                "submissions": [],  # List of {version, file_id, file_url, timestamp, remarks}
                "student_remarks_history": [],
                "instructor_remarks_history": [],
                "evaluation_history": [],  # List of {marks, max_marks, remarks, timestamp}
                "latest_marks": None,
                "max_marks": 100,
                "time_spent_minutes": 0,
                "created_at": now_str,
                "updated_at": now_str,
            }
        return self._project_states[key]

    async def start_project_timer(
        self,
        student_id: str,
        student_name: str,
        project_title: str,
        duration_minutes: int = 120,
    ) -> Dict[str, Any]:
        state = await self.get_or_create_project_state(student_id, student_name, project_title, duration_minutes)
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # If already started, return existing timer
        if state["timer_start"] and state["status"] in ["IN_PROGRESS", "SUBMITTED", "RESUBMITTED"]:
            return state

        deadline = now + timedelta(minutes=duration_minutes + state["extension_minutes_total"])
        deadline_str = deadline.strftime("%Y-%m-%d %H:%M:%S")

        state["timer_start"] = now_str
        state["deadline"] = deadline_str
        state["status"] = "IN_PROGRESS"
        state["updated_at"] = now_str

        # Log Events
        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="PROJECT_SELECTED",
            description=f"Student selected project {project_title}.",
            actor="STUDENT",
        )
        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="TIMER_STARTED",
            description=f"Timer started. Deadline set to {deadline_str} ({duration_minutes} minutes).",
            actor="STUDENT",
            metadata={"timer_start": now_str, "deadline": deadline_str},
        )

        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def extend_deadline(
        self,
        student_id: str,
        project_title: str,
        extension_minutes: int,
        reason: str,
        admin_name: str = "Aman Sah",
    ) -> Dict[str, Any]:
        """Grant a deadline extension with instructor reason."""
        student = await self.get_student_by_id(student_id)
        student_name = student["full_name"] if student else "Student"
        state = await self.get_or_create_project_state(student_id, student_name, project_title)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        state["extension_minutes_total"] += extension_minutes
        
        # Recalculate deadline
        if state["timer_start"]:
            start_dt = datetime.strptime(state["timer_start"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            new_deadline = start_dt + timedelta(minutes=state["allowed_duration_minutes"] + state["extension_minutes_total"])
            state["deadline"] = new_deadline.strftime("%Y-%m-%d %H:%M:%S")

        extension_record = {
            "extension_minutes": extension_minutes,
            "reason": reason,
            "granted_by": admin_name,
            "timestamp": now_str,
            "new_deadline": state.get("deadline"),
        }
        state["extension_history"].append(extension_record)
        state["updated_at"] = now_str

        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="DEADLINE_EXTENDED",
            description=f"Deadline extended by {extension_minutes} mins by {admin_name}. Reason: {reason}",
            actor="INSTRUCTOR",
            metadata=extension_record,
        )

        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def record_submission(
        self,
        student_id: str,
        student_name: str,
        project_title: str,
        drive_file_id: str,
        drive_file_url: str,
        student_remarks: str,
    ) -> Dict[str, Any]:
        """Handles both first submission (v1) and resubmissions (v2, v3...)."""
        state = await self.get_or_create_project_state(student_id, student_name, project_title)
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        state["current_version"] += 1
        version_str = f"v{state['current_version']}"
        is_resubmission = state["current_version"] > 1

        # Calculate duration
        duration_mins = 0
        if state["timer_start"]:
            try:
                start_dt = datetime.strptime(state["timer_start"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                duration_mins = max(1, int((now - start_dt).total_seconds() / 60))
            except Exception:
                duration_mins = 0
        state["time_spent_minutes"] = duration_mins
        state["timer_end"] = now_str
        state["status"] = "RESUBMITTED" if is_resubmission else "SUBMITTED"
        state["updated_at"] = now_str

        submission_entry = {
            "version": version_str,
            "file_id": drive_file_id,
            "file_url": drive_file_url,
            "student_remarks": student_remarks,
            "submitted_at": now_str,
            "duration_minutes": duration_mins,
        }
        state["submissions"].append(submission_entry)

        if student_remarks:
            state["student_remarks_history"].append({
                "version": version_str,
                "remarks": student_remarks,
                "timestamp": now_str,
            })

        # Event type
        event_type = "NOTEBOOK_RESUBMITTED" if is_resubmission else "NOTEBOOK_UPLOADED"
        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type=event_type,
            description=f"Notebook {version_str} uploaded to Google Drive. Remarks: {student_remarks or 'None'}",
            actor="STUDENT",
            metadata=submission_entry,
        )

        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def grade_project(
        self,
        student_id: str,
        project_title: str,
        marks: Any,
        instructor_remarks: str,
        new_status: str = "GRADED",
        admin_name: str = "Aman Sah",
    ) -> Dict[str, Any]:
        """Evaluate project, update marks, append to evaluation history, and log status change."""
        student = await self.get_student_by_id(student_id)
        student_name = student["full_name"] if student else "Student"
        state = await self.get_or_create_project_state(student_id, student_name, project_title)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        state["latest_marks"] = marks
        state["status"] = new_status
        state["updated_at"] = now_str

        evaluation_record = {
            "evaluation_round": len(state["evaluation_history"]) + 1,
            "version_evaluated": f"v{state['current_version']}",
            "marks": marks,
            "max_marks": state["max_marks"],
            "instructor_remarks": instructor_remarks,
            "evaluated_by": admin_name,
            "timestamp": now_str,
        }
        state["evaluation_history"].append(evaluation_record)

        if instructor_remarks:
            state["instructor_remarks_history"].append({
                "round": len(state["evaluation_history"]),
                "remarks": instructor_remarks,
                "timestamp": now_str,
            })

        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="MARKS_EVALUATED",
            description=f"Evaluated by {admin_name}: {marks}/{state['max_marks']}. Remarks: {instructor_remarks}",
            actor="INSTRUCTOR",
            metadata=evaluation_record,
        )

        if new_status == "COMPLETED":
            await self.log_event(
                student_id=student_id,
                student_name=student_name,
                project_title=project_title,
                event_type="PROJECT_COMPLETED",
                description="Project marked as COMPLETED.",
                actor="INSTRUCTOR",
            )

        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def update_project_status(
        self,
        student_id: str,
        project_title: str,
        new_status: str,
        reason: str,
        actor: str = "INSTRUCTOR",
    ) -> Dict[str, Any]:
        """Change project status (e.g., UNDER_REVIEW, COMPLETED, REOPENED)."""
        student = await self.get_student_by_id(student_id)
        student_name = student["full_name"] if student else "Student"
        state = await self.get_or_create_project_state(student_id, student_name, project_title)

        old_status = state["status"]
        state["status"] = new_status
        state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="STATUS_CHANGED",
            description=f"Status changed from {old_status} to {new_status}. Note: {reason}",
            actor=actor,
            metadata={"old_status": old_status, "new_status": new_status, "reason": reason},
        )

        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def _sync_state_to_sheet(self, state: Dict[str, Any]):
        """Persist current project state to Google Sheets tab Projects_Status."""
        creds = self.get_credentials()
        if not creds:
            return

        try:
            service = build("sheets", "v4", credentials=creds)
            latest_sub = state["submissions"][-1] if state["submissions"] else {}
            row = [
                state["student_id"],
                state["student_name"],
                state["project_title"],
                state["status"],
                state["timer_start"] or "",
                state["deadline"] or "",
                state["timer_end"] or "",
                state["time_spent_minutes"],
                state["extension_minutes_total"],
                f"v{state['current_version']}",
                latest_sub.get("file_url", ""),
                latest_sub.get("student_remarks", ""),
                state["instructor_remarks_history"][-1]["remarks"] if state["instructor_remarks_history"] else "",
                state["latest_marks"] or "",
                state["max_marks"],
                state["updated_at"],
            ]
            service.spreadsheets().values().append(
                spreadsheetId=settings.GOOGLE_SHEET_ID,
                range="Projects_Status!A2:P",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
        except Exception as e:
            print(f"Error syncing project state to Google Sheets: {e}")

    # ==========================================
    # Student Roster Access
    # ==========================================
    async def get_all_students(self) -> List[Dict[str, Any]]:
        return self._mock_students

    async def get_student_by_id(self, student_id: str) -> Optional[Dict[str, Any]]:
        for s in self._mock_students:
            if s["student_id"] == student_id:
                return s
        return None

    async def get_student_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        clean_email = email.strip().lower()
        for s in self._mock_students:
            if s.get("email", "").lower() == clean_email:
                return s
        return None

    async def save_students_roster(self, students: List[Dict[str, Any]]):
        self._mock_students = students

    async def get_all_project_states(self) -> List[Dict[str, Any]]:
        return list(self._project_states.values())

    async def get_student_project_states(self, student_id: str) -> List[Dict[str, Any]]:
        return [s for s in self._project_states.values() if s["student_id"] == student_id]

google_service = GoogleWorkspaceService()
