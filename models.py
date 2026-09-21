from datetime import datetime, date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False, default=date.today)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submissions = db.relationship("Submission", backref="event", lazy=True)


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)

    # Snapshotted so history stays intact even if the Event row changes/is removed.
    event_name = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)

    tech_name = db.Column(db.String(200), nullable=False)

    # Each stored as JSON: list of dicts, e.g. [{"item": "...", "kit": "..."}]
    misplaced_items = db.Column(db.Text, nullable=False, default="[]")
    missing_items = db.Column(db.Text, nullable=False, default="[]")
    broken_items = db.Column(db.Text, nullable=False, default="[]")

    notes = db.Column(db.Text, nullable=True)

    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
