# Bleep Student Assignment & Evaluation Management System

An enterprise-grade, database-less (Google Sheets as single source of truth) assignment submission, timer tracking, and evaluation platform built with **FastAPI**, **Google OpenID Connect**, **Google Drive API v3**, and **Google Sheets API v4**.

Designed for seamless deployment on **Render** with zero database hosting overhead.

---

## 🌟 Key Architecture & Capabilities

### 1. Dual-Authentication Flow
- **Google OpenID Connect (SSO)**:
  - Students click *"Continue with Google"*.
  - Google verifies their identity and returns a cryptographically signed ID token.
  - The FastAPI backend validates the token and checks whether the email exists in your registered Google Sheet roster.
  - Scopes: `openid`, `https://www.googleapis.com/auth/userinfo.email`, `https://www.googleapis.com/auth/userinfo.profile`.
- **Email + Password Fallback**:
  - Students can also log in directly with their registered email and a generated temporary password.
  - Passwords are encrypted using **bcrypt + salt** before being stored.
  - **Aman Sah (Admin)** logs in at the same portal with administrative credentials (`amansah1717@gmail.com`).

### 2. Google Drive Vault Custodian Architecture
- **One-Time Administrator Authorization**:
  - The instructor authorizes their Google account once via the Admin Dashboard (`/auth/admin/oauth-drive`).
  - The backend stores the offline `refresh_token` securely.
- **Automated Directory Provisioning**:
  - Dedicated student folders: `Bleep_Student_Assignments/{student_id}_{student_name}/`.
  - Project subfolders: `{student_folder}/{project_title}/`.
  - Automatic versioning: `STU0001_Project_01_EDA_v1.ipynb`, `_v2.ipynb`, `_v3.ipynb`.
- **Absolute Privacy & Isolation**:
  - Students never get access to browse or delete files in your Google Drive.
  - All uploads stream through the backend.

### 3. Google Sheets as Live Database (No PostgreSQL Required)
Eliminates database maintenance and costs. Organizes records into three tabs:
- **`Students_Roster`**: Master registry of students, emails, bcrypt hashes, plain temporary passwords, and folder IDs.
- **`Projects_Status`**: Current consolidated state of every student's project: status, timer start, deadline, time spent, latest version, Drive link, student remarks, instructor feedback, marks, and max marks.
- **`Activity_Audit_Log`**: Immutable event stream logging all actions with timestamps (`PROJECT_SELECTED`, `TIMER_STARTED`, `NOTEBOOK_UPLOADED`, `NOTEBOOK_RESUBMITTED`, `DEADLINE_EXTENDED`, `MARKS_EVALUATED`, `PROJECT_COMPLETED`).

### 4. 9-Point Event & Milestone Tracking Engine
1. **Project selection & start time**
2. **Live timer and deadline calculation**
3. **Project completion tracking**
4. **Notebook uploads and resubmissions (versioning v1, v2, v3)**
5. **Student remarks logging**
6. **Instructor feedback logging**
7. **Marks and multi-round evaluation history**
8. **Instructor deadline extensions (+X minutes with reason)**
9. **Status lifecycle transitions** (`NOT_STARTED` -> `IN_PROGRESS` -> `SUBMITTED` -> `RESUBMITTED` -> `GRADED` -> `COMPLETED`)

---

## 📁 Repository Structure

```
.
├── main.py                     # FastAPI application entrypoint & page routing
├── config.py                   # Centralized configuration & Google secret loader
├── requirements.txt            # Production Python dependencies
├── render.yaml                 # Render Blueprint Infrastructure-as-Code
├── .env.example                # Template for environment variables
├── test_system.py              # Automated end-to-end verification test suite
├── routes/
│   ├── auth_routes.py          # Google SSO, password auth & Drive authorization
│   ├── student_routes.py       # Student dashboard data, timer, & .ipynb uploads
│   └── admin_routes.py         # Instructor grading, extensions, & password generator
├── services/
│   ├── auth_service.py         # Bcrypt hashing, password generator, & JWT tokens
│   └── google_service.py       # Google Drive API, Sheets API & Audit event engine
└── templates/
    ├── login.html              # Modern, responsive dual-login portal (Tailwind CSS)
    ├── student_dashboard.html  # Student workspace with live countdown timer
    └── admin_dashboard.html    # Instructor command center for Aman Sah
```

---

## ⚡ Quick Start: Local Testing

### Prerequisites
- Python 3.10+ (Tested on Python 3.14 with `D:\CUDA_ENV\CUDA_ENV`)
- Virtual environment active:
  ```powershell
  D:\CUDA_ENV\CUDA_ENV\Scripts\activate
  ```

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Run the Verification Suite
Execute the automated test script to verify authentication, timer start, uploads, grading, and audit logging:
```powershell
& "D:\CUDA_ENV\CUDA_ENV\Scripts\python.exe" "D:\CUDA_ENV\Assignment_submission\test_system.py"
```

### 3. Launch the Server
```powershell
& "D:\CUDA_ENV\CUDA_ENV\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser:
- **Unified Login**: [http://localhost:8000/](http://localhost:8000/)
- **Student Dashboard**: [http://localhost:8000/student/dashboard](http://localhost:8000/student/dashboard)
- **Admin Command Center**: [http://localhost:8000/admin/dashboard](http://localhost:8000/admin/dashboard)

### Default Credentials
- **Admin**:
  - Email: `amansah1717@gmail.com`
  - Password: `Amansah@1717`
- **Sample Student**:
  - Email: `manas@gmail.com`
  - Password: `Bleep#9x2K` (or sign in with Google SSO)

---

## 🔧 Google Cloud Console Configuration

To authorize logins and Google Drive uploads, configure your OAuth Client in [Google Cloud Console](https://console.cloud.google.com/apis/credentials?project=bleepstudents):

1. **Enable APIs**:
   - Google Drive API
   - Google Sheets API
2. **Authorized JavaScript Origins**:
   - `http://localhost:8000`
   - `https://<your-render-app>.onrender.com`
3. **Authorized Redirect URIs**:
   - `http://localhost:8000/auth/google/callback`
   - `http://localhost:8000/auth/admin/oauth-callback`
   - `https://<your-render-app>.onrender.com/auth/google/callback`
   - `https://<your-render-app>.onrender.com/auth/admin/oauth-callback`

---

## ☁️ Deploying to Render

This project is pre-configured with [`render.yaml`](file:///D:/CUDA_ENV/Assignment_submission/render.yaml) for automated Blueprint deployment:

1. Push your repository to GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial commit of Student Portal"
   git remote add origin git@github.com:AmanSah17/Bleep_Assignment_submission_portal.git
   git branch -M main
   git push -u origin main
   ```
2. Navigate to [Render Dashboard](https://dashboard.render.com).
3. Click **New +** -> **Blueprint**.
4. Select `AmanSah17/Bleep_Assignment_submission_portal`.
5. Under Environment Variables, supply:
   - `GOOGLE_CLIENT_SECRET`: Your Google client secret (`GOCSPX-...`).
6. Click **Apply**. Render will build and deploy your service with a free live `https://<app>.onrender.com` URL.

---

## 🛡️ Security Best Practices
- **Bcrypt Password Hashes**: Student passwords are never stored in plaintext within the authentication database.
- **JWT Expiry**: Sessions are secured using HMAC-SHA256 signed tokens with 24-hour expiration.
- **Encrypted Media Streams**: File transfers stream in-memory without caching sensitive notebooks to persistent container disk.
- **Isolated Refresh Tokens**: The instructor's Google Drive credentials remain server-side and are never exposed to the frontend.
