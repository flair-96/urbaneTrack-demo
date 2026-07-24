import sqlite3
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, g, flash, abort

app = Flask(__name__)

app.secret_key = "dev-secret-change-this"  # for sessions

DB_PATH = "urbaneTrack.db"


# ----------------------------
# Database helpers
# ----------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def format_datetime(value):
    if not value:
        return "-"

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(
                value,
                fmt
            ).strftime("%d %b %Y • %I:%M %p")
        except ValueError:
            pass

    return value

app.jinja_env.filters["datetime"] = format_datetime

def init_db():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,

        role TEXT NOT NULL
            CHECK(role IN ('ADMIN', 'THERAPIST', 'PARENT')),

        must_change_password INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,

        approval_status TEXT NOT NULL
            CHECK(
                approval_status IN (
                    'APPROVED',
                    'PENDING',
                    'REJECTED'
                )
            )
            DEFAULT 'APPROVED'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_user_id INTEGER NOT NULL,
        full_name TEXT NOT NULL,
        date_of_birth TEXT,
        FOREIGN KEY(parent_user_id) REFERENCES users(user_id)
    )
    """)

    # UPDATED appointments table (no reschedule_requests; store status here)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        therapist_user_id INTEGER NOT NULL,
        appointment_type TEXT NOT NULL CHECK(appointment_type IN ('THERAPY','ASSESSMENT')) DEFAULT 'THERAPY',
        date_time TEXT NOT NULL,
        location TEXT,
        status TEXT NOT NULL CHECK(status IN ('Scheduled','Cancelled','Completed')) DEFAULT 'Scheduled',
        notes TEXT,

        confirmation_status TEXT NOT NULL
            CHECK(confirmation_status IN ('Pending','Accepted','Declined','Rescheduled'))
            DEFAULT 'Pending',
        update_note TEXT,
        last_updated_at TEXT,

        FOREIGN KEY(client_id) REFERENCES clients(client_id),
        FOREIGN KEY(therapist_user_id) REFERENCES users(user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS progress_notes (
        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        therapist_user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        content TEXT NOT NULL,
        FOREIGN KEY(appointment_id) REFERENCES appointments(appointment_id),
        FOREIGN KEY(therapist_user_id) REFERENCES users(user_id)
    )
    """)

    # OPTIONAL: clean old table if it exists (safe)
    cur.execute("DROP TABLE IF EXISTS reschedule_requests")

    db.commit()

    

    db.close()

def evaluate_patient_progress(
    goal_score,
    attendance_rate,
    therapist_rating
):
    if (
        goal_score >= 80
        and attendance_rate >= 80
        and therapist_rating >= 4
    ):
        return {
            "status": "Excellent Progress",
            "recommendation": "Continue the current therapy plan."
        }

    elif goal_score >= 60 and attendance_rate >= 70:
        return {
            "status": "Good Progress",
            "recommendation": "Continue monitoring the current goals."
        }

    elif goal_score >= 40:
        return {
            "status": "Moderate Progress",
            "recommendation": "Review activities and provide additional support."
        }

    else:
        return {
            "status": "Needs Attention",
            "recommendation": "Therapist should review the goals and intervention plan."
        }


# ----------------------------
# Auth helpers
# ----------------------------
def login_required(roles=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = session.get("user")

            if not user:
                flash("Please log in first.", "error")
                return redirect(url_for("home"))

            if roles and user.get("role") not in roles:
                abort(403)

            return fn(*args, **kwargs)

        return wrapper

    return decorator


@app.get("/")
def home():
    return redirect(url_for("login"))

@app.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    db = get_db()

    existing_admin = db.execute("""
        SELECT user_id
        FROM users
        WHERE role = 'ADMIN'
        LIMIT 1
    """).fetchone()

    if existing_admin:
        flash("An administrator account already exists.", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name:
            flash("Please enter your full name.", "error")

        elif not email:
            flash("Please enter an email address.", "error")

        elif len(password) < 8:
            flash(
                "Password must contain at least 8 characters.",
                "error"
            )

        elif password != confirm_password:
            flash("Passwords do not match.", "error")

        else:
            try:
                db.execute("""
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash,
                        role,
                        must_change_password,
                        is_active
                    )
                    VALUES (?, ?, ?, 'ADMIN', 0, 1)
                """, (
                    full_name,
                    email,
                    generate_password_hash(password)
                ))

                db.commit()

                flash(
                    "Administrator account created. Please log in.",
                    "ok"
                )
                return redirect(url_for("home"))

            except sqlite3.IntegrityError:
                flash(
                    "An account with that email already exists.",
                    "error"
                )

    return render_template("setup_admin.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()

        user = db.execute("""
            SELECT
                user_id,
                full_name,
                email,
                password_hash,
                role,
                must_change_password,
                is_active,
                approval_status
            FROM users
            WHERE email = ?
        """, (email,)).fetchone()

        if user is None or not check_password_hash(
            user["password_hash"],
            password
        ):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        if user["approval_status"] == "PENDING":
            flash(
                "Your therapist account is waiting for administrator approval.",
                "error"
            )
            return render_template("login.html")

        if user["approval_status"] == "REJECTED":
            flash(
                "Your therapist registration was not approved.",
                "error"
            )
            return render_template("login.html")

        if user["is_active"] == 0:
            flash(
                "This account is not active.",
                "error"
            )
            return render_template("login.html")

        session.clear()

        session["user"] = {
            "user_id": user["user_id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user["role"]
        }

        return redirect(url_for("dashboard"))

    return render_template("login.html")



@app.route("/change-password", methods=["GET", "POST"])
@login_required()
def change_password():
    user_id = session["user"]["user_id"]

    if request.method == "POST":
        current_password = request.form.get(
            "current_password",
            ""
        )
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        db = get_db()

        user = db.execute("""
            SELECT password_hash
            FROM users
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        if user is None:
            session.clear()
            flash("Account not found.", "error")
            return redirect(url_for("home"))

        if not check_password_hash(
            user["password_hash"],
            current_password
        ):
            flash("Current password is incorrect.", "error")

        elif len(new_password) < 8:
            flash(
                "New password must contain at least 8 characters.",
                "error"
            )

        elif new_password != confirm_password:
            flash("New passwords do not match.", "error")

        elif current_password == new_password:
            flash(
                "New password must be different from the current password.",
                "error"
            )

        else:
            db.execute("""
                UPDATE users
                SET password_hash = ?,
                    must_change_password = 0
                WHERE user_id = ?
            """, (
                generate_password_hash(new_password),
                user_id
            ))

            db.commit()

            flash("Password updated successfully.", "ok")
            return redirect(url_for("dashboard"))

    return render_template("change_password.html")

@app.route("/admin/create-user", methods=["GET", "POST"])
@login_required(roles=["ADMIN"])
def admin_create_user():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        temporary_password = request.form.get(
            "temporary_password",
            ""
        )
        role = request.form.get("role", "")

        if role not in ("THERAPIST", "PARENT"):
            flash(
                "Only therapist and parent accounts can be created.",
                "error"
            )

        elif not full_name:
            flash("Please enter the user's full name.", "error")

        elif not email:
            flash("Please enter the user's email.", "error")

        elif len(temporary_password) < 8:
            flash(
                "Temporary password must contain at least 8 characters.",
                "error"
            )

        else:
            db = get_db()

            try:
                db.execute("""
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash,
                        role,
                        must_change_password,
                        is_active
                    )
                    VALUES (?, ?, ?, ?, 1, 1)
                """, (
                    full_name,
                    email,
                    generate_password_hash(
                        temporary_password
                    ),
                    role
                ))

                db.commit()

                flash(
                    f"{role.title()} account created successfully.",
                    "ok"
                )
                return redirect(url_for("admin_create_user"))

            except sqlite3.IntegrityError:
                flash(
                    "An account with that email already exists.",
                    "error"
                )

    return render_template("create_user.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )
        role = request.form.get("role", "")

        if role not in ("THERAPIST", "PARENT"):
            flash("Please select a valid account type.", "error")

        elif not full_name:
            flash("Please enter your full name.", "error")

        elif not email:
            flash("Please enter your email address.", "error")

        elif len(password) < 8:
            flash(
                "Password must contain at least 8 characters.",
                "error"
            )

        elif password != confirm_password:
            flash("Passwords do not match.", "error")

        else:
            # Parent accounts can be active immediately.
            # Therapist accounts require admin approval.
            if role == "THERAPIST":
                is_active = 0
                approval_status = "PENDING"
            else:
                is_active = 1
                approval_status = "APPROVED"

            db = get_db()

            try:
                db.execute("""
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash,
                        role,
                        must_change_password,
                        is_active,
                        approval_status
                    )
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                """, (
                    full_name,
                    email,
                    generate_password_hash(password),
                    role,
                    is_active,
                    approval_status
                ))

                db.commit()

                if role == "THERAPIST":
                    flash(
                        "Registration submitted. An administrator "
                        "must approve your therapist account.",
                        "ok"
                    )
                else:
                    flash(
                        "Account created. You may now log in.",
                        "ok"
                    )

                return redirect(url_for("login"))

            except sqlite3.IntegrityError:
                flash(
                    "An account with that email already exists.",
                    "error"
                )

    return render_template("register.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/dashboard")
@login_required()
def dashboard():
    user_id = session["user"]["user_id"]
    db = get_db()

    user = db.execute("""
        SELECT must_change_password
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    if user and user["must_change_password"] == 1:
        return redirect(url_for("change_password"))

    role = session["user"]["role"]

    if role == "ADMIN":
        return redirect(url_for("admin_dashboard"))

    if role == "THERAPIST":
        return redirect(url_for("therapist_dashboard"))

    if role == "PARENT":
        return redirect(url_for("parent_dashboard"))

    session.clear()
    return redirect(url_for("home"))

@app.errorhandler(403)
def forbidden(_error):
    return render_template("403.html"), 403


# ----------------------------
# ADMIN
# ----------------------------

@app.get("/admin")
@login_required(roles=["ADMIN"])
def admin_dashboard():
    return render_template("admin.html")


@app.route("/admin/users", methods=["GET", "POST"])
@login_required(roles=["ADMIN"])
def admin_users():
    db = get_db()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        temporary_password = request.form.get(
            "temporary_password",
            ""
        )
        role = request.form.get("role", "")

        if role not in ("THERAPIST", "PARENT"):
            flash("Please select Therapist or Parent.", "error")

        elif not full_name:
            flash("Please enter the full name.", "error")

        elif not email:
            flash("Please enter the email address.", "error")

        elif len(temporary_password) < 8:
            flash(
                "Temporary password must contain at least 8 characters.",
                "error"
            )

        else:
            try:
                db.execute("""
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash,
                        role,
                        must_change_password,
                        is_active,
                        approval_status
                    )
                    VALUES (?, ?, ?, ?, 1, 1, 'APPROVED')
                """, (
                    full_name,
                    email,
                    generate_password_hash(
                        temporary_password
                    ),
                    role
                ))

                db.commit()

                flash(
                    f"{role.title()} account created successfully.",
                    "ok"
                )

                return redirect(url_for("admin_users"))

            except sqlite3.IntegrityError:
                flash(
                    "An account with that email already exists.",
                    "error"
                )

    users = db.execute("""
        SELECT
            user_id,
            full_name,
            email,
            role,
            is_active,
            approval_status
        FROM users
        WHERE role IN ('THERAPIST', 'PARENT')
        ORDER BY full_name
    """).fetchall()

    return render_template(
        "admin_users.html",
        users=users
    )



@app.route("/admin/clients", methods=["GET", "POST"])
@login_required(roles=["ADMIN"])
def admin_clients():
    db = get_db()

    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        parent_user_id = request.form.get("parent_user_id")

        if not client_name:
            flash("Please enter the client's full name.", "error")

        elif not parent_user_id:
            flash("Please select a parent.", "error")

        else:
            parent = db.execute("""
                SELECT user_id
                FROM users
                WHERE user_id = ?
                  AND role = 'PARENT'
                  AND is_active = 1
            """, (parent_user_id,)).fetchone()

            if not parent:
                flash("The selected parent account is invalid.", "error")

            else:
                db.execute("""
                    INSERT INTO clients (
                        full_name,
                        parent_user_id
                    )
                    VALUES (?, ?)
                """, (
                    client_name,
                    parent_user_id
                ))

                db.commit()

                flash("Client registered successfully.", "ok")
                return redirect(url_for("admin_clients"))

    parents = db.execute("""
        SELECT
            user_id,
            full_name,
            email
        FROM users
        WHERE role = 'PARENT'
          AND is_active = 1
          AND approval_status = 'APPROVED'
        ORDER BY full_name
    """).fetchall()

    clients = db.execute("""
        SELECT
            c.client_id,
            c.full_name AS client_name,
            u.full_name AS parent_name,
            u.email AS parent_email
        FROM clients c
        JOIN users u
            ON u.user_id = c.parent_user_id
        ORDER BY c.full_name
    """).fetchall()

    return render_template(
        "admin_clients.html",
        parents=parents,
        clients=clients
    )

@app.post("/admin/user/<int:user_id>/approve")
@login_required(roles=["ADMIN"])
def admin_approve_user(user_id):
    db = get_db()

    db.execute("""
        UPDATE users
        SET approval_status = 'APPROVED',
            is_active = 1
        WHERE user_id = ?
          AND role = 'THERAPIST'
    """, (user_id,))

    db.commit()

    flash("Therapist account approved.", "ok")
    return redirect(url_for("admin_users"))

@app.post("/admin/user/<int:user_id>/reject")
@login_required(roles=["ADMIN"])
def admin_reject_user(user_id):
    db = get_db()

    db.execute("""
        UPDATE users
        SET approval_status = 'REJECTED',
            is_active = 0
        WHERE user_id = ?
          AND role = 'THERAPIST'
    """, (user_id,))

    db.commit()

    flash("Therapist account rejected.", "ok")
    return redirect(url_for("admin_users"))

@app.post("/admin/users/<int:user_id>/<action>")
@login_required(roles=["ADMIN"])
def admin_user_action(user_id, action):
    db = get_db()

    user = db.execute("""
        SELECT
            user_id,
            role,
            approval_status,
            is_active
        FROM users
        WHERE user_id = ?
          AND role IN ('PARENT', 'THERAPIST')
    """, (user_id,)).fetchone()

    if not user:
        flash("User account not found.", "error")
        return redirect(url_for("admin_users"))

    if action == "approve":
        if user["role"] != "THERAPIST":
            flash(
                "Only therapist registrations require approval.",
                "error"
            )
            return redirect(url_for("admin_users"))

        db.execute("""
            UPDATE users
            SET approval_status = 'APPROVED',
                is_active = 1
            WHERE user_id = ?
        """, (user_id,))

        flash("Therapist account approved.", "ok")

    elif action == "reject":
        if user["role"] != "THERAPIST":
            flash(
                "Only therapist registrations can be rejected.",
                "error"
            )
            return redirect(url_for("admin_users"))

        db.execute("""
            UPDATE users
            SET approval_status = 'REJECTED',
                is_active = 0
            WHERE user_id = ?
        """, (user_id,))

        flash("Therapist account rejected.", "ok")

    elif action == "activate":
        if (
            user["role"] == "THERAPIST"
            and user["approval_status"] != "APPROVED"
        ):
            flash(
                "Approve the therapist account before activating it.",
                "error"
            )
            return redirect(url_for("admin_users"))

        db.execute("""
            UPDATE users
            SET is_active = 1
            WHERE user_id = ?
        """, (user_id,))

        flash("Account activated.", "ok")

    elif action == "deactivate":
        db.execute("""
            UPDATE users
            SET is_active = 0
            WHERE user_id = ?
        """, (user_id,))

        flash("Account deactivated.", "ok")

    else:
        flash("Invalid account action.", "error")
        return redirect(url_for("admin_users"))

    db.commit()

    return redirect(url_for("admin_users"))

@app.get("/admin/appointments")
@login_required(roles=["ADMIN"])
def admin_appointments():
    db = get_db()

    clients = db.execute("""
        SELECT
            c.client_id,
            c.full_name AS client_name,
            u.full_name AS parent_name
        FROM clients c
        JOIN users u
            ON u.user_id = c.parent_user_id
        ORDER BY c.full_name
    """).fetchall()

    therapists = db.execute("""
        SELECT user_id, full_name
        FROM users
        WHERE role = 'THERAPIST'
          AND is_active = 1
        ORDER BY full_name
    """).fetchall()

    appointments = db.execute("""
        SELECT
            a.appointment_id,
            a.date_time,
            a.status,
            a.location,
            a.appointment_type,
            a.confirmation_status,
            c.full_name AS client_name,
            t.full_name AS therapist_name
        FROM appointments a
        JOIN clients c
            ON c.client_id = a.client_id
        JOIN users t
            ON t.user_id = a.therapist_user_id
        ORDER BY a.date_time DESC
        LIMIT 20
    """).fetchall()

    return render_template(
        "admin_appointments.html",
        clients=clients,
        therapists=therapists,
        appointments=appointments
    )


@app.post("/admin/schedule")
@login_required(roles=["ADMIN"])
def admin_schedule():
    client_id = request.form.get("client_id")
    therapist_id = request.form.get("therapist_id")
    date_time = request.form.get("date_time")  # datetime-local
    location = request.form.get("location", "").strip()
    notes = request.form.get("notes", "").strip()
    appointment_type = request.form.get("appointment_type", "THERAPY")

    if not (client_id and therapist_id and date_time):
        flash("Please fill client, therapist, and date/time.", "error")
        return redirect(url_for("admin_appointments"))

    dt = date_time.replace("T", " ")
    now = now_str()

    db = get_db()

    # Optional conflict check: same therapist + same datetime + scheduled
    conflict = db.execute("""
        SELECT 1 FROM appointments
        WHERE therapist_user_id=? AND date_time=? AND status='Scheduled'
    """, (therapist_id, dt)).fetchone()

    if conflict:
        flash("Therapist not available for that time. Choose another slot.", "error")
        return redirect(url_for("admin_appointments"))

    db.execute("""
        INSERT INTO appointments(
            client_id, therapist_user_id, appointment_type, date_time,
            location, status, notes,
            confirmation_status, update_note, last_updated_at
        )
        VALUES(?, ?, ?, ?, ?, 'Scheduled', ?, 'Pending', ?, ?)
    """, (
        client_id, therapist_id, appointment_type, dt,
        location, notes,
        "Created. Waiting parent confirmation (WhatsApp).", now
    ))
    db.commit()

    flash("Appointment scheduled (Confirmation: Pending).", "ok")
    return redirect(url_for("admin_appointments"))


@app.post("/admin/appointment/<int:appointment_id>/update")
@login_required(roles=["ADMIN"])
def admin_update_appointment(appointment_id: int):
    therapist_id = request.form.get("therapist_id")
    date_time = request.form.get("date_time")
    location = request.form.get("location", "").strip()
    update_note = request.form.get("update_note", "").strip()

    if not (therapist_id and date_time):
        flash("Therapist and date/time are required.", "error")
        return redirect(url_for("admin_appointments"))

    dt = date_time.replace("T", " ")
    now = now_str()

    db = get_db()

    # conflict check excluding current appointment
    conflict = db.execute("""
        SELECT 1 FROM appointments
        WHERE therapist_user_id=? AND date_time=? AND status='Scheduled'
          AND appointment_id <> ?
    """, (therapist_id, dt, appointment_id)).fetchone()

    if conflict:
        flash("Therapist not available for that time.", "error")
        return redirect(url_for("admin_appointments"))

    db.execute("""
        UPDATE appointments
        SET therapist_user_id=?,
            date_time=?,
            location=?,
            confirmation_status='Rescheduled',
            update_note=?,
            last_updated_at=?
        WHERE appointment_id=?
    """, (
        therapist_id, dt, location,
        update_note or "Rescheduled after WhatsApp discussion.",
        now, appointment_id
    ))
    db.commit()

    flash("Appointment updated (Rescheduled).", "ok")
    return redirect(url_for("admin_appointments"))


@app.post("/admin/appointment/<int:appointment_id>/confirmation")
@login_required(roles=["ADMIN"])
def admin_update_confirmation(appointment_id: int):
    confirmation_status = request.form.get("confirmation_status")
    update_note = request.form.get("update_note", "").strip()
    now = now_str()

    if confirmation_status not in ("Pending", "Accepted", "Declined", "Rescheduled"):
        flash("Invalid confirmation status.", "error")
        return redirect(url_for("admin_appointments"))

    db = get_db()
    db.execute("""
        UPDATE appointments
        SET confirmation_status = ?,
            last_updated_at = ?
        WHERE appointment_id = ?
    """, (
        confirmation_status,
        now,
        appointment_id
    ))
    db.commit()

    flash("Confirmation status updated.", "ok")
    return redirect(url_for("admin_appointments"))

@app.get("/admin/progress-notes")
@login_required(roles=["ADMIN"])
def admin_progress_notes():
    db = get_db()

    notes = db.execute("""
        SELECT
            pn.note_id,
            pn.content,
            pn.created_at,
            c.full_name AS client_name,
            u.full_name AS therapist_name,
            a.appointment_type,
            a.date_time
        FROM progress_notes pn
        JOIN appointments a
            ON a.appointment_id = pn.appointment_id
        JOIN clients c
            ON c.client_id = a.client_id
        JOIN users u
            ON u.user_id = pn.therapist_user_id
        ORDER BY pn.created_at DESC
    """).fetchall()

    return render_template(
        "admin_progress_notes.html",
        notes=notes
    )

@app.get("/admin/progress-status")
@login_required(roles=["ADMIN"])
def admin_progress_status():
    db = get_db()

    statuses = db.execute("""
        SELECT
            pn.note_id,
            pn.goal_score,
            pn.attendance_rate,
            pn.therapist_rating,
            pn.progress_status,
            pn.ai_recommendation,
            pn.created_at,
            c.full_name AS client_name,
            u.full_name AS therapist_name,
            a.appointment_type,
            a.date_time
        FROM progress_notes pn
        JOIN appointments a
            ON a.appointment_id = pn.appointment_id
        JOIN clients c
            ON c.client_id = a.client_id
        JOIN users u
            ON u.user_id = pn.therapist_user_id
        ORDER BY pn.created_at DESC
    """).fetchall()

    return render_template(
        "admin_progress_status.html",
        statuses=statuses
    )

# ----------------------------
# THERAPIST: dashboard
# ----------------------------
@app.get("/therapist")
@login_required(roles=["THERAPIST"])
def therapist_dashboard():
    therapist_id = session["user"]["user_id"]
    db = get_db()

    # Count all appointments assigned to the therapist
    session_count = db.execute("""
        SELECT COUNT(*) AS total
        FROM appointments
        WHERE therapist_user_id = ?
    """, (therapist_id,)).fetchone()["total"]

    # Count all progress notes
    note_count = db.execute("""
        SELECT COUNT(*) AS total
        FROM progress_notes
        WHERE therapist_user_id = ?
    """, (therapist_id,)).fetchone()["total"]

    # Count all AI progress evaluations
    progress_status_count = db.execute("""
        SELECT COUNT(*) AS total
        FROM progress_notes
        WHERE therapist_user_id = ?
          AND progress_status IS NOT NULL
          AND TRIM(progress_status) <> ''
    """, (therapist_id,)).fetchone()["total"]

    print("Therapist ID:", therapist_id)
    print("Session count:", session_count)
    print("Note count:", note_count)
    print("Progress status count:", progress_status_count)

    return render_template(
        "therapist_dashboard.html",
        session_count=session_count,
        note_count=note_count,
        progress_status_count=progress_status_count
    )


# ----------------------------
# THERAPIST: assigned sessions
# ----------------------------
@app.get("/therapist/sessions")
@login_required(roles=["THERAPIST"])
def therapist_sessions():
    therapist_id = session["user"]["user_id"]
    db = get_db()

    sessions = db.execute("""
        SELECT
            a.appointment_id,
            a.date_time,
            a.appointment_type,
            a.status,
            a.location,
            a.confirmation_status,
            c.full_name AS client_name
        FROM appointments a
        JOIN clients c
            ON c.client_id = a.client_id
        WHERE a.therapist_user_id = ?
        ORDER BY a.date_time DESC
    """, (therapist_id,)).fetchall()

    return render_template(
        "therapist_sessions.html",
        sessions=sessions
    )


# ----------------------------
# THERAPIST: progress notes page
# ----------------------------
@app.get("/therapist/progress-notes")
@login_required(roles=["THERAPIST"])
def therapist_progress_notes():
    therapist_id = session["user"]["user_id"]
    db = get_db()

    sessions = db.execute("""
        SELECT
            a.appointment_id,
            a.date_time,
            a.confirmation_status,
            c.full_name AS client_name
        FROM appointments a
        JOIN clients c
            ON c.client_id = a.client_id
        WHERE a.therapist_user_id = ?
        ORDER BY a.date_time DESC
    """, (therapist_id,)).fetchall()

    notes = db.execute("""
        SELECT
            pn.note_id,
            pn.created_at,
            pn.content,
            pn.goal_score,
            pn.attendance_rate,
            pn.therapist_rating,
            pn.progress_status,
            pn.ai_recommendation,
            a.appointment_id,
            c.full_name AS client_name
        FROM progress_notes pn
        JOIN appointments a
            ON a.appointment_id = pn.appointment_id
        JOIN clients c
            ON c.client_id = a.client_id
        WHERE pn.therapist_user_id = ?
        ORDER BY pn.note_id DESC
        LIMIT 10
    """, (therapist_id,)).fetchall()

    return render_template(
        "therapist_progress_notes.html",
        sessions=sessions,
        notes=notes
    )


# ----------------------------
# THERAPIST: save progress note
# ----------------------------
@app.post("/therapist/note")
@login_required(roles=["THERAPIST"])
def therapist_add_note():
    therapist_id = session["user"]["user_id"]
    appointment_id = request.form.get("appointment_id")
    content = request.form.get("content", "").strip()

    try:
        goal_score = int(request.form.get("goal_score", 0))
        attendance_rate = int(request.form.get("attendance_rate", 0))
        therapist_rating = int(request.form.get("therapist_rating", 0))
    except ValueError:
        flash("Please enter valid progress values.", "error")
        return redirect(url_for("therapist_progress_notes"))

    if not appointment_id or not content:
        flash("Please select a session and write a note.", "error")
        return redirect(url_for("therapist_progress_notes"))

    if not 0 <= goal_score <= 100:
        flash("Goal score must be between 0 and 100.", "error")
        return redirect(url_for("therapist_progress_notes"))

    if not 0 <= attendance_rate <= 100:
        flash("Attendance rate must be between 0 and 100.", "error")
        return redirect(url_for("therapist_progress_notes"))

    if not 1 <= therapist_rating <= 5:
        flash("Therapist rating must be between 1 and 5.", "error")
        return redirect(url_for("therapist_progress_notes"))

    db = get_db()

    appt = db.execute("""
        SELECT appointment_id
        FROM appointments
        WHERE appointment_id = ?
          AND therapist_user_id = ?
    """, (appointment_id, therapist_id)).fetchone()

    if not appt:
        flash("You cannot write a note for this session.", "error")
        return redirect(url_for("therapist_progress_notes"))

    ai_result = evaluate_patient_progress(
        goal_score,
        attendance_rate,
        therapist_rating
    )

    db.execute("""
        INSERT INTO progress_notes (
            appointment_id,
            therapist_user_id,
            created_at,
            content,
            goal_score,
            attendance_rate,
            therapist_rating,
            progress_status,
            ai_recommendation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        appointment_id,
        therapist_id,
        now_str(),
        content,
        goal_score,
        attendance_rate,
        therapist_rating,
        ai_result["status"],
        ai_result["recommendation"]
    ))

     # Automatically mark the appointment as completed
    db.execute("""
        UPDATE appointments
        SET status = 'Completed'
        WHERE appointment_id = ?
          AND therapist_user_id = ?
    """, (
        appointment_id,
        therapist_id
    ))

    db.commit()

    flash("Progress note and progress evaluation saved.", "ok")
    return redirect(url_for("therapist_progress_notes"))


# ----------------------------
# THERAPIST: AI progress status
# ----------------------------
@app.get("/therapist/progress-status")
@login_required(roles=["THERAPIST"])
def therapist_progress_status():
    therapist_id = session["user"]["user_id"]
    db = get_db()

    results = db.execute("""
        SELECT
            pn.note_id,
            pn.created_at,
            pn.goal_score,
            pn.attendance_rate,
            pn.therapist_rating,
            pn.progress_status,
            pn.ai_recommendation,
            a.appointment_id,
            c.full_name AS client_name
        FROM progress_notes pn
        JOIN appointments a
            ON a.appointment_id = pn.appointment_id
        JOIN clients c
            ON c.client_id = a.client_id
        WHERE pn.therapist_user_id = ?
        ORDER BY pn.note_id DESC
    """, (therapist_id,)).fetchall()

    return render_template(
        "therapist_progress_status.html",
        results=results
    )

# ----------------------------
# PARENT: view appointments (NO reschedule request in system)
# ----------------------------
@app.get("/parent")
@login_required(roles=["PARENT"])
def parent_dashboard():
    parent_id = session["user"]["user_id"]
    db = get_db()

    clients = db.execute("""
        SELECT client_id, full_name FROM clients
        WHERE parent_user_id=?
        ORDER BY full_name
    """, (parent_id,)).fetchall()

    appointments = db.execute("""
        SELECT a.appointment_id, a.date_time, a.status, a.location,
               a.appointment_type, a.confirmation_status, a.update_note,
               c.full_name AS client_name, t.full_name AS therapist_name
        FROM appointments a
        JOIN clients c ON c.client_id = a.client_id
        JOIN users t ON t.user_id = a.therapist_user_id
        WHERE c.parent_user_id=?
        ORDER BY a.date_time DESC
        LIMIT 20
    """, (parent_id,)).fetchall()

    return render_template("parent.html", clients=clients, appointments=appointments)


# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
