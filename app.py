import sqlite3
from datetime import datetime
from functools import wraps
from collections import Counter
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

def calculate_age(date_of_birth):
    if not date_of_birth:
        return None

    try:
        birth_date = datetime.strptime(
            date_of_birth,
            "%Y-%m-%d"
        ).date()

        today = datetime.now().date()

        age = today.year - birth_date.year

        if (
            today.month,
            today.day
        ) < (
            birth_date.month,
            birth_date.day
        ):
            age -= 1

        return age

    except (TypeError, ValueError):
        return None

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
            CHECK(role IN ('ADMIN', 'THERAPIST', 'PARENT', 'PATIENT')),

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

    # Check whether users table already supports PATIENT
    users_sql = cur.execute("""
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
        AND name = 'users'
    """).fetchone()

    if users_sql and "'PATIENT'" not in users_sql[0]:

        cur.execute("""
            CREATE TABLE users_new (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,

                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,

                role TEXT NOT NULL
                    CHECK(
                        role IN (
                            'ADMIN',
                            'THERAPIST',
                            'PARENT',
                            'PATIENT'
                        )
                    ),

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
            INSERT INTO users_new (
                user_id,
                full_name,
                email,
                password_hash,
                role,
                must_change_password,
                is_active,
                approval_status
            )
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
        """)

        cur.execute("""
            DROP TABLE users
        """)

        cur.execute("""
            ALTER TABLE users_new
            RENAME TO users
        """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_user_id INTEGER,
        patient_user_id INTEGER,
        full_name TEXT NOT NULL,
        date_of_birth TEXT,
        gender TEXT,
        diagnosis TEXT,
        created_at TEXT,
        FOREIGN KEY(parent_user_id) REFERENCES users(user_id),
        FOREIGN KEY(patient_user_id) REFERENCES users(user_id)
    )
    """)

    client_columns = {
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(clients)"
        ).fetchall()
    }

    if "date_of_birth" not in client_columns:
        cur.execute("""
            ALTER TABLE clients
            ADD COLUMN date_of_birth TEXT
        """)

    if "gender" not in client_columns:
        cur.execute("""
            ALTER TABLE clients
            ADD COLUMN gender TEXT
        """)

    if "diagnosis" not in client_columns:
        cur.execute("""
            ALTER TABLE clients
            ADD COLUMN diagnosis TEXT
        """)

    if "created_at" not in client_columns:
        cur.execute("""
            ALTER TABLE clients
            ADD COLUMN created_at TEXT
        """)

    if "patient_user_id" not in client_columns:
        cur.execute("""
            ALTER TABLE clients
            ADD COLUMN patient_user_id INTEGER
        """)

    # Check whether parent_user_id is still NOT NULL
    client_info = cur.execute(
        "PRAGMA table_info(clients)"
    ).fetchall()

    parent_column = next(
        (
            row
            for row in client_info
            if row[1] == "parent_user_id"
        ),
        None
    )

    if parent_column and parent_column[3] == 1:

        cur.execute("""
            CREATE TABLE clients_new (
                client_id INTEGER PRIMARY KEY AUTOINCREMENT,

                parent_user_id INTEGER,
                patient_user_id INTEGER,

                full_name TEXT NOT NULL,
                date_of_birth TEXT,
                gender TEXT,
                diagnosis TEXT,
                created_at TEXT,

                FOREIGN KEY(parent_user_id)
                    REFERENCES users(user_id),

                FOREIGN KEY(patient_user_id)
                    REFERENCES users(user_id)
            )
        """)

        cur.execute("""
            INSERT INTO clients_new (
                client_id,
                parent_user_id,
                patient_user_id,
                full_name,
                date_of_birth,
                gender,
                diagnosis,
                created_at
            )
            SELECT
                client_id,
                parent_user_id,
                patient_user_id,
                full_name,
                date_of_birth,
                gender,
                diagnosis,
                created_at
            FROM clients
        """)

        cur.execute("""
            DROP TABLE clients
        """)

        cur.execute("""
            ALTER TABLE clients_new
            RENAME TO clients
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

    # Ensure progress_notes has newer columns
    progress_note_columns = {
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(progress_notes)"
        ).fetchall()
    }

    if "diagnosis" not in progress_note_columns:
        cur.execute("""
            ALTER TABLE progress_notes
            ADD COLUMN diagnosis TEXT
        """)

    if "updated_at" not in progress_note_columns:
        cur.execute("""
            ALTER TABLE progress_notes
            ADD COLUMN updated_at TEXT
        """)

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
        full_name = " ".join(request.form.get("full_name", "").split()).title()
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
        full_name = " ".join(request.form.get("full_name", "").split()).title()
        email = request.form.get("email", "").strip().lower()
        temporary_password = request.form.get(
            "temporary_password",
            ""
        )
        role = request.form.get("role", "")

        if role not in ("THERAPIST", "PARENT", "PATIENT"):
            flash(
                "Please select a valid account type.",
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
        full_name = " ".join(request.form.get("full_name", "").split()).title()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )
        role = request.form.get("role", "")

        if role not in ("THERAPIST", "PARENT", "PATIENT"):
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
                cursor = db.execute("""
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

                new_user_id = cursor.lastrowid

                if role == "PATIENT":
                    db.execute("""
                        INSERT INTO clients (
                            patient_user_id,
                            full_name
                        )
                        VALUES (?, ?)
                    """, (
                        new_user_id,
                        full_name
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

    elif role == "PATIENT":
        return redirect(url_for("patient_dashboard"))

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
    conn = get_db()

    appointments_count = conn.execute(
        "SELECT COUNT(*) FROM appointments"
    ).fetchone()[0]

    users_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE role IN ('THERAPIST', 'PARENT')
        """
    ).fetchone()[0]

    clients_count = conn.execute(
        "SELECT COUNT(*) FROM clients"
    ).fetchone()[0]

    progress_notes_count = conn.execute(
    "SELECT COUNT(*) FROM progress_notes"
    ).fetchone()[0]

    progress_status_count = conn.execute("""
        SELECT COUNT(*)
        FROM progress_notes
        WHERE progress_status IS NOT NULL
    """).fetchone()[0]

    return render_template(
        "admin.html",
        appointments_count=appointments_count,
        users_count=users_count,
        clients_count=clients_count,
        progress_notes_count=progress_notes_count,
        progress_status_count=progress_status_count
    )

@app.route("/admin/users", methods=["GET", "POST"])
@login_required(roles=["ADMIN"])
def admin_users():
    db = get_db()

    if request.method == "POST":
        full_name = " ".join(request.form.get("full_name", "").split()).title()
        email = request.form.get("email", "").strip().lower()
        temporary_password = request.form.get(
            "temporary_password",
            ""
        )
        role = request.form.get("role", "")

        if role not in ("THERAPIST", "PARENT", "PATIENT"):
            flash("Only therapist, parent and patient accounts can be created.", "error")

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
        WHERE role IN ('THERAPIST', 'PARENT', 'PATIENT')
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


    # ==============================
    # REGISTER NEW PATIENT
    # ==============================
    if request.method == "POST":

        client_name = " ".join(
            request.form.get(
                "client_name",
                ""
            ).split()
        ).title()

        date_of_birth = request.form.get(
            "date_of_birth",
            ""
        ).strip()

        gender = request.form.get(
            "gender",
            ""
        ).strip().upper()

        diagnosis = request.form.get(
            "diagnosis",
            ""
        ).strip()

        link_type = request.form.get(
            "link_type",
            ""
        ).strip().upper()

        parent_user_id = request.form.get(
            "parent_user_id"
        )

        patient_user_id = request.form.get(
            "patient_user_id"
        )


        # ------------------------------
        # BASIC VALIDATION
        # ------------------------------
        if not client_name:

            flash(
                "Please enter the patient's full name.",
                "error"
            )


        elif not date_of_birth:

            flash(
                "Please enter the patient's date of birth.",
                "error"
            )


        elif gender not in {
            "MALE",
            "FEMALE"
        }:

            flash(
                "Please select the patient's gender.",
                "error"
            )


        elif link_type not in {
            "PARENT",
            "PATIENT"
        }:

            flash(
                "Please select how this patient should be linked.",
                "error"
            )


        # ==============================
        # LINK TO PARENT
        # ==============================
        elif link_type == "PARENT":

            if not parent_user_id:

                flash(
                    "Please select a parent account.",
                    "error"
                )

            else:

                parent = db.execute("""
                    SELECT
                        user_id
                    FROM users
                    WHERE user_id = ?
                      AND role = 'PARENT'
                      AND is_active = 1
                      AND approval_status = 'APPROVED'
                """, (
                    parent_user_id,
                )).fetchone()


                if not parent:

                    flash(
                        "The selected parent account is invalid.",
                        "error"
                    )

                else:

                    created_at = now_str()

                    db.execute("""
                        INSERT INTO clients (
                            full_name,
                            date_of_birth,
                            gender,
                            diagnosis,
                            parent_user_id,
                            patient_user_id,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """, (
                        client_name,
                        date_of_birth,
                        gender,
                        diagnosis,
                        parent_user_id,
                        created_at
                    ))

                    db.commit()

                    flash(
                        "Patient registered successfully.",
                        "ok"
                    )

                    return redirect(
                        url_for("admin_clients")
                    )


        # ==============================
        # LINK TO PATIENT ACCOUNT
        # ==============================
        elif link_type == "PATIENT":

            if not patient_user_id:

                flash(
                    "Please select a patient account.",
                    "error"
                )

            else:

                patient = db.execute("""
                    SELECT
                        user_id,
                        full_name
                    FROM users
                    WHERE user_id = ?
                      AND role = 'PATIENT'
                      AND is_active = 1
                      AND approval_status = 'APPROVED'
                """, (
                    patient_user_id,
                )).fetchone()


                if not patient:

                    flash(
                        "The selected patient account is invalid.",
                        "error"
                    )

                else:

                    # Prevent one Patient account
                    # from being linked more than once
                    existing_patient = db.execute("""
                        SELECT
                            client_id
                        FROM clients
                        WHERE patient_user_id = ?
                        LIMIT 1
                    """, (
                        patient_user_id,
                    )).fetchone()


                    if existing_patient:

                        flash(
                            "This patient account is already linked to a patient record.",
                            "error"
                        )

                    else:

                        created_at = now_str()

                        db.execute("""
                            INSERT INTO clients (
                                full_name,
                                date_of_birth,
                                gender,
                                diagnosis,
                                parent_user_id,
                                patient_user_id,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, NULL, ?, ?)
                        """, (
                            client_name,
                            date_of_birth,
                            gender,
                            diagnosis,
                            patient_user_id,
                            created_at
                        ))

                        db.commit()

                        flash(
                            "Patient registered successfully.",
                            "ok"
                        )

                        return redirect(
                            url_for("admin_clients")
                        )


    # ==============================
    # AVAILABLE PARENT ACCOUNTS
    # ==============================
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


    # ==============================
    # AVAILABLE PATIENT ACCOUNTS
    # ==============================
    patient_accounts = db.execute("""
        SELECT
            u.user_id,
            u.full_name,
            u.email
        FROM users u

        LEFT JOIN clients c
            ON c.patient_user_id = u.user_id

        WHERE u.role = 'PATIENT'
          AND u.is_active = 1
          AND u.approval_status = 'APPROVED'
          AND c.client_id IS NULL

        ORDER BY u.full_name
    """).fetchall()

    edit_patient_accounts = db.execute("""
    SELECT
        user_id,
        full_name,
        email

    FROM users

    WHERE role = 'PATIENT'
      AND is_active = 1
      AND approval_status = 'APPROVED'

    ORDER BY full_name
""").fetchall()


    # ==============================
    # REGISTERED PATIENTS
    # ==============================
    client_rows = db.execute("""
        SELECT
            c.client_id,
            c.full_name AS client_name,
            c.date_of_birth,
            c.gender,
            c.diagnosis,
            c.created_at,

            c.parent_user_id,
            c.patient_user_id,

            parent.full_name AS parent_name,
            parent.email AS parent_email,

            patient.full_name AS patient_account_name,
            patient.email AS patient_account_email

        FROM clients c

        LEFT JOIN users parent
            ON parent.user_id = c.parent_user_id

        LEFT JOIN users patient
            ON patient.user_id = c.patient_user_id

        ORDER BY c.full_name
    """).fetchall()


    clients = []


    for row in client_rows:

        client = dict(row)

        client["age"] = calculate_age(
            client["date_of_birth"]
        )

        clients.append(
            client
        )


    return render_template(
        "admin_clients.html",
        parents=parents,
        patient_accounts=patient_accounts,
        edit_patient_accounts=edit_patient_accounts,
        clients=clients
    )

@app.post("/admin/clients/<int:client_id>/update")
@login_required(roles=["ADMIN"])
def admin_update_client(client_id):

    db = get_db()

    client_name = " ".join(
        request.form.get("client_name", "").split()
    ).title()

    date_of_birth = request.form.get(
        "date_of_birth",
        ""
    ).strip()

    gender = request.form.get(
        "gender",
        ""
    ).strip().upper()

    diagnosis = request.form.get(
        "diagnosis",
        ""
    ).strip()

    link_type = request.form.get(
        "link_type",
        ""
    ).strip().upper()

    parent_user_id = request.form.get(
        "parent_user_id"
    )

    patient_user_id = request.form.get(
        "patient_user_id"
    )


    # ------------------------------
    # BASIC VALIDATION
    # ------------------------------
    if not client_name:

        flash(
            "Please enter the patient's full name.",
            "error"
        )

        return redirect(
            url_for("admin_clients")
        )


    if not date_of_birth:

        flash(
            "Please enter the patient's date of birth.",
            "error"
        )

        return redirect(
            url_for("admin_clients")
        )


    if gender not in (
        "MALE",
        "FEMALE"
    ):

        flash(
            "Please select the patient's gender.",
            "error"
        )

        return redirect(
            url_for("admin_clients")
        )


    if link_type not in (
        "PARENT",
        "PATIENT"
    ):

        flash(
            "Please select how this patient should be linked.",
            "error"
        )

        return redirect(
            url_for("admin_clients")
        )


    # ==============================
    # PARENT / GUARDIAN
    # ==============================
    if link_type == "PARENT":

        if not parent_user_id:

            flash(
                "Please select a parent account.",
                "error"
            )

            return redirect(
                url_for("admin_clients")
            )


        parent = db.execute("""
            SELECT user_id
            FROM users
            WHERE user_id = ?
              AND role = 'PARENT'
              AND is_active = 1
              AND approval_status = 'APPROVED'
        """, (
            parent_user_id,
        )).fetchone()


        if not parent:

            flash(
                "The selected parent account is invalid.",
                "error"
            )

            return redirect(
                url_for("admin_clients")
            )


        db.execute("""
            UPDATE clients
            SET
                full_name = ?,
                date_of_birth = ?,
                gender = ?,
                diagnosis = ?,
                parent_user_id = ?,
                patient_user_id = NULL
            WHERE client_id = ?
        """, (
            client_name,
            date_of_birth,
            gender,
            diagnosis,
            parent_user_id,
            client_id
        ))


    # ==============================
    # PATIENT ACCOUNT
    # ==============================
    elif link_type == "PATIENT":

        if not patient_user_id:

            flash(
                "Please select a patient account.",
                "error"
            )

            return redirect(
                url_for("admin_clients")
            )


        patient = db.execute("""
            SELECT user_id
            FROM users
            WHERE user_id = ?
              AND role = 'PATIENT'
              AND is_active = 1
              AND approval_status = 'APPROVED'
        """, (
            patient_user_id,
        )).fetchone()


        if not patient:

            flash(
                "The selected patient account is invalid.",
                "error"
            )

            return redirect(
                url_for("admin_clients")
            )


        existing_patient = db.execute("""
            SELECT client_id
            FROM clients
            WHERE patient_user_id = ?
              AND client_id != ?
            LIMIT 1
        """, (
            patient_user_id,
            client_id
        )).fetchone()


        if existing_patient:

            flash(
                "This patient account is already linked to another patient record.",
                "error"
            )

            return redirect(
                url_for("admin_clients")
            )


        db.execute("""
            UPDATE clients
            SET
                full_name = ?,
                date_of_birth = ?,
                gender = ?,
                diagnosis = ?,
                parent_user_id = NULL,
                patient_user_id = ?
            WHERE client_id = ?
        """, (
            client_name,
            date_of_birth,
            gender,
            diagnosis,
            patient_user_id,
            client_id
        ))


    db.commit()

    flash(
        "Patient information updated successfully.",
        "ok"
    )

    return redirect(
        url_for("admin_clients")
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
          AND role IN ('PARENT', 'THERAPIST', 'PATIENT')
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

            p.full_name AS parent_name,
            pa.full_name AS patient_account_name

        FROM clients c
        LEFT JOIN users p
            ON p.user_id = c.parent_user_id
        LEFT JOIN users pa
            ON pa.user_id = c.patient_user_id

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
        "Created. Waiting for confirmation (WhatsApp).", now
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
    status = request.form.get("status", "Scheduled").strip()

    if not (therapist_id and date_time):
        flash("Therapist and date/time are required.", "error")
        return redirect(url_for("admin_appointments"))

    if status not in (
        "Scheduled",
        "Completed",
        "Cancelled",
        "No Show"
    ):
        flash("Invalid appointment status.", "error")
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
            status=?,
            update_note=?,
            last_updated_at=?
        WHERE appointment_id=?
    """, (
        therapist_id, dt, location, status,
        update_note, now, 
        appointment_id
    ))
    db.commit()

    flash("Appointment updated successfully.", "ok")
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
            pn.updated_at,
            c.full_name AS client_name,
            c.date_of_birth,
            c.gender,
            c.diagnosis,

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
        ORDER BY COALESCE(pn.updated_at, pn.created_at) DESC
    """).fetchall()

    progress_notes = []

    for row in notes:
        note = dict(row)

        note["age"] = calculate_age(
            note["date_of_birth"]
        )

        progress_notes.append(note)

    return render_template(
        "admin_progress_notes.html",
        notes=progress_notes
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

            c.client_id,
            c.full_name AS client_name,
            c.date_of_birth,

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

        ORDER BY a.date_time ASC
    """).fetchall()

    # attendance_labels = []
    # attendance_values = []

    goal_history = {}

    attendance_history = {}

    patients = {}

    for status in statuses:

        client_id = str(status["client_id"])
        client_name = status["client_name"]


        # ==============================
        # UNIQUE PATIENTS
        # ==============================

        if client_id not in patients:

            # Format DOB for duplicate-name display
            if status["date_of_birth"]:

                dob_obj = datetime.strptime(
                    status["date_of_birth"],
                    "%Y-%m-%d"
                )

                formatted_dob = dob_obj.strftime(
                    "%d %b %Y"
                )

            else:

                formatted_dob = None

            patients[client_id] = {
                "client_id": client_id,
                "client_name": client_name,
                "date_of_birth": formatted_dob
            }


        # ==============================
        # FORMAT SESSION DATE
        # ==============================

        date_obj = datetime.strptime(
            status["date_time"],
            "%Y-%m-%d %H:%M"
        )

        formatted_date = date_obj.strftime(
            "%d %b %Y"
        )


        # ==============================
        # GOAL PROGRESS
        # ==============================

        if client_id not in goal_history:

            goal_history[client_id] = {
                "dates": [],
                "scores": []
            }


        goal_history[client_id]["dates"].append(
            formatted_date
        )

        goal_history[client_id]["scores"].append(
            status["goal_score"]
        )


        # ==============================
        # ATTENDANCE PROGRESS
        # ==============================

        if client_id not in attendance_history:

            attendance_history[client_id] = {
                "dates": [],
                "rates": []
            }


        attendance_history[client_id]["dates"].append(
            formatted_date
        )

        attendance_history[client_id]["rates"].append(
            status["attendance_rate"]
        )


    # ==============================
    # PATIENT LIST
    # ==============================

    patient_list = list(
        patients.values()
    )

    patient_list.sort(
        key=lambda patient:
        patient["client_name"].lower()
    )


    # Detect duplicate patient names
    name_counts = Counter(
        patient["client_name"].lower()
        for patient in patient_list
    )


    for patient in patient_list:

        patient["is_duplicate"] = (
            name_counts[
                patient["client_name"].lower()
            ] > 1
        )


    return render_template(
        "admin_progress_status.html",

        statuses=statuses,

        goal_history=goal_history,

        attendance_history=attendance_history,

        patient_list=patient_list
    )

# ----------------------------
# admin reports
# ----------------------------

@app.get("/admin/reports")
@login_required(roles=["ADMIN"])
def admin_reports():
    db = get_db()

    selected_year = request.args.get(
        "year",
        str(datetime.now().year)
    )

    report_data = db.execute("""
        SELECT
            strftime('%m', created_at) AS month,
            COUNT(*) AS total
        FROM clients
        WHERE strftime('%Y', created_at) = ?
        GROUP BY strftime('%m', created_at)
        ORDER BY month
    """, (selected_year,)).fetchall()

    month_names = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December"
    ]

    monthly_counts = {
        row["month"]: row["total"]
        for row in report_data
    }

    report_rows = []

    for month_number, month_name in enumerate(
        month_names,
        start=1
    ):
        month_key = f"{month_number:02d}"

        report_rows.append({
            "month_name": month_name,
            "total": monthly_counts.get(month_key, 0)
        })

    total_patients = sum(
        row["total"]
        for row in report_rows
    )

    return render_template(
        "admin_reports.html",
        report_rows=report_rows,
        selected_year=selected_year,
        total_patients=total_patients
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
            a.appointment_type,

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
            pn.updated_at,
            pn.content,

            pn.goal_score,
            pn.attendance_rate,
            pn.therapist_rating,
            pn.progress_status,
            pn.ai_recommendation,

            a.appointment_id,
            a.appointment_type,
            a.date_time,

            c.client_id,
            c.full_name AS client_name,
            c.date_of_birth,
            c.gender,
            c.diagnosis

        FROM progress_notes pn
        JOIN appointments a
            ON a.appointment_id = pn.appointment_id
        JOIN clients c
            ON c.client_id = a.client_id
        WHERE pn.therapist_user_id = ?

        ORDER BY COALESCE(pn.updated_at, pn.created_at) DESC
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
            updated_at,
            content,
            goal_score,
            attendance_rate,
            therapist_rating,
            progress_status,
            ai_recommendation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        appointment_id,
        therapist_id,
        now_str(),
        None,
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
# THERAPIST: edit progress note
# ----------------------------
@app.post("/therapist/progress-notes/<int:note_id>/edit")
@login_required(roles=["THERAPIST"])
def therapist_edit_progress_note(note_id):
    therapist_id = session["user"]["user_id"]
    db = get_db()

    content = request.form.get("content","").strip()

    if not content:
        flash(
            "Progress report are required.",
            "error"
        )
        return redirect(
            url_for("therapist_progress_notes")
        )

    note = db.execute("""
        SELECT note_id
        FROM progress_notes
        WHERE note_id = ?
          AND therapist_user_id = ?
    """, (
        note_id,
        therapist_id
    )).fetchone()

    if not note:
        flash(
            "Progress note not found.",
            "error"
        )
        return redirect(
            url_for("therapist_progress_notes")
        )

    db.execute("""
        UPDATE progress_notes
        SET
            content = ?,
            updated_at = ?
        WHERE note_id = ?
          AND therapist_user_id = ?
    """, (
        content,
        now_str(),
        note_id,
        therapist_id
    ))

    db.commit()

    flash(
        "Progress note updated successfully.",
        "ok"
    )

    return redirect(
        url_for("therapist_progress_notes")
    )

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
            a.appointment_type,
            a.date_time,

            c.client_id,
            c.full_name AS client_name,
            c.date_of_birth

        FROM progress_notes pn
        JOIN appointments a
            ON a.appointment_id = pn.appointment_id
        JOIN clients c
            ON c.client_id = a.client_id
        WHERE pn.therapist_user_id = ?
        ORDER BY a.date_time ASC
    """, (therapist_id,)).fetchall()

    goal_history = {}
    attendance_history = {}
    patients = {}

    for result in results:

        client_id = str(result["client_id"])
        client_name = result["client_name"]


        # ------------------------------
        # Unique therapist patients
        # ------------------------------

        if client_id not in patients:

            if result["date_of_birth"]:

                dob_obj = datetime.strptime(
                    result["date_of_birth"],
                    "%Y-%m-%d"
                )

                formatted_dob = dob_obj.strftime(
                    "%d %b %Y"
                )

            else:

                formatted_dob = None


            patients[client_id] = {
                "client_id": client_id,
                "client_name": client_name,
                "date_of_birth": formatted_dob
            }


        # ------------------------------
        # Format session date
        # ------------------------------

        date_obj = datetime.strptime(
            result["date_time"],
            "%Y-%m-%d %H:%M"
        )

        formatted_date = date_obj.strftime(
            "%d %b %Y"
        )


        # ------------------------------
        # Goal progress
        # ------------------------------

        if client_id not in goal_history:

            goal_history[client_id] = {
                "dates": [],
                "scores": []
            }


        goal_history[client_id]["dates"].append(
            formatted_date
        )

        goal_history[client_id]["scores"].append(
            result["goal_score"]
        )


        # ------------------------------
        # Attendance progress
        # ------------------------------

        if client_id not in attendance_history:

            attendance_history[client_id] = {
                "dates": [],
                "rates": []
            }


        attendance_history[client_id]["dates"].append(
            formatted_date
        )

        attendance_history[client_id]["rates"].append(
            result["attendance_rate"]
        )


    # ------------------------------
    # Patient selector list
    # ------------------------------

    patient_list = list(
        patients.values()
    )

    patient_list.sort(
        key=lambda patient:
        patient["client_name"].lower()
    )


    name_counts = Counter(
        patient["client_name"].lower()
        for patient in patient_list
    )


    for patient in patient_list:

        patient["is_duplicate"] = (
            name_counts[
                patient["client_name"].lower()
            ] > 1
        )


    return render_template(
        "therapist_progress_status.html",

        results=results,

        goal_history=goal_history,

        attendance_history=attendance_history,

        patient_list=patient_list
    )

# ------------------------------
# PATIENT: view own appointments and progress
# ------------------------------
@app.get("/patient")
@login_required(roles=["PATIENT"])
def patient_dashboard():

    patient_id = session["user"]["user_id"]

    db = get_db()


    # Get the client record linked to this patient account
    client = db.execute("""
        SELECT
            client_id,
            full_name,
            date_of_birth,
            gender,
            diagnosis
        FROM clients
        WHERE patient_user_id = ?
        LIMIT 1
    """, (patient_id,)).fetchone()


    # If patient has not completed their patient profile yet
    if not client:

        return render_template(
            "patient.html",
            client=None,
            appointments=[],
            upcoming_count=0,
            previous_count=0,
            progress_results=[],
            parent_progress_data={},
            patient_not_linked=True
        )


    client_id = client["client_id"]


    # ------------------------------
    # APPOINTMENTS
    # ------------------------------
    appointment_rows = db.execute("""
        SELECT
            a.appointment_id,
            a.date_time,
            a.status,
            a.location,
            a.appointment_type,
            a.confirmation_status,
            a.update_note,

            t.full_name AS therapist_name

        FROM appointments a

        JOIN users t
            ON t.user_id = a.therapist_user_id

        WHERE a.client_id = ?

        ORDER BY a.date_time DESC
    """, (client_id,)).fetchall()


    current_time = datetime.now()

    appointments = []

    upcoming_count = 0
    previous_count = 0


    for row in appointment_rows:

        appointment = dict(row)

        appointment_date = datetime.strptime(
            row["date_time"],
            "%Y-%m-%d %H:%M"
        )

        status = (
            row["status"] or ""
        ).strip().lower()


        # Previous if:
        # - completed
        # - cancelled
        # - appointment date already passed
        if (
            status in ["completed", "cancelled"]
            or appointment_date < current_time
        ):

            appointment["appointment_group"] = "previous"

            previous_count += 1

        else:

            appointment["appointment_group"] = "upcoming"

            upcoming_count += 1


        appointments.append(
            appointment
        )


    # ------------------------------
    # PROGRESS
    # ------------------------------
    progress_results = db.execute("""
        SELECT
            pn.goal_score,
            pn.progress_status,
            pn.ai_recommendation,

            a.appointment_type,
            a.date_time,

            c.client_id,
            c.full_name AS client_name

        FROM progress_notes pn

        JOIN appointments a
            ON a.appointment_id = pn.appointment_id

        JOIN clients c
            ON c.client_id = a.client_id

        WHERE c.client_id = ?

        ORDER BY a.date_time ASC
    """, (client_id,)).fetchall()


    # Keep same variable name used by patient.html
    parent_progress_data = {}


    for result in progress_results:

        progress_client_id = str(
            result["client_id"]
        )


        if progress_client_id not in parent_progress_data:

            parent_progress_data[progress_client_id] = {
                "dates": [],
                "scores": [],
                "statuses": [],
                "types": [],
                "recommendations": []
            }


        date_obj = datetime.strptime(
            result["date_time"],
            "%Y-%m-%d %H:%M"
        )


        formatted_date = date_obj.strftime(
            "%d %b %Y"
        )


        parent_progress_data[
            progress_client_id
        ]["dates"].append(
            formatted_date
        )


        parent_progress_data[
            progress_client_id
        ]["scores"].append(
            result["goal_score"]
        )


        parent_progress_data[
            progress_client_id
        ]["statuses"].append(
            result["progress_status"]
        )


        parent_progress_data[
            progress_client_id
        ]["types"].append(
            result["appointment_type"]
        )


        parent_progress_data[
            progress_client_id
        ]["recommendations"].append(
            result["ai_recommendation"]
        )


    return render_template(
        "patient.html",
        client=client,
        appointments=appointments,
        upcoming_count=upcoming_count,
        previous_count=previous_count,
        progress_results=progress_results,
        parent_progress_data=parent_progress_data
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
        SELECT  client_id, 
                full_name 
        FROM clients
        WHERE parent_user_id=?
        ORDER BY full_name
    """, (parent_id,)).fetchall()

    appointment_rows = db.execute("""
        SELECT  a.appointment_id, 
                a.date_time, 
                a.status, 
                a.location,
                a.appointment_type, 
                a.confirmation_status, 
                a.update_note,

               c.full_name AS client_name, 
               
               t.full_name AS therapist_name

        FROM appointments a
        JOIN clients c ON c.client_id = a.client_id
        JOIN users t ON t.user_id = a.therapist_user_id
        WHERE c.parent_user_id=?
        ORDER BY a.date_time DESC
    """, (parent_id,)).fetchall()

    # Current date/time
    current_time = datetime.now()

    appointments = []

    upcoming_count = 0
    previous_count = 0


    for row in appointment_rows:

        appointment = dict(row)

        appointment_date = datetime.strptime(
            row["date_time"],
            "%Y-%m-%d %H:%M"
        )

        status = (
            row["status"] or ""
        ).strip().lower()

        # Previous if:
        # - completed
        # - cancelled
        # - appointment date already passed

        if (
            status in ["completed", "cancelled"]
            or appointment_date < current_time
        ):
            appointment["appointment_group"] = "previous"

            previous_count += 1

        else:

            appointment["appointment_group"] = "upcoming"
            upcoming_count += 1

        appointments.append(
            appointment
        )

    progress_results = db.execute("""
        SELECT
            pn.goal_score,
            pn.progress_status,
            pn.ai_recommendation,

            a.appointment_type,
            a.date_time,

            c.client_id,
            c.full_name AS client_name

        FROM progress_notes pn

        JOIN appointments a
            ON a.appointment_id = pn.appointment_id

        JOIN clients c
            ON c.client_id = a.client_id

        WHERE c.parent_user_id = ?

        ORDER BY a.date_time ASC
    """, (parent_id,)).fetchall()   
    

    parent_progress_data = {}


    for result in progress_results:

        client_id = str(
            result["client_id"]
        )


        if client_id not in parent_progress_data:

            parent_progress_data[client_id] = {
                "dates": [],
                "scores": [],
                "statuses": [],
                "types": [],
                "recommendations": []
            }


        date_obj = datetime.strptime(
            result["date_time"],
            "%Y-%m-%d %H:%M"
        )


        formatted_date = date_obj.strftime(
            "%d %b %Y"
        )


        parent_progress_data[client_id]["dates"].append(
            formatted_date
        )

        parent_progress_data[client_id]["scores"].append(
            result["goal_score"]
        )

        parent_progress_data[client_id]["statuses"].append(
            result["progress_status"]
        )

        parent_progress_data[client_id]["types"].append(
            result["appointment_type"]
        )

        parent_progress_data[client_id]["recommendations"].append(
            result["ai_recommendation"]
        ) 

    return render_template(
        "parent.html",
        clients=clients,
        appointments=appointments,
        upcoming_count=upcoming_count,
        previous_count=previous_count,
        progress_results=progress_results,
        parent_progress_data=parent_progress_data
    )
   
# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
