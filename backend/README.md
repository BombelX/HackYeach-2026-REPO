# VarioLog backend

Python services for the Bank24 banking demonstration: an `aiohttp` banking API
with SQLite persistence and a separate `aiortc` camera-analysis worker. Accounts,
transfers and money are fictional.

## Services and source files

| File | Purpose |
| --- | --- |
| `bank24_server.py` | Authentication, account/history, transfers, study/operator APIs, camera gateway and built frontend hosting |
| `webrtc_server.py` | Camera frame/WebRTC transport, annotated images and analysis snapshots |
| `camera_estimator.py` | PhysNet pulse estimation and landmark utilities |
| `bank24_camera_risk.py` | Camera profiles and experimental fusion-model scoring |
| `bank24_risk.py` | Behavioral metadata features and baseline comparisons |
| `static/webrtc.html` | Standalone browser camera client |

Use Python 3.11–3.13. Camera dependencies are larger than the basic banking
requirements. A GPU is optional; the examples use CPU inference.

## 1. Download models

From the repository root, download camera assets before starting analysis:

```bash
python3 scripts/download_models.py
```

On Windows, use `python` instead of `python3`. The downloader uses only the Python
standard library and requires internet access. It prepares MediaPipe bundles,
PhysNet weights and architecture, the Haar cascade and license files under
`models/`. Binary/architecture assets are SHA-256 verified and valid files reused.
The worker also prepares missing required assets at startup.

Fusion and other research checkpoints are separate Git LFS assets. Download them
with `git lfs pull` when needed for model inference. Their code and canonical
artifacts live under `research/training/`; the camera downloader does not fetch
these research checkpoints.

## 2. Install Python dependencies

Linux/macOS, from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-server.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-server.txt
```

For basic banking without camera analysis, install `backend/requirements-bank.txt`
instead. The full `requirements-server.txt` includes the banking dependency and
camera/model packages. The separate research collector has its own dependencies
under `data-collector/backend/`.

## 3. Run the bank API

Linux/macOS, from the repository root:

```bash
.venv/bin/python backend/bank24_server.py --demo
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe backend/bank24_server.py --demo
```

The API listens on **http://127.0.0.1:8081/**. Its default allowed browser origin
is `http://localhost:5173`, for the [Vite development server](../frontend/README.md).
Demo credentials are `anna.demo` / `bank24`, with sign-in and transfer code `1234`.
No SMS is sent. Demo code `4321` enables a synthetic alarm scenario; it is not an
actual model result. Outside demo mode, an SMS provider must be configured through
the application integration before verification works.

To serve the built frontend instead, first run `npm ci` and `npm run build` inside
`frontend/`, then start the API with the browser's origin:

```bash
.venv/bin/python backend/bank24_server.py --demo --origin http://127.0.0.1:8081
```

Open **http://127.0.0.1:8081/**. The API serves `frontend/dist/`.

## Camera worker

Leave the bank running and start a second terminal at the repository root:

```bash
.venv/bin/python backend/webrtc_server.py --host 127.0.0.1 --device cpu
```

On Windows use `.venv\Scripts\python.exe`. The worker listens on port 8080.
Sign in to the bank and grant browser camera permission. Browser frames go through
the authenticated bank gateway; the worker processes the browser's camera, not a
camera attached to the server.

| Worker option | Behavior |
| --- | --- |
| `--device cpu` | Run inference on CPU |
| `--device cuda` | Use a supported CUDA GPU |
| `--preview-only` | Disable PhysNet pulse estimation while retaining landmark analysis |
| `--preview-only --no-analysis` | Test video transport without model analysis |
| `--port 8080` | Worker port; match the bank's `--camera-url` if changed |
| `--max-sessions 4` | Maximum concurrent camera sessions |

The standalone WebRTC client is at **http://127.0.0.1:8080/**. Remote browser
camera access requires HTTPS. The bank's JPEG gateway needs no STUN/TURN; separate
WebRTC clients may need those services across networks.

## Configuration and storage

| Bank option/environment | Purpose |
| --- | --- |
| `--host`, `--port` | Bind address and port; defaults `127.0.0.1:8081` |
| `--database` | SQLite location; default `backend/data/bank24.sqlite` |
| `--origin` | Allowed browser origins, comma-separated |
| `--camera-url` | Private worker address; default `http://127.0.0.1:8080` |
| `--secure-cookie` | Enable Secure cookies behind HTTPS |
| `BANK24_ADMIN_TOKEN` | Enable operator APIs with a secret bearer token |
| `--fusion-repo` / `BANK24_FUSION_REPO` | Research code root; defaults to `research/` |

Run either server with `--help` for all supported options. Operator tokens need
at least 32 characters and are sent as `Authorization: Bearer ...`. Keep the
worker private and avoid committing credentials or participant data.

SQLite persists accounts, balances, transfers, consent, study metadata and camera
profiles across restarts. Local databases and sidecars are ignored by Git.
Authentication uses HttpOnly cookies; the server enforces CSRF, origin checks and
resource ownership. Transfer edits invalidate earlier codes and decisions.
Submission is atomic and idempotent, so retries do not debit twice.

Camera enrollment requires explicit calm samples from separately verified sign-ins.
Three approved samples create the initial profile; operator approval rules apply
to further updates and non-demo enrollment. Scoring never enrolls a sample.
Missing or insufficient signals produce unavailable results. Fusion scores and
behavioral indicators are experimental, unvalidated comparisons rather than fraud
probabilities or proof of coercion/identity.

## Tests

From the repository root:

```bash
.venv/bin/python scripts/check_backend.py
```

On Windows use `.venv\Scripts\python.exe`. Integration tests need permission
to open local sockets. Model-inference tests also need actual Git LFS checkpoints,
not pointer files. See the [frontend guide](../frontend/README.md#tests) for browser
and camera lifecycle checks.

The [API contract](BANK24_API.md) documents endpoints, fields and state transitions.
The [product notes](PRODUCT.md) describe intended behavior. Retain model license
files with distributions; see the [license review](../models/licenses/README.md)
for unresolved PhysNet use restrictions.

With the optional usage-metadata permission, the live model also receives mouse
windows, form interaction, browser/device details, measured connection RTT and
request latency. Keyboard embeddings require the exact frozen encoder
`models/keystroke/long-run/keystroke_long_epoch_59.pt` (Git LFS). Key identifiers
and eight timing/category features are used transiently; only 128D embeddings
are stored. Passwords and verification codes are excluded. Both enrollment and
live scoring use the same adapters in `bank24_inputs.py`, aligned to the camera's
start timestamp. `/api/bank/risk-check` reports `available_signals`. Missing
network measurements bypass the network classifier; missing context is masked.

To verify the fusion checkpoint and independently recheck its saved cross-validation
metrics, run `.venv/bin/python scripts/verify_fusion_model.py` from the repository
root (Windows: `.venv\Scripts\python.exe`). Add `--database backend/data/bank24.sqlite`
for an optional read-only sensitivity check of the latest trusted profile, and
`--output /tmp/model-verification.json` to save aggregate results. A successful
exit verifies execution/artifact consistency; it does **not** establish detection
accuracy. Recomputing accuracy on new recordings requires the processed dataset.
