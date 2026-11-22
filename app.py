import hmac
import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path

import psycopg
from flask import Flask, abort, g, jsonify, request
from psycopg.rows import dict_row

from business_calendar import BusinessCalendar, REPLY_TARGET, WORKWEEK

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
ROOT = Path(__file__).resolve().parent
CALENDAR = BusinessCalendar(
    date.fromisoformat(day) for day in os.getenv("FRONTDESK_HOLIDAYS", "").split(",") if day
)
ACCOUNTS = json.loads(os.getenv("FRONTDESK_ACCOUNTS", "{}"))
PUBLIC_EVENTS = ("created", "agent_reply", "customer_reply", "resolved", "reopened", "auto_closed")


def db():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def initialize():
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(4039127)")
        conn.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))


def clock(conn):
    return conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def event(conn, ticket_id, at, actor, kind, body=None):
    conn.execute(
        "INSERT INTO ticket_events(ticket_id, at, actor, kind, body) VALUES (%s,%s,%s,%s,%s)",
        (ticket_id, at, actor, kind, body),
    )


def snapshot(conn, ticket_id):
    return conn.execute("SELECT * FROM tickets WHERE id=%s", (ticket_id,)).fetchone()


def auto_close(conn):
    candidates = conn.execute(
        """SELECT id, close_due_at FROM tickets
           WHERE status='waiting' AND close_due_at <= clock_timestamp()
           ORDER BY id FOR UPDATE SKIP LOCKED"""
    ).fetchall()
    for ticket in candidates:
        conn.execute(
            "UPDATE tickets SET status='closed', closed_at=%s WHERE id=%s",
            (ticket["close_due_at"], ticket["id"]),
        )
        event(conn, ticket["id"], clock(conn), "system", "auto_closed")


def worker():
    while not threading.Event().wait(30):
        try:
            with db() as conn:
                auto_close(conn)
        except psycopg.Error:
            app.logger.exception("Automatic closure sweep failed")


def authorize(role=None):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        abort(401, "Enter an access key.")
    for identifier, account in ACCOUNTS.items():
        if hmac.compare_digest(token.encode(), account["token"].encode()):
            if role and account["role"] != role:
                abort(403)
            g.actor = identifier
            g.role = account["role"]
            return
    abort(401, "Invalid access key.")


def data():
    payload = request.get_json()
    if not isinstance(payload, dict):
        abort(400, "Expected a JSON object.")
    return payload


def required(payload, key, limit):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        abort(400, f"{key} must contain between 1 and {limit} characters.")
    return value.strip()


def milliseconds(delta):
    return delta // timedelta(milliseconds=1)


def serialize(row, now):
    keys = ("id", "subject", "status", "priority", "created_at")
    result = {key: row[key] for key in keys}
    if g.role == "agent":
        paused = timedelta(milliseconds=row["paused_ms"])
        reply_due = CALENDAR.deadline(row["created_at"], REPLY_TARGET[row["priority"]])
        resolve_due = CALENDAR.deadline(
            row["resolution_start"], timedelta(milliseconds=row["resolution_budget_ms"]) + paused
        )
        resolution_clock = row["waiting_since"] if row["status"] in ("waiting", "closed") else now
        result.update(
            owner=row["owner"], customer=row["customer"], reply_due=reply_due,
            resolution_due=resolve_due, close_due_at=row["close_due_at"],
            first_reply_at=row["first_reply_at"],
            reply_late=row["first_reply_late"] if row["first_reply_at"] else now > reply_due,
            resolution_late=row["resolution_late"] if row["resolved_at"] else resolution_clock > resolve_due,
        )
    return result


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(413)
@app.errorhandler(415)
def client_error(error):
    return jsonify(error=error.description), error.code


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1 FROM tickets LIMIT 1")
    return {"ok": True}


@app.get("/api/me")
def me():
    authorize()
    return {"id": g.actor, "role": g.role}


@app.get("/api/tickets")
def tickets():
    authorize()
    with db() as conn:
        auto_close(conn)
        if g.role == "customer":
            rows = conn.execute(
                "SELECT * FROM tickets WHERE customer=%s ORDER BY id DESC", (g.actor,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
        now = clock(conn)
        return jsonify([serialize(row, now) for row in rows])


@app.post("/api/tickets")
def create():
    authorize("customer")
    payload = data()
    subject = required(payload, "subject", 160)
    body = required(payload, "body", 5000)
    priority = required(payload, "priority", 10)
    if priority not in REPLY_TARGET:
        abort(400, "Choose urgent, medium, or low.")
    with db() as conn:
        now = clock(conn)
        ticket = conn.execute(
            """INSERT INTO tickets(customer,subject,priority,created_at,resolution_start,resolution_budget_ms)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (g.actor, subject, priority, now, now, milliseconds(CALENDAR.resolution_budget(priority, now))),
        ).fetchone()
        event(conn, ticket["id"], now, g.actor, "created", body)
        return jsonify(serialize(ticket, now)), 201


def get_ticket(conn, ticket_id, *, lock=False):
    query = "SELECT * FROM tickets WHERE id=%s"
    if lock:
        query += " FOR UPDATE"
    row = conn.execute(query, (ticket_id,)).fetchone()
    if not row or (g.role == "customer" and row["customer"] != g.actor):
        abort(404, "Ticket not found.")
    return row


@app.get("/api/tickets/<int:ticket_id>")
def detail(ticket_id):
    authorize()
    with db() as conn:
        auto_close(conn)
        row = get_ticket(conn, ticket_id)
        if g.role == "customer":
            history = conn.execute(
                """SELECT at, kind, body FROM ticket_events
                   WHERE ticket_id=%s AND kind=ANY(%s) ORDER BY id""",
                (ticket_id, list(PUBLIC_EVENTS)),
            ).fetchall()
        else:
            history = conn.execute(
                "SELECT at, actor, kind, body FROM ticket_events WHERE ticket_id=%s ORDER BY id",
                (ticket_id,),
            ).fetchall()
        return jsonify(ticket=serialize(row, clock(conn)), history=history)


def change(conn, ticket_id, **fields):
    from psycopg import sql

    assignments = sql.SQL(", ").join(
        sql.SQL("{}={}").format(sql.Identifier(name), sql.Placeholder()) for name in fields
    )
    conn.execute(
        sql.SQL("UPDATE tickets SET {} WHERE id=%s").format(assignments),
        (*fields.values(), ticket_id),
    )


def agent_action(conn, row, action, payload, now):
    ticket_id = row["id"]
    active = row["status"] in ("open", "waiting")
    if action == "claim":
        if not active or row["owner"] is not None:
            abort(409, "This ticket cannot be claimed.")
        change(conn, ticket_id, owner=g.actor)
        return "claimed", None
    if action == "note":
        return "internal_note", required(payload, "body", 5000)
    if not active or row["owner"] != g.actor:
        abort(409, "Only the assigned agent can update an active ticket.")

    if action in ("reply", "ask"):
        body = required(payload, "body", 5000)
        fields = {}
        if row["first_reply_at"] is None:
            due = CALENDAR.deadline(row["created_at"], REPLY_TARGET[row["priority"]])
            fields.update(first_reply_at=now, first_reply_late=now > due)
        if action == "ask" and row["status"] == "open":
            fields.update(status="waiting", waiting_since=now, close_due_at=CALENDAR.deadline(now, WORKWEEK))
        if fields:
            change(conn, ticket_id, **fields)
        return "agent_reply", body
    if action == "resolve":
        paused = row["paused_ms"]
        if row["waiting_since"]:
            paused += milliseconds(CALENDAR.elapsed(row["waiting_since"], now))
        due = CALENDAR.deadline(
            row["resolution_start"], timedelta(milliseconds=row["resolution_budget_ms"] + paused)
        )
        comparison = row["waiting_since"] or now
        prior_due = CALENDAR.deadline(
            row["resolution_start"], timedelta(milliseconds=row["resolution_budget_ms"] + row["paused_ms"])
        )
        late = now > due if not row["waiting_since"] else comparison > prior_due
        change(
            conn, ticket_id, status="resolved", resolved_at=now, waiting_since=None,
            close_due_at=None, paused_ms=paused, resolution_late=late,
        )
        return "resolved", None
    if action == "priority":
        priority = required(payload, "priority", 10)
        if priority not in REPLY_TARGET:
            abort(400, "Choose urgent, medium, or low.")
        change(
            conn, ticket_id, priority=priority,
            resolution_budget_ms=milliseconds(CALENDAR.resolution_budget(priority, row["resolution_start"])),
        )
        return "priority_changed", f'{row["priority"]} to {priority}'
    abort(400, "Unknown agent action.")


def customer_action(conn, row, action, payload, now):
    ticket_id = row["id"]
    if action == "reply" and row["status"] in ("open", "waiting"):
        body = required(payload, "body", 5000)
        if row["waiting_since"]:
            paused = row["paused_ms"] + milliseconds(CALENDAR.elapsed(row["waiting_since"], now))
            change(conn, ticket_id, status="open", waiting_since=None, close_due_at=None, paused_ms=paused)
        return "customer_reply", body
    if action == "reopen" and row["status"] == "resolved":
        if now > row["resolved_at"] + timedelta(days=7):
            abort(409, "The reopen window expired. Please create a new ticket.")
        body = required(payload, "body", 5000)
        change(
            conn, ticket_id, status="open", resolved_at=None, resolution_late=None,
            paused_ms=0, resolution_start=now,
            resolution_budget_ms=milliseconds(CALENDAR.resolution_budget(row["priority"], now)),
        )
        return "reopened", body
    abort(409, "This ticket does not accept that action. You can create a new ticket.")


@app.post("/api/tickets/<int:ticket_id>/<action>")
def apply_action(ticket_id, action):
    authorize()
    payload = data()
    with db() as conn:
        auto_close(conn)
        row = get_ticket(conn, ticket_id, lock=True)
        now = clock(conn)
        if row["status"] == "waiting" and row["close_due_at"] <= now:
            abort(409, "The customer response window expired.")
        if g.role == "agent":
            kind, body = agent_action(conn, row, action, payload, now)
        else:
            kind, body = customer_action(conn, row, action, payload, now)
        event(conn, ticket_id, now, g.actor, kind, body)
        if action == "ask":
            event(conn, ticket_id, now, g.actor, "customer_response_requested")
        return jsonify(serialize(snapshot(conn, ticket_id), now))


if __name__ == "__main__":
    from waitress import serve

    initialize()
    threading.Thread(target=worker, daemon=True).start()
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

