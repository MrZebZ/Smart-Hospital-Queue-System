# API reference

Base URL: `http://127.0.0.1:5000`. Requests and responses are JSON. Errors look like `{"error": "message"}` with an HTTP status of 400, 401, 403, 404, 409 or 429.

## Public endpoints

### `GET /healthz`
`{"status": "ok"}`

### `GET /api/hospitals`
Query: `lat`, `lng` (your position), `mode` = `regular` (default) or `emergency` (ER hospitals only, nearest first).
```json
[{"id": 2, "name": "Al-Shifa Medical Complex", "lat": 34.005, "lng": 72.95, "has_er": true,
  "km": 1.9, "travel_min": 4, "queue": 4, "wait_min": 20, "total_min": 24, "level": "low"}]
```
`level` is `low` (queue 8 or fewer), `medium` (18 or fewer) or `high`.

### `POST /api/reserve`
Body `{"hospital_id": 2, "name": "Ali", "phone": "03001234567"}` returns `{"id": 17, "number": 5}`.
Errors: 400 invalid name/phone (10+ digits), 404 unknown hospital, 409 this phone already has an active reservation.

### `GET /api/token/<id>`
```json
{"id": 17, "number": 5, "status": "waiting", "hospital": "Al-Shifa Medical Complex",
 "position": 3, "eta_min": 10, "expires_in_min": 27}
```
`status` is `waiting`, `served`, `cancelled` or `expired`. `position` and `eta_min` are `null` unless waiting.

### `POST /api/token/<id>/cancel`
Returns `{"ok": true}`.

### `POST /api/emergency`
Body `{"hospital_id": 1, "name": "Bilal", "phone": "0300...", "eta_min": 8}` returns `{"ok": true, "hospital": "..."}`. 404 if the hospital has no emergency department.

## Staff endpoints (session cookie required)

### `POST /api/login`
Body `{"username": "hospital1", "password": "demo123"}` returns `{"ok": true}` and sets a session cookie. After 5 failed attempts in a minute, further attempts get 429.

### `POST /api/logout` · `GET /api/me`
`/api/me` returns `{"hospital_id": 1, "hospital": "...", "user": "hospital1"}`.

### `GET /api/dashboard/<hospital_id>`
Returns 403 for any hospital other than your own.
```json
{"name": "City General Hospital", "walk_in": 12, "avg_min": 6,
 "tokens": [{"id": 17, "number": 5, "name": "Ali", "phone": "0300...", "created": 1761700000.0}],
 "alerts": [{"id": 3, "name": "Bilal", "phone": "0300...", "eta_min": 8, "created": 1761700000.0}]}
```

| Method | Path | Body | Result |
|---|---|---|---|
| POST | `/api/dashboard/<id>/next` | none | Marks the lowest waiting number as served (or lowers the walk-in count if nobody is reserved) |
| POST | `/api/dashboard/<id>/service-time` | `{"avg_min": 7}` (1 to 60) | `{"ok": true, "avg_min": 7}` |
| GET | `/api/dashboard/<id>/history` | none | List of recent waiting-room counts (about 10 minutes) |
| POST | `/api/alerts/<alert_id>/ack` | none | Acknowledges an emergency alert of your hospital |

### `POST /api/dashboard/<id>/camera`
Body `{"count": 14}` returns `{"ok": true, "walk_in": 14}`. Allowed for staff of that hospital **or** any caller that sends the header `X-Camera-Key: <CAMERA_KEY>`.
```bash
curl -X POST localhost:5000/api/dashboard/1/camera -H "Content-Type: application/json" \
     -H "X-Camera-Key: camera-demo-key" -d '{"count": 14}'
```
