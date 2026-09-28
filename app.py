import base64
import io
import json
import os
import re
from datetime import datetime, timedelta, date
from functools import wraps

import qrcode
import qrcode.image.svg
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, Response, make_response

from models import db, Event, Submission

load_dotenv()

def _normalized_db_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///pullsheets.db")
    # Render/Heroku-style URLs use the old "postgres://" scheme, and some
    # providers (e.g. Neon) hand out "postgresql+psycopg://" (driver v3).
    # Force the psycopg2 driver, which is the one actually installed.
    if url.startswith(("postgres://", "postgresql://", "postgresql+")):
        url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg2://", url, count=1)
    return url


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = _normalized_db_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
REPORT_TOKEN = os.environ.get("REPORT_TOKEN", "")

db.init_app(app)

with app.app_context():
    db.create_all()


def _logo_data_uri():
    path = os.path.join(app.root_path, "static", "img", "siagel-logo.png")
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


LOGO_DATA_URI = _logo_data_uri()


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


@app.route("/event/<int:event_id>/qr.svg")
def event_qr(event_id):
    event = Event.query.filter_by(id=event_id, active=True).first_or_404()
    form_url = url_for("event_form", event_id=event.id, _external=True)
    img = qrcode.make(form_url, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


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


def weekend_bounds(reference=None):
    """Return (friday, sunday) for the weekend most relevant to `reference`:
    the current weekend if today is Fri/Sat/Sun, otherwise the last one."""
    ref = reference or date.today()
    weekday = ref.weekday()  # Monday=0 ... Sunday=6
    if weekday >= 4:
        friday = ref - timedelta(days=weekday - 4)
    else:
        friday = ref - timedelta(days=weekday + 3)
    return friday, friday + timedelta(days=2)


def _item_phrase(items, verb):
    """['Fog Machine'] + 'missing' -> 'Fog Machine missing'
    ['A', 'B', 'C'] + 'damaged' -> 'A, B, and C damaged'"""
    names = [i["item"] for i in items]
    if len(names) == 1:
        joined = names[0]
    elif len(names) == 2:
        joined = f"{names[0]} and {names[1]}"
    else:
        joined = ", ".join(names[:-1]) + f", and {names[-1]}"
    return f"{joined} {verb}"


def build_weekend_report(reference=None):
    """Synthesize the weekend's submissions into a narrative summary (an
    executive-summary paragraph plus short per-crew highlights) instead of
    a raw item-by-item transcript."""
    friday, sunday = weekend_bounds(reference)
    submissions = (
        Submission.query.filter(Submission.event_date >= friday, Submission.event_date <= sunday)
        .order_by(Submission.event_date.asc(), Submission.event_name.asc(), Submission.submitted_at.asc())
        .all()
    )

    highlights = []
    events_seen = set()
    clean_count = 0
    totals = {"missing": 0, "broken": 0, "misplaced": 0}
    event_issue_counts = {}

    for s in submissions:
        events_seen.add((s.event_name, s.event_date))
        m_items = json.loads(s.missing_items)
        b_items = json.loads(s.broken_items)
        p_items = json.loads(s.misplaced_items)
        totals["missing"] += len(m_items)
        totals["broken"] += len(b_items)
        totals["misplaced"] += len(p_items)

        if not (m_items or b_items or p_items):
            clean_count += 1
            continue

        phrases = []
        if m_items:
            phrases.append(_item_phrase(m_items, "missing"))
        if b_items:
            phrases.append(_item_phrase(b_items, "damaged"))
        if p_items:
            phrases.append(_item_phrase(p_items, "misplaced"))

        highlights.append(
            {
                "tech_name": s.tech_name,
                "event_name": s.event_name,
                "summary": "; ".join(phrases),
                "notes": s.notes,
            }
        )
        event_issue_counts[s.event_name] = event_issue_counts.get(s.event_name, 0) + len(m_items) + len(b_items) + len(p_items)

    stats = {
        "events": len(events_seen),
        "submissions": len(submissions),
        "missing": totals["missing"],
        "broken": totals["broken"],
        "misplaced": totals["misplaced"],
    }

    narrative = build_weekend_narrative(friday, sunday, stats, clean_count, event_issue_counts)

    return friday, sunday, stats, narrative, highlights, clean_count


def build_weekend_narrative(friday, sunday, stats, clean_count, event_issue_counts):
    date_range = f"{friday.strftime('%B %-d')}–{sunday.strftime('%-d, %Y')}"

    if stats["submissions"] == 0:
        return f"No return reports were submitted for the weekend of {date_range}."

    total_flagged = stats["missing"] + stats["broken"] + stats["misplaced"]

    if total_flagged == 0:
        tone = "a clean weekend across the board"
    elif total_flagged <= 2:
        tone = "a mostly clean weekend, with just a couple of items to follow up on"
    elif total_flagged <= 6:
        tone = "a fairly typical weekend, with a handful of items that need attention"
    else:
        tone = "a rougher weekend than usual, with a notable number of items flagged"

    sentence = (
        f"Across {stats['events']} event{'s' if stats['events'] != 1 else ''} and "
        f"{stats['submissions']} crew submission{'s' if stats['submissions'] != 1 else ''} "
        f"over {date_range}, it was {tone}."
    )

    if total_flagged:
        breakdown = []
        if stats["missing"]:
            breakdown.append(f"{stats['missing']} missing")
        if stats["broken"]:
            breakdown.append(f"{stats['broken']} broken or damaged")
        if stats["misplaced"]:
            breakdown.append(f"{stats['misplaced']} misplaced")
        sentence += (
            f" In total, {', '.join(breakdown)} item{'s' if total_flagged != 1 else ''} "
            f"{'were' if total_flagged != 1 else 'was'} flagged."
        )

    if event_issue_counts:
        worst_event = max(event_issue_counts, key=event_issue_counts.get)
        if len(event_issue_counts) > 1 or event_issue_counts[worst_event] > 1:
            sentence += f" {worst_event} accounted for the most flagged items."

    if clean_count:
        sentence += (
            f" {clean_count} of {stats['submissions']} crew{'s' if stats['submissions'] != 1 else ''} "
            f"reported a fully clean return."
        )

    return sentence


@app.route("/admin/report/weekend")
@admin_required
def admin_report_weekend():
    friday, sunday, stats, narrative, highlights, clean_count = build_weekend_report()
    return render_template(
        "report_weekend.html",
        friday=friday,
        sunday=sunday,
        stats=stats,
        narrative=narrative,
        highlights=highlights,
        clean_count=clean_count,
    )


@app.route("/admin/report/weekend/download")
@admin_required
def admin_report_weekend_download():
    friday, sunday, stats, narrative, highlights, clean_count = build_weekend_report()
    html = render_template(
        "report_weekend_download.html",
        friday=friday,
        sunday=sunday,
        stats=stats,
        narrative=narrative,
        highlights=highlights,
        clean_count=clean_count,
        logo_data_uri=LOGO_DATA_URI,
        generated_at=datetime.utcnow(),
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="weekend-report-{friday.isoformat()}-to-{sunday.isoformat()}.html"'
    )
    return response


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
