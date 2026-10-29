# Architecture

![Architecture](images/architecture.png)

## Components
- **Patient web app** (`templates/patient.html`): vanilla JavaScript and Leaflet. Polls `/api/hospitals` every 4 s and `/api/token/<id>` every 3 s.
- **Staff dashboard** (`templates/dashboard.html`): polls `/api/dashboard/<id>` every 2 s; requires a login session.
- **Flask app** (`app.py`): REST API, authentication, queue and ranking logic, reservation expiry.
- **SQLite**: five tables (see below).
- **Camera input**: either the built-in simulator thread (`SIMULATE=1`) or an external script posting counts with an API key.

## Data model
![ER diagram](images/er-diagram.png)

`tokens.status` is one of `waiting`, `served`, `cancelled`, `expired`. Expiry is applied lazily: every request that reads queues first marks waiting tokens older than `TTL_MIN` (30) as expired.

## Queue logic
```
queue      = hospitals.walk_in + count(tokens WHERE status = 'waiting')
wait_min   = queue * hospitals.avg_min
travel_min = haversine_km / 30 km/h * 60
regular    : sort by travel_min + wait_min
emergency  : keep has_er = 1, sort by distance
position   = 1 + count(waiting tokens at the same hospital with a lower number)
```

## Design decisions
- **Emergency patients are not queued.** Emergency departments triage by severity, so the app only routes the patient and notifies the hospital.
- **Camera sends a number only.** No images are transmitted or stored, which avoids most privacy concerns.
- **Polling instead of WebSockets.** Simple, works behind any proxy, and is enough for a few-second refresh. Server-sent events are the natural next step.
- **SQLite.** Zero setup for a course project. Moving to PostgreSQL only requires replacing the connection helper and SQL dialect details.
- **Per-hospital authorization** is enforced in the `staff_only` decorator, so a logged-in user cannot read or change another hospital.

## Scaling notes
The login rate limiter and the simulator run in-process, so run a single worker as shipped. For several workers, move rate limiting to a shared store (such as Redis), disable the simulator, and use a networked database.
