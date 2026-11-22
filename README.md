# Frontdesk

Frontdesk is a support queue for Arvo Systems. Agents claim tickets, send public replies, request customer information, take private notes, and review the audit history. Customers can open their own tickets and see their public conversations.

## Run locally

Requirements are Python 3.11 or later, and PostgreSQL 16 or Docker Compose.

1. Run `docker compose up -d db`. With an existing PostgreSQL server, create a database and use its connection string below.
2. Run `python -m pip install -r requirements.txt`.
3. In PowerShell, set the database URL and local access keys.

```powershell
$env:DATABASE_URL = 'postgresql://frontdesk:local-frontdesk@127.0.0.1:5432/frontdesk'
$env:FRONTDESK_ACCOUNTS = '{"meera":{"role":"agent","token":"local-meera"},"ravi":{"role":"agent","token":"local-ravi"},"customer-one":{"role":"customer","token":"local-customer-one"},"customer-two":{"role":"customer","token":"local-customer-two"}}'
python app.py
```

4. Open http://localhost:8000. Use `local-customer-one` to create a ticket and `local-meera` to claim it. Open a separate browser window for another identity. Use `GET /health` to check the database connection and schema.

## SLA decisions

- Arvo's calendar is Asia/Kolkata, 09:30–18:30 Monday through Friday. Set `FRONTDESK_HOLIDAYS` to comma-separated ISO dates for company holidays in the deployment period.
- Urgent replies are due in two business hours. Urgent resolution is due by the end of the first working day on which the ticket is received. A ticket received outside business hours starts at the next opening. A customer wait can extend this deadline.
- Medium replies and resolutions are due in 4.5 and 27 business hours. Low replies and resolutions are due in nine and 45 business hours.
- The first public agent message counts as the first reply. A request for customer information pauses the resolution clock and starts a 45-business-hour inactivity window. Customer replies resume the clock. A worker closes expired waits, and request-time checks keep expired tickets from accepting late replies.
- Open targets are recalculated from their existing clock starts when priority changes. Accrued business time and pauses carry over. A completed reply's measured outcome stays fixed.
- Customers can reopen a resolved ticket within seven calendar days. Reopening starts a new resolution clock and keeps the original first-response outcome. An inactivity-closed ticket requires a new request.
- Ticket changes and activity writes are transactional. A competing claim receives HTTP 409. The customer detail route selects public event types only. The audit table has database triggers rejecting updates, deletions, and truncation. Database administrators retain control over the underlying schema.

## Verify

Run `python -m unittest test_calendar -v` for calendar tests. With the service running in a throwaway database and the local demo keys loaded, run `python smoke.py` to exercise two competing agents, note visibility, customer isolation, waiting, resolution, and reopening.

Set `FRONTDESK_TEST_DATABASE_URL` to the disposable database URL to also verify that PostgreSQL rejects audit updates, deletes, and truncation.
