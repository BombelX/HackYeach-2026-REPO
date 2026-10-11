#!/usr/bin/env python3
"""Download the three camera models; validate SHA-256 before replacing files."""
import hashlib
from pathlib import Path
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    'face': ('models/mediapipe/face_landmarker.task',
             'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
             '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'),
    'pose': ('models/mediapipe/pose_landmarker_lite.task',
             'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
             '59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a'),
    'architecture': ('models/physnet/physnet.py',
                     'https://raw.githubusercontent.com/ubicomplab/rPPG-Toolbox/main/neural_methods/model/PhysNet.py',
                     '48a5a3132d9cb737f0dd782d354d27bf36c723a3ce018b4a1ec0cc3571905d9a'),
    'cascade': ('models/haarcascade/haarcascade_frontalface_default.xml',
                'https://raw.githubusercontent.com/opencv/opencv/4.x/data/haarcascades/haarcascade_frontalface_default.xml',
                '0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0'),
    'pulse': ('models/physnet/UBFC-rPPG_PhysNet_DiffNormalized.pth',
              'https://raw.githubusercontent.com/ubicomplab/rPPG-Toolbox/main/final_model_release/UBFC-rPPG_PhysNet_DiffNormalized.pth',
              '6c00db978d9db3566b8953a97cb7cfcd6deb9522b0cbc937c921bb1859a1cdd0'),
}


LICENSES = {
    'pulse': ('models/physnet/LICENSE',
              'https://raw.githubusercontent.com/ubicomplab/rPPG-Toolbox/main/LICENSE',
              'Responsible Artificial Intelligence Source Code License'),
    'face': ('models/mediapipe/LICENSE',
             'https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/LICENSE',
             'Apache License'),
}


def ensure_license(name):
    # Face and pose share the MediaPipe license file.
    relative, url, marker = LICENSES['face' if name == 'pose' else name]
    path = ROOT / relative
    if path.is_file():
        text = path.read_text()
        if marker in text and 'END OF TERMS AND CONDITIONS' in text:
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    print(f'Downloading license to {path}', flush=True)
    try:
        with urlopen(url, timeout=60) as response:
            data = response.read()
        text = data.decode('utf-8')
        if marker not in text or 'END OF TERMS AND CONDITIONS' not in text:
            raise RuntimeError('Response is not the expected complete license text')
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        temporary.replace(path)
    except Exception as exc:
        raise RuntimeError(f'Cannot download license from {url}: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def restore_cascade_license(path):
    text = path.read_text()
    notice = text.split('<!--', 1)[1].split('-->', 1)[0].strip() + '\n'
    license_path = path.parent / 'LICENSE'
    if not license_path.is_file() or license_path.read_text() != notice:
        license_path.write_text(notice)


def ensure_model(name, path=None):
    if name == 'pulse':
        ensure_model('architecture')
    if name != 'cascade':
        ensure_license('pulse' if name == 'architecture' else name)
    relative, url, expected = ASSETS[name]
    default = ROOT / relative
    path = Path(path) if path is not None else default
    if path.resolve() != default.resolve():
        if not path.is_file() or path.read_bytes()[:80].startswith(b'version https://git-lfs'):
            raise RuntimeError(f'Custom model is missing or is an LFS pointer: {path}')
        return path
    if path.is_file() and digest(path) == expected:
        if name == 'cascade':
            restore_cascade_license(path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    print(f'Downloading {name} model to {path}', flush=True)
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            with urlopen(url, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        if digest(temporary) != expected:
            raise RuntimeError(f'Checksum mismatch for {name} model')
        temporary.replace(path)
        if name == 'cascade':
            restore_cascade_license(path)
    except Exception as exc:
        raise RuntimeError(f'Cannot download {name} model. Run scripts/download_models.py with internet access: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def prepare_models(args):
    ensure_model('cascade')
    if not args.preview_only:
        ensure_model('pulse', args.weights)
    if not args.no_analysis:
        ensure_model('face', args.face_model)
        ensure_model('pose', args.pose_model)


if __name__ == '__main__':
    for name in ASSETS:
        ensure_model(name)
    print('All camera model files and licenses are ready.')
