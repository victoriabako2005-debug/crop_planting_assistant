import secrets
import os

from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

import sqlite3

from flask import Flask, render_template, request, session, redirect, url_for, abort
from datetime import datetime, timedelta

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "crop-assistant-development-key")

PRODUCTION = os.environ.get("PRODUCTION") == "1"

if PRODUCTION and "SECRET_KEY" not in os.environ:
    raise RuntimeError("SECRET_KEY must be set in production")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=PRODUCTION,
)

app.permanent_session_lifetime = timedelta(days=365)

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crop_assistant.db")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id TEXT NOT NULL,
            crop TEXT NOT NULL,
            planting_date TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            days_after_planting INTEGER NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            user_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()

# Sample activity schedules.
# The offsets are illustrative and should be verified
# against local agricultural recommendations.

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_user():
    return {"current_username": session.get("username")}

def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = generate_csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(sent, expected):
            abort(400)

CROP_SCHEDULES = {
    "Maize": [
        (0, "Plant maize"),
        (7, "Check germination"),
        (14, "Inspect seedlings"),
        (21, "Check weeding requirements"),
        (30, "Monitor crop growth"),
    ],

    "Rice": [
        (0, "Plant rice"),
        (7, "Check germination"),
        (14, "Inspect seedlings"),
        (21, "Check water management"),
        (30, "Monitor crop growth"),
    ],

    "Beans": [
        (0, "Plant beans"),
        (7, "Check germination"),
        (14, "Inspect seedlings"),
        (21, "Check weeding requirements"),
        (30, "Monitor crop growth"),
    ],

    "Tomatoes": [
        (0, "Plant tomatoes"),
        (7, "Inspect young plants"),
        (14, "Check plant health"),
        (21, "Inspect for pests"),
        (30, "Monitor plant growth"),
    ],

    "Cassava": [
        (0, "Plant cassava cuttings"),
        (7, "Check planted cuttings"),
        (14, "Inspect new growth"),
        (21, "Check weeding requirements"),
        (30, "Monitor crop growth"),
    ],

    "Pepper": [
        (0, "Plant pepper"),
        (7, "Inspect young plants"),
        (14, "Check plant health"),
        (21, "Check weeding requirements"),
        (30, "Monitor plant growth"),
    ],
}

CROP_GUIDE = {
    "Maize": {
        "months": "March to May, and August to September",
        "harvest": "90 to 120 days",
        "tip": "Plant at the start of the rains. Weed early and add fertiliser about 3 weeks after planting.",
    },
    "Tomatoes": {
        "months": "April to June (rainy season), or October to November (with irrigation)",
        "harvest": "90 to 120 days",
        "tip": "Stake the plants and avoid wetting the leaves, since wet leaves encourage disease.",
    },
    "Okra": {
        "months": "March to July",
        "harvest": "50 to 65 days",
        "tip": "Harvest pods often, while they are young and tender, to keep the plant producing.",
    },
    "Cassava": {
        "months": "April to October",
        "harvest": "9 to 12 months",
        "tip": "Use healthy stem cuttings and plant them on mounds or ridges for good drainage.",
    },
    "Pepper": {
        "months": "March to May, and September to October",
        "harvest": "90 to 150 days",
        "tip": "Raise seedlings in a nursery first, then transplant after about 4 to 6 weeks.",
    },
}

@app.route("/")
@login_required
def home():
    calendar_id = session.get("calendar_id")
    due_tasks = []

    if calendar_id:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM activities WHERE calendar_id = ? AND done = 0",
            (calendar_id,),
        ).fetchall()
        conn.close()

        today = datetime.now().date()

        for row in rows:
            activity = dict(row)
            activity_date = datetime.strptime(activity["date"], "%d %B %Y").date()

            if activity_date <= today:
                activity["status"] = "overdue" if activity_date < today else "today"
                activity["sort_date"] = activity_date
                due_tasks.append(activity)

        due_tasks.sort(key=lambda a: a["sort_date"])

    return render_template("index.html", guide=CROP_GUIDE, due_tasks=due_tasks)


@app.route("/reminders")
@login_required
def reminders():
    calendar_id = session.get("calendar_id")
    my_calendars = session.get("my_calendars", [])

    calendar_list = []
    if my_calendars:
        conn = get_db()
        placeholders = ",".join("?" * len(my_calendars))
        calendar_list = conn.execute(
            f"""
            SELECT calendar_id, crop, planting_date
            FROM activities
            WHERE calendar_id IN ({placeholders})
            GROUP BY calendar_id
            ORDER BY MIN(id) DESC
            """,
            my_calendars,
        ).fetchall()
        conn.close()

    activities = []
    if calendar_id:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM activities WHERE calendar_id = ? ORDER BY id",
            (calendar_id,),
        ).fetchall()
        conn.close()

        today = datetime.now().date()

        for row in rows:
            activity = dict(row)
            activity["sort_date"] = datetime.strptime(activity["date"], "%d %B %Y")
            activity_date = datetime.strptime(activity["date"], "%d %B %Y").date()

            if activity["done"]:
                activity["status"] = "done"
            elif activity_date < today:
                activity["status"] = "overdue"
            elif activity_date == today:
                activity["status"] = "today"
            else:
                activity["status"] = "upcoming"

            activities.append(activity)
            activities.sort(key=lambda a: a["sort_date"])     

    total = len(activities)
    counts = {
        "overdue": sum(1 for a in activities if a["status"] == "overdue"),
        "today": sum(1 for a in activities if a["status"] == "today"),
        "upcoming": sum(1 for a in activities if a["status"] == "upcoming"),
        "done": sum(1 for a in activities if a["status"] == "done"),
    }
    progress = round(counts["done"] / total * 100) if total else 0

    return render_template(
        "reminders.html",
        crop=activities[0]["crop"] if activities else None,
        planting_date=activities[0]["planting_date"] if activities else None,
        activities=activities,
        counts=counts,
        progress=progress,
        calendar_list=calendar_list,
        current_calendar=calendar_id,
    )

@app.route("/complete/<int:activity_id>", methods=["POST"])
@login_required
def complete_activity(activity_id):
    calendar_id = session.get("calendar_id")

    if calendar_id:
        conn = get_db()
        conn.execute(
            "UPDATE activities SET done = 1 WHERE id = ? AND calendar_id = ?",
            (activity_id, calendar_id),
        )
        conn.commit()
        conn.close()

    return redirect(url_for("reminders"))
    
@app.route("/select/<calendar_id>")
@login_required
def select_calendar(calendar_id):
    if calendar_id in session.get("my_calendars", []):
        session["calendar_id"] = calendar_id
    return redirect(url_for("reminders"))

@app.route("/delete/<calendar_id>", methods=["POST"])
@login_required
def delete_calendar(calendar_id):
    my_calendars = session.get("my_calendars", [])

    if calendar_id in my_calendars:
        conn = get_db()
        conn.execute(
            "DELETE FROM activities WHERE calendar_id = ?",
            (calendar_id,),
        )
        conn.execute(
            "DELETE FROM notes WHERE calendar_id = ?",    
            (calendar_id,),
        )
        conn.commit()
        conn.close()

        my_calendars.remove(calendar_id)
        session["my_calendars"] = my_calendars

    if session.get("calendar_id") == calendar_id:
            session["calendar_id"] = my_calendars[-1] if my_calendars else None

    return redirect(url_for("reminders"))

@app.route("/add_activity", methods=["POST"])
@login_required
def add_activity():
    calendar_id = session.get("calendar_id")
    name = request.form.get("name", "").strip()
    date_text = request.form.get("date", "")

    if calendar_id and name and date_text:
        conn = get_db()
        first = conn.execute(
            "SELECT crop, planting_date FROM activities WHERE calendar_id = ? LIMIT 1",
            (calendar_id,),
        ).fetchone()

        if first:
            activity_date = datetime.strptime(date_text, "%Y-%m-%d")
            planting = datetime.strptime(first["planting_date"], "%d %B %Y")
            days = (activity_date - planting).days

            conn.execute(
                """
                INSERT INTO activities
                (calendar_id, crop, planting_date, name, date, days_after_planting)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    calendar_id,
                    first["crop"],
                    first["planting_date"],
                    name,
                    activity_date.strftime("%d %B %Y"),
                    days,
                ),
            )
            conn.commit()
        conn.close()

    return redirect(url_for("reminders"))

@app.route("/notes")
@login_required
def notes():
    calendar_id = session.get("calendar_id")

    notes_list = []
    crop = None

    if calendar_id:
        conn = get_db()
        notes_list = conn.execute(
            "SELECT * FROM notes WHERE calendar_id = ? ORDER BY id DESC",
            (calendar_id,),
        ).fetchall()
        first = conn.execute(
            "SELECT crop FROM activities WHERE calendar_id = ? LIMIT 1",
            (calendar_id,),
        ).fetchone()
        conn.close()
        crop = first["crop"] if first else None

    return render_template(
        "notes.html",
        notes=notes_list,
        crop=crop,
        has_calendar=bool(calendar_id and crop),
    )


@app.route("/add_note", methods=["POST"])
@login_required
def add_note():
    calendar_id = session.get("calendar_id")
    content = request.form.get("content", "").strip()

    if calendar_id and content:
        conn = get_db()
        conn.execute(
            "INSERT INTO notes (calendar_id, content, created_at) VALUES (?, ?, ?)",
            (calendar_id, content, datetime.now().strftime("%d %B %Y, %H:%M")),
        )
        conn.commit()
        conn.close()

    return redirect(url_for("notes"))


@app.route("/delete_note/<int:note_id>", methods=["POST"])
@login_required
def delete_note(note_id):
    calendar_id = session.get("calendar_id")

    if calendar_id:
        conn = get_db()
        conn.execute(
            "DELETE FROM notes WHERE id = ? AND calendar_id = ?",
            (note_id, calendar_id),
        )
        conn.commit()
        conn.close()

    return redirect(url_for("notes"))

@app.route("/undo/<int:activity_id>", methods=["POST"])
@login_required
def undo_activity(activity_id):
    calendar_id = session.get("calendar_id")

    if calendar_id:
        conn = get_db()
        conn.execute(
            "UPDATE activities SET done = 0 WHERE id = ? AND calendar_id = ?",
            (activity_id, calendar_id),
        )
        conn.commit()
        conn.close()

    return redirect(url_for("reminders"))


@app.route("/delete_activity/<int:activity_id>", methods=["POST"])
@login_required
def delete_activity(activity_id):
    calendar_id = session.get("calendar_id")

    if calendar_id:
        conn = get_db()
        conn.execute(
            "DELETE FROM activities WHERE id = ? AND calendar_id = ?",
            (activity_id, calendar_id),
        )
        conn.commit()
        conn.close()

    return redirect(url_for("reminders"))

@app.route("/calendar", methods=["POST"])
@login_required
def generate_calendar():

    crop = request.form.get("crop", "")
    planting_date_text = request.form.get("planting_date", "")

    # Check that the selected crop has a schedule.
    if crop not in CROP_SCHEDULES:
        return "Please select a valid crop.", 400

    # Check that the planting date is valid.
    try:
        planting_date = datetime.strptime(
            planting_date_text, "%Y-%m-%d"
        ).date()

    except ValueError:
        return "Please enter a valid planting date.", 400

    # Generate the activity dates.
    activities = []

    for days_after_planting, activity_name in CROP_SCHEDULES[crop]:

        activity_date = planting_date + timedelta(
            days=days_after_planting
        )

        activities.append({
            "name": activity_name,
            "date": activity_date.strftime("%d %B %Y"),
            "days_after_planting": days_after_planting,
        })

    session.permanent = True
    session["crop"] = crop
    session["planting_date"] = planting_date.strftime("%d %B %Y")
    session["activities"] = activities

    calendar_id = datetime.now().strftime("%Y%m%d%H%M%S%f")

    conn = get_db()
    for activity in activities:
        conn.execute(
            """
            INSERT INTO activities
            (calendar_id, crop, planting_date, name, date, days_after_planting, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                calendar_id,
                crop,
                planting_date.strftime("%d %B %Y"),
                activity["name"],
                activity["date"],
                activity["days_after_planting"],
                session["user_id"],
            ),
        )
    conn.commit()
    conn.close()

    session["calendar_id"] = calendar_id

    my_calendars = session.get("my_calendars", [])
    my_calendars.append(calendar_id)
    session["my_calendars"] = my_calendars

    return render_template(
        "calendar.html",
        crop=crop,
        planting_date=planting_date.strftime("%d %B %Y"),
        activities=activities,

    )

@app.route("/activities")
@login_required
def activities_page():
    calendar_id = session.get("calendar_id")

    months = {}
    items = []

    if calendar_id:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM activities WHERE calendar_id = ?",
            (calendar_id,),
        ).fetchall()
        conn.close()

        today = datetime.now().date()

        for row in rows:
            activity = dict(row)
            activity_date = datetime.strptime(activity["date"], "%d %B %Y")
            activity["sort_date"] = activity_date

            if activity["done"]:
                activity["status"] = "done"
            elif activity_date.date() < today:
                activity["status"] = "overdue"
            elif activity_date.date() == today:
                activity["status"] = "today"
            else:
                activity["status"] = "upcoming"

            items.append(activity)

        items.sort(key=lambda a: a["sort_date"])

        for activity in items:
            month_name = activity["sort_date"].strftime("%B %Y")
            months.setdefault(month_name, []).append(activity)

    return render_template(
        "activities.html",
        months=months,
        crop=items[0]["crop"] if items else None,
        planting_date=items[0]["planting_date"] if items else None,
        has_calendar=bool(items),
    )

@app.route("/crops")
@login_required
def crops():
    return render_template("crops.html", guide=CROP_GUIDE)

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                conn.commit()
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "That username is already taken."
            finally:
                conn.close()

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            rows = conn.execute(
                """
                SELECT calendar_id FROM activities
                WHERE user_id = ?
                GROUP BY calendar_id
                ORDER BY MIN(id)
                """,
                (user["id"],),
            ).fetchall()
            conn.close()

            my_calendars = [r["calendar_id"] for r in rows]

            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["my_calendars"] = my_calendars
            session["calendar_id"] = my_calendars[-1] if my_calendars else None

            return redirect(url_for("home"))

        conn.close()
        error = "Wrong username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html", message="Sorry, we couldn't find that page. Use the menu above to get back on track."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("404.html", message="That form could not be submitted safely (security token missing or expired). Please go back, refresh the page, and try again."), 400

if __name__ == "__main__":
    app.run(debug=True)