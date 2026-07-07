# GCCC Contest Dashboard

Real-time contest war-room display + persistent historical database for the Gulf Coast Contest Club.

## Architecture

```
N1MM seats  →  UDP broadcast → [ Pi Collector ]  (LAN, this repo)
                                   ├─ SQLite DB (USB stick)
                                   ├─ FastAPI local API + WebSocket
                                   └─ async mirror → Supabase (cloud)
                                            │
                                [ Kiosk laptop ]           [ Render: remote/review ]
                                fullscreen browser          reads Supabase realtime
                                HDMI → big screen           gated by Supabase Auth
```

## Quick start

See `deploy/README-pi-setup.md` for the full Pi installation guide.

```bash
cd collector
pip install -r requirements.txt
python main.py              # starts UDP listener + web server on :8080
```

Open `http://localhost:8080` for the dashboard, `http://localhost:8080/admin.html` for contest admin.

## Directory layout

```
contest-dashboard/
  collector/
    config.py      §0 verify-first: N1MM field names + all tunable constants
    ingest.py      UDP packet parser (uses config field names throughout)
    db.py          SQLite schema + CRUD (WAL mode)
    mirror.py      Async Supabase mirror with retry queue
    api.py         FastAPI routes + WebSocket broadcaster
    main.py        Entrypoint: asyncio UDP + uvicorn in one loop
    requirements.txt
  frontend/
    index.html     War-room + leaderboard dashboard (auto-rotates)
    admin.html     Contest lifecycle + station setup
    style.css      GCCC theme (matches main site tokens)
    dashboard.js   WebSocket client + data-source abstraction
    admin.js       Admin API calls
  schema/
    supabase.sql   Postgres schema for Supabase (with RLS + realtime)
  deploy/
    gccc-collector.service   systemd service for the Pi
    README-pi-setup.md       Full Pi + kiosk + N1MM setup guide
```

## Phase status

- [x] **Phase 1 (MVP):** Collector (ingest + dedupe + edit/delete) + in-room war-room + leaderboard + admin
- [ ] Phase 2: Historical review + Supabase mirror + Render deployment
- [ ] Phase 3: Gated remote view (Supabase Auth)
- [ ] Phase 4: Feed stats onto the public GCCC website

## §0 Verify-first checklist (before first live use)

- [ ] Capture a real N1MM ContactInfo packet; confirm XML field names match `collector/config.py → N1MM_FIELDS`
- [ ] Verify `isoriginal` / `netbiosname` behavior across multi-seat setup (single vs subnet-broadcast dedupe)
- [ ] Confirm `band` field format (numeric MHz string vs label string)
- [ ] Test `ContactReplace` and `ContactDelete` packets are received and handled correctly
