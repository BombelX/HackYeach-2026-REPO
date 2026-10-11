# Model assets

This directory stores the camera-analysis assets and the keystroke checkpoints
that were located at the workspace root.

- `haarcascade/` — OpenCV face detector and its license for PhysNet face crops.
- `physnet/` — UBFC-rPPG PhysNet checkpoint for pulse estimation.
- `mediapipe/` — face and pose landmarker models, license text and documentation.
- `sapimouse/` — third-party mouse-dynamics code, pretrained models, results and license.
- `keystroke/baseline/` — epochs 0–19 from the baseline run.
- `keystroke/constant-lr/` — epochs 0–19 from the constant-learning-rate run.
- `keystroke/long-run/` — epochs 0–59 from the long training run.

The checkpoint files are not byte-identical, including files with the same epoch
number in different runs, so all are retained. `research/training/` contains the other trained artifacts.

Run `python3 scripts/download_models.py` from the repository root to download
all three camera models into `mediapipe/` and `physnet/`. The camera worker also
downloads missing required models at startup. Downloads are SHA-256 verified.
The PhysNet architecture and upstream license are retained in
`models/physnet/physnet.py` and `models/physnet/LICENSE`.

All binary model formats are managed by Git LFS via the repository-level
`.gitattributes` file.

License files, provenance and unresolved compliance findings are in [licenses/README.md](licenses/README.md).

The download script is self-contained and uses only the Python standard library.

The downloader also restores missing PhysNet and MediaPipe license files from upstream before preparing models. MediaPipe bundle licensing caveats remain documented in the license review.

The downloader also restores the PhysNet Python architecture and Haar face-detection cascade, with SHA-256 verification. The cascade retains its embedded license. Install runtime Python packages separately using `backend/requirements-server.txt`.
