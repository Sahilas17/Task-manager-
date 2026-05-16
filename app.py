import base64
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "task_manager.sqlite3"))
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-in-railway")
PORT = int(os.environ.get("PORT", "8000"))

STATUSES = {"todo", "in_progress", "review", "done"}
PRIORITIES = {"low", "medium", "high"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_id(prefix):
    return f"{prefix}_{secrets.token_urlsafe(10)}"


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(data):
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return salt, digest.hex()


def verify_password(password, salt, expected_hash):
    _, actual_hash = hash_password(password, salt)
    return hmac.compare_digest(actual_hash, expected_hash)


def sign_token(user_id):
    payload = {"sub": user_id, "exp": int(time.time()) + 60 * 60 * 24 * 7}
    payload_part = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{b64url(signature)}"


def verify_token(token):
    try:
        payload_part, signature_part = token.split(".", 1)
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(b64url(expected), signature_part):
            return None
        payload = json.loads(b64url_decode(payload_part))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload.get("sub")
    except Exception:
        return None


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'member')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS memberships (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'member')),
                added_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, user_id),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(added_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                assignee_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('todo', 'in_progress', 'review', 'done')),
                priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high')),
                due_date TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(assignee_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


def public_user(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "createdAt": row["created_at"],
    }


def membership_role(conn, project_id, user_id):
    row = conn.execute(
        "SELECT role FROM memberships WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchone()
    return row["role"] if row else None


def can_view_project(conn, user, project_id):
    return user["role"] == "admin" or membership_role(conn, project_id, user["id"]) is not None


def can_manage_project(conn, user, project_id):
    return user["role"] == "admin" or membership_role(conn, project_id, user["id"]) == "admin"


def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def validate_email(email):
    return bool(email and EMAIL_RE.match(email))


def validate_due_date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("Due date must use YYYY-MM-DD format.")


def task_payload(conn, row):
    assignee = get_user(conn, row["assignee_id"]) if row["assignee_id"] else None
    creator = get_user(conn, row["created_by"])
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "title": row["title"],
        "description": row["description"],
        "assigneeId": row["assignee_id"],
        "assignee": public_user(assignee),
        "status": row["status"],
        "priority": row["priority"],
        "dueDate": row["due_date"],
        "createdBy": public_user(creator),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def project_members(conn, project_id):
    rows = conn.execute(
        """
        SELECT m.role AS membership_role, m.created_at AS joined_at, u.*
        FROM memberships m
        JOIN users u ON u.id = m.user_id
        WHERE m.project_id = ?
        ORDER BY CASE m.role WHEN 'admin' THEN 0 ELSE 1 END, u.name
        """,
        (project_id,),
    ).fetchall()
    return [
        {
            **public_user(row),
            "projectRole": row["membership_role"],
            "joinedAt": row["joined_at"],
        }
        for row in rows
    ]


def project_tasks(conn, project_id):
    rows = conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY due_date IS NULL, due_date, created_at DESC",
        (project_id,),
    ).fetchall()
    return [task_payload(conn, row) for row in rows]


def project_payload(conn, row, user, include_tasks=False):
    tasks = project_tasks(conn, row["id"]) if include_tasks else []
    if include_tasks:
        status_counts = {status: 0 for status in STATUSES}
        for task in tasks:
            status_counts[task["status"]] += 1
        task_total = len(tasks)
        task_done = status_counts["done"]
    else:
        stats = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done
            FROM tasks WHERE project_id = ?
            """,
            (row["id"],),
        ).fetchone()
        task_total = stats["total"] or 0
        task_done = stats["done"] or 0
        status_counts = None

    role = "admin" if user["role"] == "admin" else membership_role(conn, row["id"], user["id"])
    payload = {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "currentUserRole": role,
        "taskTotal": task_total,
        "taskDone": task_done,
        "progress": round((task_done / task_total) * 100) if task_total else 0,
        "members": project_members(conn, row["id"]),
    }
    if include_tasks:
        payload["tasks"] = tasks
        payload["statusCounts"] = status_counts
    return payload


class AppError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "EtharaTaskManager/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def do_PUT(self):
        self.route()

    def do_DELETE(self):
        self.route()

    def route(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                with connect() as conn:
                    self.handle_api(conn, path)
            else:
                self.serve_static(path)
        except AppError as exc:
            self.send_json({"error": exc.message}, exc.status)
        except sqlite3.IntegrityError as exc:
            message = "This record conflicts with existing data."
            if "users.email" in str(exc):
                message = "An account with this email already exists."
            self.send_json({"error": message}, 409)
        except Exception as exc:
            print("Unhandled error:", repr(exc))
            self.send_json({"error": "Something went wrong. Please try again."}, 500)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise AppError(413, "Request body is too large.")
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            raise AppError(400, "Invalid JSON body.")

    def require_user(self, conn):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise AppError(401, "Authentication required.")
        user_id = verify_token(header[7:].strip())
        if not user_id:
            raise AppError(401, "Invalid or expired session.")
        user = get_user(conn, user_id)
        if not user:
            raise AppError(401, "User no longer exists.")
        return user

    def handle_api(self, conn, path):
        method = self.command
        parts = [part for part in path.strip("/").split("/") if part][1:]

        if method == "POST" and parts == ["auth", "signup"]:
            return self.signup(conn)
        if method == "POST" and parts == ["auth", "login"]:
            return self.login(conn)

        user = self.require_user(conn)

        if method == "GET" and parts == ["auth", "me"]:
            return self.send_json({"user": public_user(user)})
        if method == "GET" and parts == ["users"]:
            return self.list_users(conn)
        if method == "GET" and parts == ["dashboard"]:
            return self.dashboard(conn, user)
        if method == "GET" and parts == ["projects"]:
            return self.list_projects(conn, user)
        if method == "POST" and parts == ["projects"]:
            return self.create_project(conn, user)
        if len(parts) == 2 and parts[0] == "projects":
            if method == "GET":
                return self.get_project(conn, user, parts[1])
            if method == "PUT":
                return self.update_project(conn, user, parts[1])
            if method == "DELETE":
                return self.delete_project(conn, user, parts[1])
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "members" and method == "POST":
            return self.add_member(conn, user, parts[1])
        if len(parts) == 4 and parts[0] == "projects" and parts[2] == "members" and method == "DELETE":
            return self.remove_member(conn, user, parts[1], parts[3])
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "tasks" and method == "POST":
            return self.create_task(conn, user, parts[1])
        if len(parts) == 2 and parts[0] == "tasks":
            if method == "PUT":
                return self.update_task(conn, user, parts[1])
            if method == "DELETE":
                return self.delete_task(conn, user, parts[1])

        raise AppError(404, "API route not found.")

    def signup(self, conn):
        body = self.read_json()
        name = str(body.get("name", "")).strip()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        if len(name) < 2:
            raise AppError(400, "Name must be at least 2 characters.")
        if not validate_email(email):
            raise AppError(400, "Enter a valid email address.")
        if len(password) < 6:
            raise AppError(400, "Password must be at least 6 characters.")

        user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        role = "admin" if user_count == 0 else "member"
        salt, password_hash = hash_password(password)
        user_id = new_id("usr")
        conn.execute(
            """
            INSERT INTO users (id, name, email, password_hash, salt, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, email, password_hash, salt, role, now_iso()),
        )
        conn.commit()
        user = get_user(conn, user_id)
        self.send_json({"token": sign_token(user_id), "user": public_user(user)}, 201)

    def login(self, conn):
        body = self.read_json()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(password, user["salt"], user["password_hash"]):
            raise AppError(401, "Invalid email or password.")
        self.send_json({"token": sign_token(user["id"]), "user": public_user(user)})

    def list_users(self, conn):
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        self.send_json({"users": [public_user(row) for row in rows]})

    def accessible_projects(self, conn, user):
        if user["role"] == "admin":
            return conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return conn.execute(
            """
            SELECT p.*
            FROM projects p
            JOIN memberships m ON m.project_id = p.id
            WHERE m.user_id = ?
            ORDER BY p.updated_at DESC
            """,
            (user["id"],),
        ).fetchall()

    def dashboard(self, conn, user):
        projects = self.accessible_projects(conn, user)
        project_ids = [row["id"] for row in projects]
        tasks = []
        my_tasks = []
        if project_ids:
            placeholders = ",".join("?" for _ in project_ids)
            tasks = conn.execute(f"SELECT * FROM tasks WHERE project_id IN ({placeholders})", project_ids).fetchall()
            my_tasks = conn.execute(
                f"SELECT * FROM tasks WHERE project_id IN ({placeholders}) AND assignee_id = ?",
                (*project_ids, user["id"]),
            ).fetchall()

        today = dt.date.today().isoformat()
        overdue = [task for task in tasks if task["due_date"] and task["due_date"] < today and task["status"] != "done"]
        status_counts = {status: 0 for status in STATUSES}
        for task in tasks:
            status_counts[task["status"]] += 1

        recent_rows = sorted(tasks, key=lambda row: row["updated_at"], reverse=True)[:6]
        self.send_json(
            {
                "summary": {
                    "projects": len(projects),
                    "tasks": len(tasks),
                    "myTasks": len(my_tasks),
                    "overdue": len(overdue),
                    "completed": status_counts["done"],
                },
                "statusCounts": status_counts,
                "recentTasks": [task_payload(conn, row) for row in recent_rows],
                "overdueTasks": [task_payload(conn, row) for row in overdue[:6]],
            }
        )

    def list_projects(self, conn, user):
        projects = [project_payload(conn, row, user) for row in self.accessible_projects(conn, user)]
        self.send_json({"projects": projects})

    def get_project_row(self, conn, project_id):
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise AppError(404, "Project not found.")
        return row

    def get_project(self, conn, user, project_id):
        row = self.get_project_row(conn, project_id)
        if not can_view_project(conn, user, project_id):
            raise AppError(403, "You do not have access to this project.")
        self.send_json({"project": project_payload(conn, row, user, include_tasks=True)})

    def create_project(self, conn, user):
        body = self.read_json()
        name = str(body.get("name", "")).strip()
        description = str(body.get("description", "")).strip()
        if len(name) < 3:
            raise AppError(400, "Project name must be at least 3 characters.")
        project_id = new_id("prj")
        timestamp = now_iso()
        conn.execute(
            """
            INSERT INTO projects (id, name, description, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, name, description, user["id"], timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO memberships (id, project_id, user_id, role, added_by, created_at)
            VALUES (?, ?, ?, 'admin', ?, ?)
            """,
            (new_id("mem"), project_id, user["id"], user["id"], timestamp),
        )
        conn.commit()
        row = self.get_project_row(conn, project_id)
        self.send_json({"project": project_payload(conn, row, user, include_tasks=True)}, 201)

    def update_project(self, conn, user, project_id):
        row = self.get_project_row(conn, project_id)
        if not can_manage_project(conn, user, project_id):
            raise AppError(403, "Only project admins can update this project.")
        body = self.read_json()
        name = str(body.get("name", row["name"])).strip()
        description = str(body.get("description", row["description"])).strip()
        if len(name) < 3:
            raise AppError(400, "Project name must be at least 3 characters.")
        conn.execute(
            "UPDATE projects SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (name, description, now_iso(), project_id),
        )
        conn.commit()
        self.get_project(conn, user, project_id)

    def delete_project(self, conn, user, project_id):
        self.get_project_row(conn, project_id)
        if not can_manage_project(conn, user, project_id):
            raise AppError(403, "Only project admins can delete this project.")
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        self.send_json({"ok": True})

    def add_member(self, conn, user, project_id):
        self.get_project_row(conn, project_id)
        if not can_manage_project(conn, user, project_id):
            raise AppError(403, "Only project admins can manage the team.")
        body = self.read_json()
        user_id = str(body.get("userId", "")).strip()
        role = str(body.get("role", "member")).strip()
        if role not in {"admin", "member"}:
            raise AppError(400, "Member role must be admin or member.")
        target = get_user(conn, user_id)
        if not target:
            raise AppError(404, "User not found.")
        existing = membership_role(conn, project_id, user_id)
        timestamp = now_iso()
        if existing:
            conn.execute(
                "UPDATE memberships SET role = ? WHERE project_id = ? AND user_id = ?",
                (role, project_id, user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO memberships (id, project_id, user_id, role, added_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_id("mem"), project_id, user_id, role, user["id"], timestamp),
            )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (timestamp, project_id))
        conn.commit()
        self.get_project(conn, user, project_id)

    def remove_member(self, conn, user, project_id, user_id):
        self.get_project_row(conn, project_id)
        if not can_manage_project(conn, user, project_id):
            raise AppError(403, "Only project admins can manage the team.")
        user_id = unquote(user_id)
        role = membership_role(conn, project_id, user_id)
        if not role:
            raise AppError(404, "Member not found in this project.")
        if role == "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) AS count FROM memberships WHERE project_id = ? AND role = 'admin'",
                (project_id,),
            ).fetchone()["count"]
            if admin_count <= 1:
                raise AppError(400, "A project must keep at least one admin.")
        conn.execute("DELETE FROM memberships WHERE project_id = ? AND user_id = ?", (project_id, user_id))
        conn.execute("UPDATE tasks SET assignee_id = NULL, updated_at = ? WHERE project_id = ? AND assignee_id = ?", (now_iso(), project_id, user_id))
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now_iso(), project_id))
        conn.commit()
        self.get_project(conn, user, project_id)

    def validate_assignee(self, conn, project_id, assignee_id):
        if not assignee_id:
            return None
        if not get_user(conn, assignee_id):
            raise AppError(404, "Assignee not found.")
        if not membership_role(conn, project_id, assignee_id):
            raise AppError(400, "Assignee must be a member of this project.")
        return assignee_id

    def create_task(self, conn, user, project_id):
        self.get_project_row(conn, project_id)
        if not can_manage_project(conn, user, project_id):
            raise AppError(403, "Only project admins can create tasks.")
        body = self.read_json()
        title = str(body.get("title", "")).strip()
        description = str(body.get("description", "")).strip()
        status = str(body.get("status", "todo")).strip()
        priority = str(body.get("priority", "medium")).strip()
        if len(title) < 3:
            raise AppError(400, "Task title must be at least 3 characters.")
        if status not in STATUSES:
            raise AppError(400, "Invalid task status.")
        if priority not in PRIORITIES:
            raise AppError(400, "Invalid task priority.")
        assignee_id = self.validate_assignee(conn, project_id, str(body.get("assigneeId") or "").strip())
        due_date = validate_due_date(body.get("dueDate"))
        timestamp = now_iso()
        task_id = new_id("tsk")
        conn.execute(
            """
            INSERT INTO tasks (id, project_id, title, description, assignee_id, status, priority, due_date, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, project_id, title, description, assignee_id, status, priority, due_date, user["id"], timestamp, timestamp),
        )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (timestamp, project_id))
        conn.commit()
        self.get_project(conn, user, project_id)

    def get_task_row(self, conn, task_id):
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise AppError(404, "Task not found.")
        return row

    def update_task(self, conn, user, task_id):
        task = self.get_task_row(conn, task_id)
        if not can_view_project(conn, user, task["project_id"]):
            raise AppError(403, "You do not have access to this task.")
        body = self.read_json()
        is_manager = can_manage_project(conn, user, task["project_id"])
        is_assignee = task["assignee_id"] == user["id"]
        if not is_manager and not is_assignee:
            raise AppError(403, "Only admins or the assignee can update this task.")

        if is_manager:
            title = str(body.get("title", task["title"])).strip()
            description = str(body.get("description", task["description"])).strip()
            status = str(body.get("status", task["status"])).strip()
            priority = str(body.get("priority", task["priority"])).strip()
            assignee_id = self.validate_assignee(conn, task["project_id"], str(body.get("assigneeId", task["assignee_id"] or "") or "").strip())
            due_date = validate_due_date(body.get("dueDate", task["due_date"]))
            if len(title) < 3:
                raise AppError(400, "Task title must be at least 3 characters.")
            if status not in STATUSES:
                raise AppError(400, "Invalid task status.")
            if priority not in PRIORITIES:
                raise AppError(400, "Invalid task priority.")
        else:
            title = task["title"]
            description = task["description"]
            assignee_id = task["assignee_id"]
            priority = task["priority"]
            due_date = task["due_date"]
            status = str(body.get("status", task["status"])).strip()
            if status not in STATUSES:
                raise AppError(400, "Invalid task status.")

        timestamp = now_iso()
        conn.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, assignee_id = ?, status = ?, priority = ?, due_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (title, description, assignee_id, status, priority, due_date, timestamp, task_id),
        )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (timestamp, task["project_id"]))
        conn.commit()
        project_row = self.get_project_row(conn, task["project_id"])
        self.send_json({"task": task_payload(conn, self.get_task_row(conn, task_id)), "project": project_payload(conn, project_row, user, include_tasks=True)})

    def delete_task(self, conn, user, task_id):
        task = self.get_task_row(conn, task_id)
        if not can_manage_project(conn, user, task["project_id"]):
            raise AppError(403, "Only project admins can delete tasks.")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now_iso(), task["project_id"]))
        conn.commit()
        project_row = self.get_project_row(conn, task["project_id"])
        self.send_json({"ok": True, "project": project_payload(conn, project_row, user, include_tasks=True)})

    def serve_static(self, path):
        requested = "index.html" if path in {"/", ""} else unquote(path.lstrip("/"))
        file_path = (PUBLIC_DIR / requested).resolve()
        try:
            file_path.relative_to(PUBLIC_DIR.resolve())
        except ValueError:
            raise AppError(403, "Forbidden.")
        if not file_path.exists() or file_path.is_dir():
            file_path = PUBLIC_DIR / "index.html"
        content = file_path.read_bytes()
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    init_db()
    try:
        print(f"Team Task Manager running on http://127.0.0.1:{PORT}", flush=True)
    except Exception:
        pass
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
