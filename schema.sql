CREATE TABLE IF NOT EXISTS tickets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer text NOT NULL,
    subject text NOT NULL,
    priority text NOT NULL CHECK (priority IN ('urgent', 'medium', 'low')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'waiting', 'resolved', 'closed')),
    owner text,
    created_at timestamptz NOT NULL,
    first_reply_at timestamptz,
    resolved_at timestamptz,
    waiting_since timestamptz,
    close_due_at timestamptz,
    closed_at timestamptz,
    paused_ms bigint NOT NULL DEFAULT 0,
    resolution_start timestamptz NOT NULL,
    resolution_budget_ms bigint NOT NULL,
    first_reply_late boolean,
    resolution_late boolean
);

CREATE TABLE IF NOT EXISTS ticket_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id bigint NOT NULL REFERENCES tickets(id),
    at timestamptz NOT NULL,
    actor text NOT NULL,
    kind text NOT NULL,
    body text
);

CREATE INDEX IF NOT EXISTS ticket_events_timeline ON ticket_events(ticket_id, id);
CREATE INDEX IF NOT EXISTS waiting_tickets_due ON tickets(close_due_at) WHERE status = 'waiting';

CREATE OR REPLACE FUNCTION deny_audit_changes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Ticket history is append-only';
END;
$$;

CREATE OR REPLACE TRIGGER protect_ticket_events
BEFORE UPDATE OR DELETE OR TRUNCATE ON ticket_events
FOR EACH STATEMENT EXECUTE FUNCTION deny_audit_changes();
