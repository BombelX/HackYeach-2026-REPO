# Haar face detector

`haarcascade_frontalface_default.xml` is the OpenCV frontal-face detector used to crop faces for PhysNet pulse estimation. `LICENSE` reproduces the model's embedded notice.

Run `python3 scripts/download_models.py` from the repository root to download the model. The script verifies SHA-256 and restores the separate license from the verified XML, including when the model is already cached.
