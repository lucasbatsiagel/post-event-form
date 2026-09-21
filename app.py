import json
import os
from datetime import datetime, timedelta, date
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort

from models import db, Event, Submission

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///pullsheets.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
REPORT_TOKEN = os.environ.get("REPORT_TOKEN", "")

db.init_app(app)

with app.app_context():
    db.create_all()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def parse_item_rows(item_key, detail_key):
    """Zip two parallel form-array fields into a list of {item, detail} dicts,
    dropping rows where the item name is blank."""
    items = request.form.getlist(item_key)
    details = request.form.getlist(detail_key)
    rows = []
    for i, item in enumerate(items):
        item = item.strip()
        if not item:
            continue
        detail = details[i].strip() if i < len(details) else ""
        rows.append({"item": item, "detail": detail})
    return rows


@app.route("/")
def index():
    events = Event.query.filter_by(active=True).order_by(Event.event_date.desc()).all()
    return render_template("event_select.html", events=events)


@app.route("/event/<int:event_id>")
def event_form(event_id):
    event = Event.query.filter_by(id=event_id, active=True).first()
    if not event:
        flash("That event isn't open for reporting. Please pick again.", "error")
        return redirect(url_for("index"))
    return render_template("event_form.html", event=event)


@app.route("/submit", methods=["POST"])
def submit():
    event_id = request.form.get("event_id")
    tech_name = request.form.get("tech_name", "").strip()

    if not event_id or not tech_name:
        flash("Please select your event and enter your name.", "error")
        return redirect(url_for("index"))

    event = Event.query.get(event_id)
    if not event:
        flash("That event could not be found. Please pick again.", "error")
        return redirect(url_for("index"))

    misplaced = parse_item_rows("misplaced_item", "misplaced_kit")
    missing = parse_item_rows("missing_item", "missing_notes")
    broken = parse_item_rows("broken_item", "broken_notes")
    notes = request.form.get("notes", "").strip()

    submission = Submission(
        event_id=event.id,
        event_name=event.name,
        event_date=event.event_date,
        tech_name=tech_name,
        misplaced_items=json.dumps(misplaced),
        missing_items=json.dumps(missing),
        broken_items=json.dumps(broken),
        notes=notes,
    )
    db.session.add(submission)
    db.session.commit()

    return render_template("thanks.html", event=event, tech_name=tech_name)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == ADMIN_PIN:
            session["is_admin"] = True
            next_url = request.form.get("next") or url_for("admin_events")
            return redirect(next_url)
        flash("Incorrect PIN.", "error")
    return render_template("admin_login.html", next=request.args.get("next", ""))


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/events", methods=["GET", "POST"])
@admin_required
def admin_events():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        event_date_raw = request.form.get("event_date", "").strip()
        if not name or not event_date_raw:
            flash("Event name and date are required.", "error")
        else:
            try:
                event_date = datetime.strptime(event_date_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid date.", "error")
                return redirect(url_for("admin_events"))
            db.session.add(Event(name=name, event_date=event_date))
            db.session.commit()
            flash(f'Added "{name}".', "success")
        return redirect(url_for("admin_events"))

    events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template("admin_events.html", events=events, today=date.today().isoformat())


@app.route("/admin/events/<int:event_id>/toggle", methods=["POST"])
@admin_required
def toggle_event(event_id):
    event = Event.query.get_or_404(event_id)
    event.active = not event.active
    db.session.commit()
    return redirect(url_for("admin_events"))


@app.route("/admin/events/<int:event_id>/delete", methods=["POST"])
@admin_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash(f'Deleted "{event.name}".', "success")
    return redirect(url_for("admin_events"))


def build_report(days):
    since = datetime.utcnow() - timedelta(days=days)
    submissions = (
        Submission.query.filter(Submission.submitted_at >= since)
        .order_by(Submission.event_date.desc(), Submission.submitted_at.desc())
        .all()
    )
    report_rows = []
    for s in submissions:
        report_rows.append(
            {
                "id": s.id,
                "event_name": s.event_name,
                "event_date": s.event_date.isoformat(),
                "tech_name": s.tech_name,
                "misplaced_items": json.loads(s.misplaced_items),
                "missing_items": json.loads(s.missing_items),
                "broken_items": json.loads(s.broken_items),
                "notes": s.notes,
                "submitted_at": s.submitted_at.isoformat(),
            }
        )
    return report_rows


@app.route("/admin/report")
@admin_required
def admin_report():
    days = request.args.get("days", 7, type=int)
    rows = build_report(days)
    return render_template("report.html", rows=rows, days=days)


@app.route("/api/report")
def api_report():
    token = request.args.get("token", "")
    if not REPORT_TOKEN or token != REPORT_TOKEN:
        abort(403)
    days = request.args.get("days", 7, type=int)
    rows = build_report(days)
    return jsonify(rows=rows, days=days, generated_at=datetime.utcnow().isoformat())


@app.route("/report/email")
def report_email():
    token = request.args.get("token", "")
    if not REPORT_TOKEN or token != REPORT_TOKEN:
        abort(403)
    days = request.args.get("days", 7, type=int)
    rows = build_report(days)
    return render_template("report_email.html", rows=rows, days=days)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
