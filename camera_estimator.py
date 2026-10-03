#!/usr/bin/env python3
"""Live webcam pulse estimation with rPPG-Toolbox PhysNet checkpoints.

Run: venv/bin/python live_physnet.py
Dependencies: numpy scipy torch opencv-python (GUI build).
Press q or Escape to exit. Estimates are experimental, not medical measurements.
"""
import argparse
from collections import deque
import importlib.util
import json
from pathlib import Path
import queue
import sys
import threading
import time

import cv2
import numpy as np
from scipy import signal, sparse
from scipy.sparse.linalg import spsolve
import torch

ROOT = Path(__file__).resolve().parent


def normalize_frames(frames):
    """Match BaseLoader.diff_normalize_data, including its zero final frame."""
    frames = np.asarray(frames, dtype=np.float32)
    differences = np.diff(frames, axis=0) / (frames[1:] + frames[:-1] + 1e-7)
    scale = differences.std()
    if scale > 1e-12:
        differences /= scale
    else:
        differences.fill(0)
    return np.concatenate((np.nan_to_num(differences), np.zeros_like(frames[:1])))


def estimate_bpm(predictions, fs, prior=None, track_width=15.0):
    """Integrate difference labels, smoothness-detrend, bandpass, then FFT.

    With a prior (previous BPM), pick the peak within +/- track_width BPM of it,
    unless a much stronger peak exists elsewhere (lock lost, so re-acquire).
    """
    values = np.asarray(predictions, dtype=np.float64)
    # Frequency-grid padding cannot replace sufficient observation time.
    if (values.ndim != 1 or len(values) < 16 or not np.isfinite(values).all()
            or not np.isfinite(fs) or fs <= 6.6 or (len(values) - 1) / fs < 5):
        return None
    pulse = np.cumsum(values)
    n = len(pulse)
    d = sparse.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)],
                     [0, 1, 2], shape=(n - 2, n), format='csc')
    pulse -= spsolve(sparse.eye(n, format='csc') + 100**2 * (d.T @ d), pulse)
    if fs <= 6.6 or np.std(pulse) < 1e-10:
        return None
    filtered = signal.sosfiltfilt(signal.butter(2, [0.75, 2.5], fs=fs,
                                               btype='bandpass', output='sos'), pulse)
    frequencies, power = signal.periodogram(filtered, fs=fs, window='hann',
                                            nfft=max(2048, 2 ** (n - 1).bit_length()))
    mask = (frequencies >= 0.75) & (frequencies <= 2.5)
    # Track local peaks, not bins on a stronger peak's slope.
    peaks, _ = signal.find_peaks(power)
    peaks = peaks[mask[peaks]]
    if not len(peaks) or not np.isfinite(power).all() or power[peaks].max() <= 0:
        return None
    best = peaks[np.argmax(power[peaks])]
    if prior is not None and np.isfinite(prior):
        near = peaks[np.abs(frequencies[peaks] * 60 - prior) <= track_width]
        if len(near):
            tracked = near[np.argmax(power[near])]
            if power[tracked] * 3 >= power[best]:
                best = tracked
    return float(frequencies[best] * 60)


def load_model(toolbox, weights, device):
    path = toolbox / 'neural_methods/model/PhysNet.py'
    spec = importlib.util.spec_from_file_location('toolbox_physnet', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.PhysNet_padding_Encoder_Decoder_MAX(frames=128)
    state = torch.load(weights, map_location='cpu', weights_only=True)
    if 'state_dict' in state:
        state = state['state_dict']
    model.load_state_dict({k.removeprefix('module.'): v for k, v in state.items()})
    return model.to(device).eval()


def load_face_detector(toolbox):
    """Some OpenCV distributions omit the cascade; use the toolbox copy."""
    candidates = [toolbox / 'dataset/haarcascade_frontalface_default.xml']
    data = getattr(cv2, 'data', None)
    if data is not None and hasattr(data, 'haarcascades'):
        candidates.append(Path(data.haarcascades) / 'haarcascade_frontalface_default.xml')
    for path in candidates:
        if path.is_file():
            detector = cv2.CascadeClassifier(str(path))
            if not detector.empty():
                return detector
    searched = ', '.join(str(path) for path in candidates)
    raise RuntimeError(f'Could not load a face cascade. Checked: {searched}')


class LandmarkDetector:
    """Detect raw MediaPipe pose and face landmarks without assigning labels."""

    def __init__(self, pose_path, face_path):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        self.mp = mp
        self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(pose_path)),
            running_mode=vision.RunningMode.VIDEO))
        self.face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(face_path)),
            running_mode=vision.RunningMode.VIDEO, output_face_blendshapes=False))
        self.points = {'pose': [], 'face': []}
        self.timestamp_ms = None

    @staticmethod
    def serialize(landmarks):
        points = []
        for index, landmark in enumerate(landmarks):
            point = dict(index=index, x=float(landmark.x), y=float(landmark.y),
                         z=float(landmark.z))
            for field in ('visibility', 'presence'):
                value = getattr(landmark, field, None)
                if value is not None:
                    point[field] = float(value)
            points.append(point)
        return points

    def analyze(self, frame_bgr, ts_ms):
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        pose = self.pose.detect_for_video(image, ts_ms)
        face = self.face.detect_for_video(image, ts_ms)
        self.points = {
            'pose': self.serialize(pose.pose_landmarks[0]) if pose.pose_landmarks else [],
            'face': self.serialize(face.face_landmarks[0]) if face.face_landmarks else [],
        }
        self.timestamp_ms = ts_ms

    def draw(self, frame):
        h, w = frame.shape[:2]
        for group, points in self.points.items():
            for point in points:
                center = (int(point['x'] * w), int(point['y'] * h))
                radius = 3 if group == 'pose' else 1
                cv2.circle(frame, center, radius + 1, (0, 0, 0), -1)
                cv2.circle(frame, center, radius, (255, 255, 0), -1)


def inference_worker(model, device, jobs, results, stop, window_seconds):
    history = []  # list of (time, prediction)
    last_time = None
    prior = None  # previous BPM, used to keep the peak search near the last estimate
    try:
        while not stop.is_set():
            try:
                frames, timestamps = jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            # Variable-length window: n frames (a multiple of 4), resampled to a uniform rate.
            n = len(frames)
            times = np.linspace(timestamps[0], timestamps[-1], n)
            fs = (n - 1) / (times[-1] - times[0])
            raw = np.asarray(frames, dtype=np.float32)
            right = np.clip(np.searchsorted(timestamps, times), 1, n - 1)
            left = right - 1
            alpha = ((times - timestamps[left]) / (timestamps[right] - timestamps[left]))
            raw = raw[left] * (1 - alpha[:, None, None, None]) + raw[right] * alpha[:, None, None, None]
            tensor = torch.from_numpy(normalize_frames(raw).transpose(3, 0, 1, 2).copy()).unsqueeze(0)
            # The model's temporal pooling is sized for 128 frames; match it to this window.
            model.poolspa = torch.nn.AdaptiveAvgPool3d((n, 1, 1))
            with torch.inference_mode():
                prediction = model(tensor.to(device))[0].cpu().numpy().ravel()
            # Windows overlap: the newest prediction replaces older ones
            # for the same instants, then the new window is appended.
            history = [h for h in history if h[0] < times[0]]
            history.extend(zip(times, prediction))
            last_time = times[-1]
            cutoff = last_time - window_seconds
            history = [h for h in history if h[0] >= cutoff]
            t, p = np.asarray(history).T
            elapsed = t[-1] - t[0]
            uniform = np.linspace(t[0], t[-1], len(t))
            bpm = estimate_bpm(np.interp(uniform, t, p), (len(t) - 1) / elapsed, prior)
            prior = bpm
            results.put((bpm, fs, elapsed, None))
    except Exception as exc:
        results.put((None, 0, 0, str(exc)))
        stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--toolbox', type=Path, default=ROOT / 'rPPG-Toolbox')
    parser.add_argument('--weights', type=Path, default=None)
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu')
    parser.add_argument('--fps', type=float, default=30, help='maximum model sampling rate; does not change camera settings')
    parser.add_argument('--preview-only', action='store_true', help='show camera video without model inference to diagnose capture issues')
    parser.add_argument('--window', type=float, default=10, help='max seconds of pulse history used for each estimate')
    parser.add_argument('--stride', type=int, default=1, help='legacy option; updates now run every 0.5 seconds')
    parser.add_argument('--seed-bpm', type=float, default=0, help='placeholder BPM shown (marked with ~) until the first real reading; 0 disables')
    parser.add_argument('--min-frames', type=int, default=32, help='frames needed before the first estimate (multiple of 4; smaller = faster but rougher)')
    parser.add_argument('--pose-model', type=Path, default=ROOT / 'models/pose_landmarker_lite.task')
    parser.add_argument('--face-model', type=Path, default=ROOT / 'models/face_landmarker.task')
    parser.add_argument('--no-analysis', action='store_true', help='disable landmark detection')
    parser.add_argument('--threads', type=int, default=4, help='PyTorch CPU threads')
    args = parser.parse_args()
    if args.fps <= 6.6 or args.window < 5 or args.threads < 1 or args.stride < 1:
        parser.error('fps must exceed 6.6, window at least 5, threads and stride positive')
    if args.min_frames < 16 or args.min_frames > 128 or args.min_frames % 4:
        parser.error('min-frames must be a multiple of 4 between 16 and 128')
    torch.set_num_threads(args.threads)
    weights = args.weights or args.toolbox / 'final_model_release/UBFC-rPPG_PhysNet_DiffNormalized.pth'
    model = None if args.preview_only else load_model(args.toolbox, weights, args.device)
    detector = load_face_detector(args.toolbox)
    # Use the platform's native backend and request MJPG at 640x480. Raw YUYV
    # over USB or virtual cameras is a common cause of torn, half-green frames.
    # FPS is deliberately left alone, since renegotiating it can corrupt frames.
    if sys.platform.startswith('linux'):
        backend = cv2.CAP_V4L2
    elif sys.platform == 'win32':
        backend = cv2.CAP_DSHOW
    else:
        backend = cv2.CAP_ANY
    camera = cv2.VideoCapture(args.camera, backend)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(f'Could not open camera {args.camera}')
    camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    fourcc = int(camera.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, 'little').decode(errors='replace')
    print(f'Camera negotiated {fourcc} '
          f'{int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))}')
    analyzer = None
    if not args.no_analysis:
        missing = [str(m) for m in (args.pose_model, args.face_model) if not m.is_file()]
        if missing:
            print('Landmark detection disabled; model files not found: ' + ', '.join(missing))
        else:
            try:
                analyzer = LandmarkDetector(args.pose_model, args.face_model)
            except ImportError:
                print('Landmark detection disabled; install it with: pip install mediapipe')
    jobs, results, stop = queue.Queue(maxsize=1), queue.Queue(), threading.Event()
    worker = threading.Thread(target=inference_worker,
        args=(model, args.device, jobs, results, stop, args.window), daemon=True)
    if not args.preview_only:
        worker.start()
    frames, timestamps = deque(maxlen=128), deque(maxlen=128)
    since_job = 0
    box = target = None  # box is the smoothed face box; target is the latest detection
    count = 0
    recent = deque(maxlen=7)  # recent raw estimates, median-filtered for display
    bpm, shown_bpm, measured_fs, elapsed = None, None, 0, 0
    real_reading = False  # False while the displayed number is only the placeholder
    last_result = last_sample = 0
    last_job = None
    print(f'Using {weights} on {args.device}. Keep still in steady lighting; press q to exit.')
    try:
        while not stop.is_set():
            ok, frame = camera.read()
            now = time.monotonic()
            if not ok:
                raise RuntimeError('Camera stopped returning frames')
            # Own the display buffer instead of drawing on backend-owned memory.
            frame = frame.copy()
            frame = cv2.flip(frame, 1)
            # Detect landmarks every third frame to leave CPU for PhysNet.
            if analyzer is not None and count % 3 == 0:
                analyzer.analyze(frame, int(now * 1000))
            if count % 15 == 0:
                faces = detector.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                                                  scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
                target = (np.array(max(faces, key=lambda b: b[2] * b[3]), dtype=np.float64)
                          if len(faces) else None)
            count += 1
            # Glide the box toward the latest detection every frame so the crop doesn't jump.
            if target is None:
                box = None
            elif box is None:
                box = target.copy()
            else:
                box += 0.2 * (target - box)
            if box is None:
                frames.clear()
                timestamps.clear()
                since_job = 0
                last_job = None
                bpm = None
                recent.clear()
            elif not args.preview_only and now - last_sample >= 0.9 / args.fps:
                x, y, w, h = map(int, box)
                # Toolbox's enlarged face box (coefficient 1.5), clipped to image.
                x1, y1 = max(0, x - w // 4), max(0, y - h // 4)
                x2, y2 = min(frame.shape[1], x + w + w // 4), min(frame.shape[0], y + h + h // 4)
                crop = cv2.resize(frame[y1:y2, x1:x2], (72, 72), interpolation=cv2.INTER_AREA)
                frames.append(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                timestamps.append(now)
                last_sample = now
                since_job += 1
                # Update from the rolling frame buffer at most twice per second.
                if (len(frames) >= args.min_frames
                        and (last_job is None or now - last_job >= 0.5 - 1e-9)):
                    n = len(frames) // 4 * 4  # model needs a multiple of 4
                    try:
                        jobs.put_nowait((list(frames)[-n:], np.asarray(timestamps)[-n:]))
                        since_job = 0
                        last_job = now
                    except queue.Full:
                        pass  # Worker is busy; retry on the next frame.
            while not results.empty():
                bpm, measured_fs, elapsed, error = results.get_nowait()
                if error:
                    raise RuntimeError(f'Inference failed: {error}')
                last_result = now
                if bpm is None:
                    recent.clear()
                if bpm is not None:
                    # Light smoothing so the live number doesn't jitter. The first
                    # real reading blends away from the placeholder instead of jumping.
                    recent.append(bpm)
                    median_bpm = float(np.median(recent))
                    weight = 0.3 if real_reading else 0.5
                    shown_bpm = median_bpm if shown_bpm is None else (1 - weight) * shown_bpm + weight * median_bpm
                    real_reading = True
                    print(json.dumps({
                        'heart_rate_bpm': shown_bpm,
                        'sampling_fps': measured_fs,
                        'landmarks': analyzer.points if analyzer is not None else None,
                        'landmarks_timestamp_ms': analyzer.timestamp_ms if analyzer is not None else None,
                    }))
            # Until the first real reading, show a placeholder so the display never sits empty.
            if (not real_reading and box is not None and args.seed_bpm > 0
                    and not args.preview_only):
                shown_bpm = args.seed_bpm
                last_result = now
            if box is not None:
                x, y, w, h = map(int, box)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            if analyzer is not None:
                analyzer.draw(frame)
            cv2.imshow('Live PhysNet', frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
        while not results.empty():
            error = results.get_nowait()[3]
            if error:
                raise RuntimeError(f'Inference failed: {error}')
    finally:
        stop.set()
        camera.release()
        cv2.destroyAllWindows()
        if worker.is_alive():
            worker.join(timeout=2)


if __name__ == '__main__':
    main()
