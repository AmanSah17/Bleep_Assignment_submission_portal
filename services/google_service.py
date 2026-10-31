import os
import io
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fastapi import HTTPException, status
from config import settings

# ── OAuth scopes for student Google SSO (basic identity only – no verification needed) ──
SSO_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ── Admin OAuth scopes for Drive + Sheets (offline, used only by admin) ──
ADMIN_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ── Service Account scopes (used when SA JSON is provided) ──
SERVICE_ACCOUNT_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


class GoogleWorkspaceService:
    def __init__(self):
        self.lock = asyncio.Lock()
        self._cached_creds: Optional[Credentials] = None
        self._root_folder_id: Optional[str] = None

        # ── In-memory data store (persisted to Sheets when credentials available) ──
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
            },
        ]
        self._project_states: Dict[str, Dict[str, Any]] = {}
        self._audit_events: List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────
    # OAuth Client Config helpers
    # ─────────────────────────────────────────────
    def _state_key(self, student_id: str, project_title: str) -> str:
        return f"{student_id}::{project_title.replace(' ', '_')}"

    def get_client_config(self) -> dict:
        if os.path.exists(settings.GOOGLE_CLIENT_SECRETS_FILE):
            try:
                with open(settings.GOOGLE_CLIENT_SECRETS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
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
        """URL for admin to grant offline Drive + Sheets access."""
        flow = self.create_flow(scopes=ADMIN_SCOPES, redirect_uri=redirect_uri)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> Credentials:
        flow = self.create_flow(scopes=ADMIN_SCOPES, redirect_uri=redirect_uri)
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
            "scopes": list(creds.scopes) if creds.scopes else ADMIN_SCOPES,
        }
        try:
            with open(settings.TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
            print(f"[Google Auth] Credentials cached -> {settings.TOKEN_CACHE_FILE}")
        except Exception as e:
            print(f"Warning: Could not save tokens file: {e}")

    # ─────────────────────────────────────────────
    # Credential Resolution (3-tier priority)
    # ─────────────────────────────────────────────
    def get_credentials(self) -> Optional[Credentials]:
        """
        Priority order:
        1. Service Account JSON  (env var GOOGLE_SERVICE_ACCOUNT_JSON)
        2. Local token cache file (google_admin_tokens.json)
        3. GOOGLE_REFRESH_TOKEN env var (Render deployment)
        Returns None if none available – callers raise HTTP 503.
        """
        # Tier 1: Service Account (best for production / Render)
        sa_json_str = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if sa_json_str and sa_json_str.strip().startswith("{"):
            try:
                sa_info = json.loads(sa_json_str)
                creds = service_account.Credentials.from_service_account_info(
                    sa_info, scopes=SERVICE_ACCOUNT_SCOPES
                )
                creds.refresh(GoogleRequest())
                print("[Google Auth] Using Service Account credentials.")
                self._cached_creds = creds
                return creds
            except Exception as e:
                print(f"[Google Auth] Service Account load failed: {e}")

        # Tier 2: Cached access token file
        if self._cached_creds and self._cached_creds.valid:
            return self._cached_creds

        if os.path.exists(settings.TOKEN_CACHE_FILE):
            try:
                with open(settings.TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                refresh_token = data.get("refresh_token") or settings.GOOGLE_REFRESH_TOKEN
                if refresh_token:
                    creds = Credentials(
                        token=data.get("token"),
                        refresh_token=refresh_token,
                        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                        client_id=settings.GOOGLE_CLIENT_ID,
                        client_secret=settings.GOOGLE_CLIENT_SECRET,
                        scopes=ADMIN_SCOPES,
                    )
                    if creds.expired or not creds.valid:
                        creds.refresh(GoogleRequest())
                        self._save_credentials(creds)
                    if creds.valid:
                        self._cached_creds = creds
                        return creds
            except Exception as e:
                print(f"[Google Auth] Cached token refresh failed: {e}")

        # Tier 3: Env var refresh token (Render)
        if settings.GOOGLE_REFRESH_TOKEN:
            try:
                creds = Credentials(
                    token=None,
                    refresh_token=settings.GOOGLE_REFRESH_TOKEN,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.GOOGLE_CLIENT_ID,
                    client_secret=settings.GOOGLE_CLIENT_SECRET,
                    scopes=ADMIN_SCOPES,
                )
                creds.refresh(GoogleRequest())
                if creds.valid:
                    self._cached_creds = creds
                    return creds
            except Exception as e:
                print(f"[Google Auth] Env GOOGLE_REFRESH_TOKEN refresh failed: {e}")

        return None

    def is_google_connected(self) -> bool:
        creds = self.get_credentials()
        return creds is not None and creds.valid

    # ─────────────────────────────────────────────
    # Google Drive Operations (Real Drive API)
    # ─────────────────────────────────────────────
    async def get_root_folder_id(self) -> str:
        """
        Returns the shared root Drive folder ID directly.
        Folder: https://drive.google.com/drive/folders/1TlQK2zmq1IaFhkavyjlapOtcglOOB9oS
        This folder is already shared (open link) by the admin.
        No creation needed — we always upload into this existing folder.
        """
        if self._root_folder_id:
            return self._root_folder_id
        self._root_folder_id = settings.DRIVE_ROOT_FOLDER_ID
        print(f"[Drive] Using shared root folder: {self._root_folder_id}")
        return self._root_folder_id

    async def get_or_create_student_folder(self, student_id: str, student_name: str) -> str:
        """
        Creates (or finds) a per-student sub-folder inside the shared root Drive folder.
        Sub-folder name: STU0001_Manas_M
        """
        creds = self.get_credentials()
        if not creds:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Drive not authorized. Please contact instructor Aman Sah.",
            )

        clean_name = f"{student_id}_{student_name.replace(' ', '_')}"
        root_id = await self.get_root_folder_id()
        service = build("drive", "v3", credentials=creds)
        query = (
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{clean_name}' and '{root_id}' in parents and trashed = false"
        )
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
        if not creds:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Drive not authorized. Please contact instructor Aman Sah.",
            )

        clean_title = project_title.replace(" ", "_")
        service = build("drive", "v3", credentials=creds)
        query = (
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{clean_title}' and '{student_folder_id}' in parents and trashed = false"
        )
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
        """
        Uploads notebook to Google Drive -> returns real file_id and webViewLink.
        Raises HTTP 503 if Drive is not authorized (no mock fallback).
        """
        creds = self.get_credentials()
        if not creds:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Google Drive storage is not connected. "
                    "Ask instructor Aman Sah to authorize Google Drive via the Admin Dashboard, "
                    "or configure GOOGLE_SERVICE_ACCOUNT_JSON on the server."
                ),
            )

        project_folder_id = await self.get_or_create_project_folder(student_folder_id, project_title)
        service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": filename,
            "parents": [project_folder_id],
        }
        media = MediaIoBaseUpload(
            io.BytesIO(file_bytes),
            mimetype="application/x-ipynb+json",
            resumable=True,
        )
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
        ).execute()

        file_id = uploaded.get("id")

        # Grant public read access so students and instructor can view the link
        try:
            service.permissions().create(
                fileId=file_id,
                body={"role": "reader", "type": "anyone"},
                fields="id",
            ).execute()
        except Exception as perm_err:
            print(f"Warning: Could not set public link on file {file_id}: {perm_err}")

        web_view_url = uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        print(f"[Drive Upload OK] {filename} | ID: {file_id} | {web_view_url}")

        return {
            "file_id": file_id,
            "web_view_url": web_view_url,
        }

    # ─────────────────────────────────────────────
    # Event Logging & Audit Trail
    # ─────────────────────────────────────────────
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
            print(f"Notice: Sheets audit sync: {e}")

    async def get_audit_events(
        self,
        student_id: Optional[str] = None,
        project_title: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        events = self._audit_events
        if student_id:
            events = [e for e in events if e["student_id"] == student_id]
        if project_title:
            events = [e for e in events if e["project_title"] == project_title]
        return list(reversed(events))

    # ─────────────────────────────────────────────
    # Project State Tracking
    # ─────────────────────────────────────────────
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
                "status": "NOT_STARTED",
                "timer_start": None,
                "timer_end": None,
                "deadline": None,
                "time_spent_minutes": 0,
                "allowed_duration_minutes": duration_minutes,
                "extension_minutes_total": 0,
                "current_version": 0,
                "submissions": [],
                "student_remarks_history": [],
                "instructor_remarks_history": [],
                "evaluation_history": [],
                "latest_marks": None,
                "max_marks": 100,
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
        state = await self.get_or_create_project_state(
            student_id, student_name, project_title, duration_minutes
        )

        if state["timer_start"]:
            return state  # Already started

        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        deadline = now + timedelta(minutes=duration_minutes)
        deadline_str = deadline.strftime("%Y-%m-%d %H:%M:%S")

        state["timer_start"] = now_str
        state["deadline"] = deadline_str
        state["status"] = "IN_PROGRESS"
        state["updated_at"] = now_str

        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="PROJECT_SELECTED",
            description=f"Student selected project '{project_title}' and started work.",
            actor="STUDENT",
        )
        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="TIMER_STARTED",
            description=f"Timer started. Duration: {duration_minutes} min. Deadline: {deadline_str} UTC",
            actor="SYSTEM",
            metadata={
                "timer_start": now_str,
                "deadline": deadline_str,
                "duration_minutes": duration_minutes,
            },
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
        student_remarks: str = "",
    ) -> Dict[str, Any]:
        state = await self.get_or_create_project_state(student_id, student_name, project_title)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        state["current_version"] += 1
        version_tag = f"v{state['current_version']}"
        is_resubmission = state["current_version"] > 1

        submission_record = {
            "version": version_tag,
            "file_id": drive_file_id,
            "file_url": drive_file_url,
            "student_remarks": student_remarks,
            "submitted_at": now_str,
        }
        state["submissions"].append(submission_record)

        if student_remarks:
            state["student_remarks_history"].append({
                "version": version_tag,
                "remarks": student_remarks,
                "timestamp": now_str,
            })

        state["status"] = "SUBMITTED" if not is_resubmission else "RESUBMITTED"
        state["timer_end"] = now_str
        state["updated_at"] = now_str

        if state["timer_start"]:
            try:
                start = datetime.strptime(state["timer_start"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                end = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                state["time_spent_minutes"] = int((end - start).total_seconds() / 60)
            except Exception:
                pass

        event_type = "NOTEBOOK_RESUBMITTED" if is_resubmission else "NOTEBOOK_UPLOADED"
        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type=event_type,
            description=(
                f"{'Resubmitted' if is_resubmission else 'Submitted'} notebook "
                f"({version_tag}). Drive: {drive_file_url}"
            ),
            actor="STUDENT",
            metadata=submission_record,
        )

        if student_remarks:
            await self.log_event(
                student_id=student_id,
                student_name=student_name,
                project_title=project_title,
                event_type="STUDENT_REMARK_ADDED",
                description=f"Student added remarks ({version_tag}): {student_remarks}",
                actor="STUDENT",
            )

        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def extend_deadline(
        self,
        student_id: str,
        project_title: str,
        extension_minutes: int,
        admin_note: str = "",
        admin_name: str = "Instructor",
    ) -> Dict[str, Any]:
        student = await self.get_student_by_id(student_id)
        student_name = student["full_name"] if student else "Student"
        state = await self.get_or_create_project_state(student_id, student_name, project_title)

        old_deadline = state["deadline"]
        if old_deadline:
            try:
                current_dl = datetime.strptime(old_deadline, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                current_dl = datetime.now(timezone.utc)
        else:
            current_dl = datetime.now(timezone.utc)

        new_deadline = current_dl + timedelta(minutes=extension_minutes)
        new_deadline_str = new_deadline.strftime("%Y-%m-%d %H:%M:%S")
        state["deadline"] = new_deadline_str
        state["extension_minutes_total"] += extension_minutes
        state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        await self.log_event(
            student_id=student_id,
            student_name=student_name,
            project_title=project_title,
            event_type="DEADLINE_EXTENDED",
            description=(
                f"{admin_name} extended deadline by {extension_minutes} min. "
                f"Old: {old_deadline} UTC -> New: {new_deadline_str} UTC. Note: {admin_note}"
            ),
            actor="INSTRUCTOR",
            metadata={
                "extension_minutes": extension_minutes,
                "old_deadline": old_deadline,
                "new_deadline": new_deadline_str,
                "admin_note": admin_note,
            },
        )
        asyncio.create_task(self._sync_state_to_sheet(state))
        return state

    async def evaluate_project(
        self,
        student_id: str,
        project_title: str,
        marks: int,
        instructor_remarks: str,
        admin_name: str = "Instructor",
        new_status: str = "EVALUATED",
    ) -> Dict[str, Any]:
        student = await self.get_student_by_id(student_id)
        student_name = student["full_name"] if student else "Student"
        state = await self.get_or_create_project_state(student_id, student_name, project_title)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        evaluation_record = {
            "round": len(state["evaluation_history"]) + 1,
            "marks": marks,
            "max_marks": state["max_marks"],
            "instructor_remarks": instructor_remarks,
            "admin_name": admin_name,
            "evaluated_at": now_str,
        }
        state["evaluation_history"].append(evaluation_record)
        state["latest_marks"] = marks
        state["status"] = new_status
        state["updated_at"] = now_str

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
            print(f"Notice: Sheets state sync: {e}")

    # ─────────────────────────────────────────────
    # Student Roster Access
    # ─────────────────────────────────────────────
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
