# VarioLog · HackYeah 2026

A banking demonstration with behavioral analysis and an optional camera.
Built with React, TypeScript, Python, SQLite and an experimental signal-fusion model.
Accounts, transfers and money in the application are fictional.
The interface and documentation are in English; amounts remain in PLN.

![Bank24 demo dashboard](docs/dashboard.png)

## Repository contents

| Directory | Contents |
| --- | --- |
| [`frontend/`](frontend/README.md) | Banking app: setup, development, builds and browser tests |
| [`backend/`](backend/README.md) | Banking API and camera worker: setup, configuration and tests |
| `data-collector/` | Separate research session collection application |
| `research/` | Model training, experiments and research tools; see [research layout](research/README.md) |
| `models/` | Model assets, architecture code and licenses; binary formats use Git LFS |
| `tests/` | Backend integration tests |

## Requirements

- Python 3.11–3.13 (previous local verification used 3.13).
- Node.js 22.12+ or 24 LTS, with npm available on PATH.
- Git; Git LFS is needed for additional training checkpoints. Camera assets use the download script.
- A camera and GPU are optional. Basic banking works without them.

## 1. Download model files

First run the standalone downloader from the repository root.

Linux / macOS:

```bash
python3 scripts/download_models.py
```

Windows:

```powershell
python scripts/download_models.py
```

The script needs only the Python standard library. It does not require a virtual
environment, extra packages or Git LFS. It prepares these folders:

| Folder | Files |
| --- | --- |
| `models/mediapipe/` | Face and pose model bundles and license |
| `models/physnet/` | Pulse checkpoint, `physnet.py` architecture and license |
| `models/haarcascade/` | OpenCV face detector and license |

Model and architecture downloads are verified with SHA-256. Valid local files
are reused; Git LFS pointers are replaced with real assets. Downloads require
internet access. Training experiment checkpoints are separate and use Git LFS.

## 2. Install dependencies and start the bank

Run these commands from the repository root.

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-server.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe backend/bank24_server.py --demo --origin http://127.0.0.1:8081
```

Linux / macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-server.txt
(cd frontend && npm ci && npm run build)
.venv/bin/python backend/bank24_server.py --demo --origin http://127.0.0.1:8081
```

Open **http://127.0.0.1:8081/**. The server serves the built frontend.

| Field | Demo value |
| --- | --- |
| Username | `anna.demo` |
| Password | `bank24` |
| Sign-in and transfer code | `1234` |

Code `4321` starts a synthetic alarm scenario with delayed sign-out.
Bank state persists in `backend/data/bank24.sqlite`.

### Frontend development

Start the API with its default frontend origin:

```powershell
.\.venv\Scripts\python.exe backend/bank24_server.py --demo
```

On Linux/macOS use `.venv/bin/python` instead. In another terminal run
`cd frontend` and `npm run dev`, then open **http://localhost:5173/**.
Vite forwards `/api` requests to port 8081.

## 3. Start the camera analysis service

The camera analysis service runs separately from the banking API. Download the
models in step 1 and install `backend/requirements-server.txt` in step 2 first.
Leave the bank server running and open another terminal at the repository root
(a third terminal if the Vite development server is also running).
Start the camera worker on port 8080:

Linux / macOS:

```bash
.venv/bin/python backend/webrtc_server.py --host 127.0.0.1 --port 8080 --device cpu
```

Windows:

```powershell
.\.venv\Scripts\python.exe backend/webrtc_server.py --host 127.0.0.1 --port 8080 --device cpu
```

Keep both the banking API and camera service running. Open
**http://127.0.0.1:8081/** (or **http://localhost:5173/** during frontend
development), sign in and allow camera access in the browser. These commands
enable face landmarks, pose analysis and experimental pulse estimation on CPU.
The worker checks required assets at startup and downloads missing files.

Check **http://127.0.0.1:8080/health** to confirm the service is running. To test
the camera independently of the bank, open **http://127.0.0.1:8080/** and select
**Start camera**. Stop the service with `Ctrl+C` in its terminal.

`--preview-only` disables PhysNet pulse estimation while retaining MediaPipe
analysis. Add `--no-analysis` as well to test video transport alone.
The PhysNet architecture is in `models/physnet/physnet.py`.
See the [backend guide](backend/README.md#camera-worker) for more options.

The camera starts after sign-in, subject to application consent and browser
permission. Missing camera data does not block basic banking. Owner profiles
require three explicitly approved samples from separate sign-ins. The fusion
model is an experimental research signal, not a validated fraud probability.

After saving the third approved sample, sign out and sign in again so the new
profile can assess a separate recording. Keep the camera on while it collects
fresh data. The Camera profile panel shows the live experimental mismatch score
or explains why assessment is unavailable. Scoring also requires the actual
fusion checkpoint at `research/training/artifacts/fusion/fusion_model.pt`; a
Git LFS pointer alone is not a usable model.

Enable the optional typing/mouse metadata permission at sign-in to provide the
other fusion inputs: mouse movement/clicks, form interaction, browser/device
information, connection RTT and request latency. Keyboard windows use the frozen
encoder at `models/keystroke/long-run/keystroke_long_epoch_59.pt`; download it and
the fusion checkpoint with:

```bash
git lfs pull --include="models/keystroke/long-run/keystroke_long_epoch_59.pt,research/training/artifacts/fusion/fusion_model.pt"
```

Non-password key identifiers and timing features are processed transiently into
128-dimensional embeddings; only embeddings are saved, not those identifiers.
Passwords and verification codes are excluded. At least 16 completed keystrokes
in one supported field are needed for a keyboard window. Missing inputs stay
masked. Existing enrollment samples retain their camera reference; new approved
samples made with telemetry enabled add keyboard, mouse and device references.
Withdrawing telemetry disables these live inputs and deletes session metadata.
Scores remain experimental and are not calibrated fraud/manipulation probabilities.

## Session collector — separate application

```powershell
.\.venv\Scripts\python.exe -m pip install -r data-collector/backend/requirements.txt
cd data-collector/front
npm ci
npm run build
cd ../backend
$env:ADMIN_PASSWORD = "your-facilitator-password"
..\..\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. For frontend development run
`cd data-collector/front` and `npm run dev` in another terminal, then open
**http://localhost:5174/**. Collector data is stored in `data-collector/data/`
and excluded from Git. On Linux/macOS use the virtual environment's `bin/python`
and set `ADMIN_PASSWORD` with your shell's environment syntax.

## Tests

```powershell
.\.venv\Scripts\python.exe scripts/check_backend.py
cd frontend
npm run build
npm test
npx playwright install chromium
$env:BANK24_PYTHON = (Resolve-Path ../.venv/Scripts/python.exe).Path
npm run test:e2e
cd ../data-collector/front
npm run build
```

On Linux/macOS set `BANK24_PYTHON` to the absolute path of `.venv/bin/python`.
With Chrome installed, set `PLAYWRIGHT_CHANNEL=chrome` to avoid downloading
Chromium. E2E tests start their own servers on ports 8080, 8082 and 5180.
GitHub Actions checks the backend, both frontend builds and E2E tests.

## Publishing to GitHub

From the repository root, configure Git LFS before committing binary assets:

```powershell
git lfs install
git add .
git commit -m "Prepare Bank24 application and research tools"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin HEAD
```

Skip `git remote add` if `origin` is already configured. Training weights and
checkpoints exceed 2 GB and use Git LFS. Use `git lfs pull` if you need those
research artifacts. Raw data, recordings, participant profiles, SQLite databases,
secrets, virtual environments and dependencies are ignored by Git.
The source project's checkpoint history has been preserved.

## Documentation and provenance

- [Bank API contract](backend/BANK24_API.md)
- [Frontend guide](frontend/README.md)
- [Backend guide](backend/README.md)
- [Fusion training](research/training/fusion/README.md)
- [Research layout and limitations](research/README.md)

Project-owned code has not yet been assigned a license. Third-party license
texts are retained in `models/physnet/LICENSE`, `models/mediapipe/LICENSE`,
`models/haarcascade/LICENSE` and `models/sapimouse/LICENSE`.
Obtain training data separately under the terms of its sources.
See [the license review](models/licenses/README.md) for unresolved use restrictions;
PhysNet license compliance has not been established.
