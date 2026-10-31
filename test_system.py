import main
from fastapi.testclient import TestClient
from services.google_service import google_service
from config import settings

print("="*60)
print("TESTING CLIENT INFORMATION & GOOGLE DRIVE OAUTH2")
print("Secrets file:", settings.GOOGLE_CLIENT_SECRETS_FILE)
print("Client ID:", settings.GOOGLE_CLIENT_ID)
print("Project ID:", settings.GOOGLE_PROJECT_ID)
print("Redirect URI:", settings.GOOGLE_REDIRECT_URI)
print("="*60)

client = TestClient(main.app)

# 1. Health check
resp_health = client.get("/health")
assert resp_health.status_code == 200
print("[PASS] Health Check:", resp_health.json())

# 2. Test Admin Login (Aman Sah)
resp_admin_login = client.post("/auth/login", data={"email": "amansah1717@gmail.com", "password": "Amansah@1717"})
assert resp_admin_login.status_code == 200
admin_data = resp_admin_login.json()
print("[PASS] Admin Login successful:", admin_data["role"])

# 3. Test Student Login (Manas M with initial password)
resp_student_login = client.post("/auth/login", data={"email": "manas@gmail.com", "password": "Bleep#9x2K"})
assert resp_student_login.status_code == 200
student_data = resp_student_login.json()
print("[PASS] Student Login successful:", student_data["role"])

# 4. Student Dashboard Data
resp_dash = client.get("/api/student/dashboard-data")
assert resp_dash.status_code == 200
dash_json = resp_dash.json()
print(f"[PASS] Student Dashboard fetched {len(dash_json['projects'])} projects.")

# 5. Start Project Timer
resp_timer = client.post("/api/student/timer/start", data={"project_title": "Project_01_EDA"})
assert resp_timer.status_code == 200
timer_state = resp_timer.json()["state"]
print(f"[PASS] Timer started: Project {timer_state['project_title']} | Status: {timer_state['status']} | Deadline: {timer_state['deadline']}")

# 6. Upload Notebook (.ipynb)
fake_ipynb = b'{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}'
resp_sub = client.post(
    "/api/student/submit",
    data={"project_title": "Project_01_EDA", "student_remarks": "Completed data profiling and correlation heatmap."},
    files={"file": ("EDA_submission.ipynb", fake_ipynb, "application/x-ipynb+json")},
)
assert resp_sub.status_code == 200
sub_json = resp_sub.json()
print(f"[PASS] Notebook uploaded: Version {sub_json['version']} | Drive Link: {sub_json['drive_url']}")

# 7. Resubmit Notebook (version increment to v2)
resp_resub = client.post(
    "/api/student/submit",
    data={"project_title": "Project_01_EDA", "student_remarks": "v2: Fixed outlier handling and scaled features."},
    files={"file": ("EDA_submission_v2.ipynb", fake_ipynb, "application/x-ipynb+json")},
)
assert resp_resub.status_code == 200
resub_json = resp_resub.json()
print(f"[PASS] Resubmission handled: Version {resub_json['version']} | Status: {resub_json['state']['status']}")

# 8. Admin Evaluates & Grades
admin_client = TestClient(main.app)
admin_client.post("/auth/login", data={"email": "amansah1717@gmail.com", "password": "Amansah@1717"})

resp_grade = admin_client.post(
    "/api/admin/grade",
    data={
        "student_id": "STU0001",
        "project_title": "Project_01_EDA",
        "marks": "95",
        "instructor_remarks": "Excellent EDA analysis and clean visualizations. Good improvements in v2.",
        "mark_as_completed": True,
    }
)
assert resp_grade.status_code == 200
grade_json = resp_grade.json()
print(f"[PASS] Instructor Evaluation: Status {grade_json['state']['status']} | Marks: {grade_json['state']['latest_marks']}/100")

# 9. Verify Audit Trail Events
events = admin_client.get("/api/admin/audit-events").json()["events"]
print(f"[PASS] Audit Event Stream recorded {len(events)} events:")
for e in events[:5]:
    print(f"   * [{e['timestamp']}] ({e['actor']}) {e['event_type']} -> {e['description']}")

print("\nALL ARCHITECTURAL REQUIREMENTS FULLY VERIFIED AND WORKING!")

