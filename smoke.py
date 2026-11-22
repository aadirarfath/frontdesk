"""Run against a disposable local service configured with the README keys."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.getenv("FRONTDESK_TEST_URL", "http://127.0.0.1:8000") + "/api"
CUSTOMER = "local-customer-one"


def call(key, path, payload=None):
    request = Request(BASE + path, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if payload is not None:
        request.data = json.dumps(payload).encode()
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, (json.load(error) if error.headers.get_content_type() == "application/json" else error.read().decode(errors="replace"))


def verify_audit(database_url):
    import psycopg
    from psycopg import sql

    schema = sql.Identifier(os.getenv("FRONTDESK_DB_SCHEMA", "public"))
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(schema))
        for command in (
            "UPDATE ticket_events SET body=NULL",
            "DELETE FROM ticket_events",
            "TRUNCATE ticket_events",
        ):
            try:
                with connection.transaction():
                    connection.execute(command)
            except psycopg.errors.RaiseException as error:
                assert str(error).startswith("Ticket history is append-only"), error
            else:
                raise AssertionError("Audit table accepted " + command)
        version = connection.execute("SHOW server_version").fetchone()[0]
    print("Append-only audit verified on PostgreSQL " + version)


def main():
    status, ticket = call(CUSTOMER, "/tickets", {
        "subject": "Smoke test", "priority": "medium", "body": "Please investigate.",
    })
    assert status == 201, ticket
    path = f'/tickets/{ticket["id"]}'
    agents = ["local-meera", "local-ravi"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda token: call(token, path + "/claim", {}), agents))
    assert sorted(status for status, _ in claims) == [200, 409], claims
    winner = agents[next(i for i, (status, _) in enumerate(claims) if status == 200)]
    loser = next(agent for agent in agents if agent != winner)
    assert call(loser, path + "/reply", {"body": "Conflicting reply"})[0] == 409
    assert call(winner, path + "/note", {"body": "Agent-only entry"})[0] == 200
    assert call(winner, path + "/ask", {"body": "Could you share a screenshot?"})[1]["status"] == "waiting"
    status, view = call(CUSTOMER, path)
    assert status == 200 and "Agent-only entry" not in json.dumps(view)
    assert "Agent-only entry" in json.dumps(call(winner, path)[1])
    assert "Agent-only entry" not in json.dumps(call(CUSTOMER, "/tickets")[1])
    assert call("local-customer-two", path)[0] == 404
    assert call(CUSTOMER, path + "/reply", {"body": "Here are the details."})[1]["status"] == "open"
    assert call(winner, path + "/resolve", {})[1]["status"] == "resolved"
    assert call(CUSTOMER, path + "/reopen", {"body": "Still seeing the problem."})[1]["status"] == "open"
    print("Claim race, note isolation, customer access, and ticket lifecycle passed.")
    if database_url := os.getenv("FRONTDESK_TEST_DATABASE_URL"):
        verify_audit(database_url)


if __name__ == "__main__":
    main()
