"""End-to-end smoke test. Run from backend/:  python -m tests.smoke_test"""
import io, time
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app.main import app


def pdf_bytes(pages=3):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(612, 792)
    b = io.BytesIO(); w.write(b); return b.getvalue()


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


with TestClient(app) as c:
    H = lambda t: {"Authorization": f"Bearer {t}"}
    email = f"stu{int(time.time())}@school.edu"
    cust = ok(c.post("/api/auth/register", json={"email": email, "full_name": "Test Student", "password": "password123"}), 201)["token"]
    admin = ok(c.post("/api/auth/login", json={"email": "admin@queprint.app", "password": "ChangeMe123!"}))["token"]
    cfg = ok(c.get("/api/config")); assert cfg["pricing"]["per_page"]["bw"] == 2.0
    print("estimate:", ok(c.post("/api/estimate", json={"pages": 10, "copies": 2, "sides": "double", "binding": "spiral"}))["total"])

    # validation
    assert c.post("/api/jobs", files={"file": ("x.exe", b"MZ....", "application/octet-stream")}, headers=H(cust)).status_code == 422
    assert c.post("/api/jobs", files={"file": ("evil.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")}, headers=H(cust)).status_code == 422
    assert c.post("/api/jobs", files={"file": ("a.pdf", pdf_bytes(2) + b"/JavaScript", "application/pdf")}, headers=H(cust)).status_code == 422
    assert c.post("/api/jobs", files={"file": ("a.pdf", pdf_bytes(2), "application/pdf")}).status_code == 401
    print("validation ok")

    # PDF job
    job = ok(c.post("/api/jobs", files={"file": ("thesis.pdf", pdf_bytes(3), "application/pdf")}, headers=H(cust)), 201)
    assert job["page_count"] == 3 and job["status"] == "draft"
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert c.post(f"/api/jobs/{job['id']}/confirm", json={"pickup_at": soon}, headers=H(cust)).status_code == 422
    later = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    done = ok(c.post(f"/api/jobs/{job['id']}/confirm", json={"pickup_at": later, "copies": 2, "color_mode": "color", "sides": "double", "binding": "staple"}, headers=H(cust)))
    assert done["status"] == "pending" and done["queue_position"] == 1 and done["total_cost"] == 43.2 + 6, done
    print("confirmed", done["tracking_code"], done["total_cost"])
    assert ok(c.get(f"/api/track/{done['tracking_code']}"))["status"] in ("pending", "processing", "ready")
    assert ok(c.get("/api/board"))["jobs"]

    # RBAC (FR2)
    assert c.get("/api/staff/jobs", headers=H(cust)).status_code == 403
    assert c.put("/api/admin/pricing", json={}, headers=H(cust)).status_code == 403
    assert ok(c.get("/api/staff/jobs", headers=H(admin)))

    # auto dispatch (FR15) -> processing, then staff flow
    time.sleep(7)
    st = ok(c.get(f"/api/staff/jobs/{job['id']}", headers=H(admin)))["status"]; print("after dispatcher:", st); assert st == "processing"
    assert c.get(f"/api/staff/jobs/{job['id']}/file", headers=H(admin)).headers["content-type"] == "application/pdf"
    assert c.patch(f"/api/staff/jobs/{job['id']}/status", json={"status": "completed"}, headers=H(admin)).status_code == 409
    ok(c.patch(f"/api/staff/jobs/{job['id']}/status", json={"status": "ready"}, headers=H(admin)))
    ok(c.patch(f"/api/staff/jobs/{job['id']}/status", json={"status": "completed"}, headers=H(admin)))
    notes = ok(c.get("/api/notifications", headers=H(cust))); print("notifications:", [n["message"] for n in notes][:3]); assert len(notes) >= 3

    # cancel + FIFO
    ok(c.put("/api/admin/auto-dispatch", json={"enabled": False}, headers=H(admin)))
    ids = []
    for i in range(2):
        j = ok(c.post("/api/jobs", files={"file": (f"d{i}.pdf", pdf_bytes(1), "application/pdf")}, headers=H(cust)), 201)
        ids.append(ok(c.post(f"/api/jobs/{j['id']}/confirm", json={"pickup_at": later}, headers=H(cust)))["id"])
    pos = [ok(c.get(f"/api/jobs/{i}", headers=H(cust)))["queue_position"] for i in ids]; print("positions", pos); assert pos[1] == pos[0] + 1
    ok(c.post(f"/api/jobs/{ids[0]}/cancel", headers=H(cust)))
    assert ok(c.get(f"/api/jobs/{ids[1]}", headers=H(cust)))["queue_position"] == 1
    ok(c.put("/api/admin/auto-dispatch", json={"enabled": True}, headers=H(admin)))

    # DOCX via LibreOffice
    import shutil, subprocess, tempfile, pathlib
    d = tempfile.mkdtemp(); pathlib.Path(d, "n.txt").write_text("Hello QuePrint\n" * 5)
    subprocess.run(["soffice", "--headless", "--convert-to", "docx", "--outdir", d, f"{d}/n.txt"], capture_output=True, timeout=120)
    docx = pathlib.Path(d, "n.docx").read_bytes()
    dj = ok(c.post("/api/jobs", files={"file": ("n.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=H(cust)), 201)
    print("docx pages:", dj["page_count"]); assert dj["page_count"] >= 1
    ok(c.post(f"/api/jobs/{dj['id']}/cancel", headers=H(cust)))  # delete draft
    ok(c.post("/api/admin/users", json={"email": f"op{int(time.time())}@shop.ph", "full_name": "Operator", "password": "operator123"}, headers=H(admin)), 201)
print("ALL OK")
