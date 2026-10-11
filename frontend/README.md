# VarioLog frontend

The Bank24 demonstration interface, built with React, TypeScript, Vite,
React Router and TanStack Query. Accounts and money are fictional. The interface
uses English, PLN amounts and Polish NRB account numbers.

## Setup

Use Node.js 22.12+ or 24 LTS. From the repository root:

```bash
cd frontend
npm ci
```

The frontend needs the banking API. Follow the [backend setup](../backend/README.md)
to download models and install Python dependencies before starting the services.

## Development

Start the API from the repository root in one terminal:

```bash
.venv/bin/python backend/bank24_server.py --demo
```

On Windows, replace `.venv/bin/python` with
`.venv\Scripts\python.exe`.

In another terminal, from `frontend/`:

```bash
npm run dev
```

Open **http://localhost:5173/**. Vite forwards API requests to
`http://127.0.0.1:8081`. Override the proxy target with `BANK24_API_URL` when needed.
The application shows API errors explicitly; it does not fall back to mock data.

| Demo field | Value |
| --- | --- |
| Username | `anna.demo` |
| Password | `bank24` |
| Sign-in and transfer code | `1234` |

The backend must run with `--demo` to enable the demo account and codes.
No SMS is sent. Code `4321` triggers a synthetic alarm scenario.

## Build and serve

From `frontend/`:

```bash
npm run build
```

This type-checks the application and writes `frontend/dist/`. From the repository
root, serve that build through the banking backend:

```bash
.venv/bin/python backend/bank24_server.py --demo --origin http://127.0.0.1:8081
```

Open **http://127.0.0.1:8081/**. The backend supports direct client-route links.
For a public HTTPS deployment, configure the matching `--origin` and
`--secure-cookie`; keep the camera worker private behind the bank gateway.

For hosting under `/variolog/`, build with
`npm run build -- --base /variolog/`. The reverse proxy must strip that prefix
before forwarding requests to the bank. Set the backend origin to the public
scheme and host without the path.

## Camera and analysis

Start the separate [camera worker](../backend/README.md#camera-worker) for face,
pose and pulse analysis. The bank starts camera capture after sign-in, subject
to application and browser permissions. It sends JPEG frames through the
bank's authenticated gateway and renders annotated images and measurements.
It does not request microphone access. Missing camera data does not block basic
banking, and missing measurements appear as unavailable rather than zero.

Camera state survives route changes. Visible controls stop capture; sign-out
releases tracks. The camera-profile panel supports explicit calm recordings,
sample approval and profile deletion. Model scores are experimental comparison
signals, not validated fraud probabilities or proof of account ownership.

## Application structure and behavior

| Directory | Purpose |
| --- | --- |
| `src/app/` | Routing, shared application state and path helpers |
| `src/design/` | Reusable components and styles |
| `src/layouts/` | Public and authenticated layouts |
| `src/features/` | Landing, authentication, accounts, transfers, camera, telemetry, help and feedback |
| `src/services/` | API client, types and validation |
| `src/tests/`, `e2e/` | Unit tests and browser tests |
| `public/brand/` | Logo, fonts and landscape assets |

The main flow is landing → sign-in → code → account → transfer details → review
→ transaction code → result. History and contextual help are separate pages.
Transfer versions and challenges come from the server. Editing invalidates old
confirmation state; uncertain submission recovers the same operation instead of
creating a second debit. Unsubmitted drafts remain in memory.

Passwords, verification codes and session tokens are excluded from telemetry
and localStorage. Optional behavioral telemetry sends bounded batches of timing,
length, correction, focus and pointer metadata. The backend enforces consent,
CSRF, ownership and allowed event fields. Operator and study onboarding APIs are
documented separately; this banking UI does not implement their operator screens.

## Tests

From `frontend/`:

```bash
npm test
npm run build
npx playwright install chromium
```

For browser tests on Linux/macOS:

```bash
BANK24_PYTHON="$(pwd)/../.venv/bin/python" npm run test:e2e
```

On Windows PowerShell:

```powershell
$env:BANK24_PYTHON = (Resolve-Path ../.venv/Scripts/python.exe).Path
npm run test:e2e
```

Install the backend's camera dependencies before running browser tests. Playwright
starts the camera worker on 8080, a separate banking API on 8082 and Vite on 5180.
Its database is `data/e2e-bank24.sqlite`, separate from the running demo. Keep
these ports free. A controlled canvas stream tests camera transport; axe checks
selected accessibility rules. These checks do not validate model accuracy or
replace manual screen-reader testing.

See the [backend guide](../backend/README.md), [API contract](../backend/BANK24_API.md)
and [project README](../README.md) for related setup and behavior.
