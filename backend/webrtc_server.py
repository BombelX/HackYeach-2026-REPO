#!/usr/bin/env python3
"""Receive browser video over WebRTC and return annotated video and estimates."""
import argparse
import asyncio
import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import logging
import math
import ssl
from pathlib import Path
import time
import uuid

from aiohttp import web
from aiortc import MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame
import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
import torch

from camera_estimator import ROOT, LandmarkDetector, estimate_bpm, load_face_detector, load_model, normalize_frames, resolve_device
from scipy import signal, sparse
from scipy.sparse.linalg import spsolve

LOG = logging.getLogger(__name__)

# Feature names the fusion risk model reads from the recorder timeline (training/fusion/features.py).
TRACE_BLENDSHAPES = (
    'browDownLeft', 'browDownRight', 'browInnerUp', 'eyeBlinkLeft', 'eyeBlinkRight',
    'eyeSquintLeft', 'eyeSquintRight', 'eyeWideLeft', 'eyeWideRight', 'eyeLookDownLeft',
    'eyeLookDownRight', 'jawOpen', 'mouthClose', 'mouthFrownLeft', 'mouthFrownRight',
    'mouthPressLeft', 'mouthPressRight', 'mouthSmileLeft', 'mouthSmileRight', 'cheekSquintLeft',
)
TRACE_SECONDS = 600


def spectral_concentration(pulse, fs, bpm):
    """Share of 45-150 BPM band power within 0.1 Hz of the estimate (as in preprocessing/rppg.py)."""
    values = np.asarray(pulse, dtype=np.float64)
    n = len(values)
    if n < 16 or not np.isfinite(fs) or fs <= 5 or bpm is None:
        return None
    d = sparse.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)], [0, 1, 2], shape=(n - 2, n), format='csc')
    values = values - spsolve(sparse.eye(n, format='csc') + 100**2 * (d.T @ d), values)
    filtered = signal.sosfiltfilt(signal.butter(2, [0.75, 2.5], fs=fs, btype='bandpass', output='sos'), values)
    frequencies, power = signal.periodogram(filtered, fs=fs, window='hann', nfft=max(2048, 2 ** (n - 1).bit_length()))
    band = (frequencies >= 0.75) & (frequencies <= 2.5)
    total = float(power[band].sum())
    if total <= 1e-20:
        return None
    return float(power[band & (np.abs(frequencies - bpm / 60) <= 0.1)].sum() / total)


def posture_metrics(points, width, height, minimum_visibility=0.5):
    """Same posture definition as preprocessing/vision.py (ears 7/8, shoulders 11/12)."""
    if len(points) <= 12 or any(points[i].get('visibility', 0) < minimum_visibility for i in (7, 8, 11, 12)):
        return None
    xy = lambda i: np.array([points[i]['x'] * width, points[i]['y'] * height])  # noqa: E731
    left_ear, right_ear, left_shoulder, right_shoulder = (xy(i) for i in (7, 8, 11, 12))
    def tilt(a, b):
        angle = abs(math.degrees(math.atan2(a[1] - b[1], a[0] - b[0])))
        return min(angle, 180 - angle)
    shoulder_width = float(np.linalg.norm(left_shoulder - right_shoulder))
    if shoulder_width < 1e-6:
        return None
    return dict(shoulder_tilt_degrees=tilt(left_shoulder, right_shoulder),
                head_tilt_degrees=tilt(left_ear, right_ear),
                head_shoulder_ratio=float((left_shoulder[1] + right_shoulder[1] - left_ear[1] - right_ear[1])
                                          / (2 * shoulder_width)),
                shoulder_width_normalized=shoulder_width / width)


def measurement_output(session_id, **values):
    """Return the stable JSON contract consumed by the camera panel.

    A session can be read before a first frame arrives or after it ends. Keep
    every field present in those states so clients never have to infer whether
    a missing key means "not measured" or a protocol mismatch.
    """
    output = dict(
        session_id=session_id,
        timestamp=time.time(),
        status='waiting',
        heart_rate_bpm=None,
        heart_rate_stale=False,
        heart_rate_updated_at=None,
        face_detected=False,
        sampling_fps=None,
        window_seconds=None,
        landmarks=None,
        landmarks_timestamp_ms=None,
        frame_width=None,
        frame_height=None,
        error=None,
    )
    output.update(values)
    output['session_id'] = session_id
    return output


class Processor:
    """One stream's model, landmarks and pulse history; called on one worker."""
    def __init__(self, args):
        self.args = args
        self.detector = load_face_detector()
        self.model = None if args.preview_only else load_model(args.weights, args.device)
        self.analyzer = None if args.no_analysis else LandmarkDetector(args.pose_model, args.face_model)
        # estimate_bpm requires five seconds of signal. A fixed 128-frame
        # buffer holds only 4.27 s at 30 FPS, so it can never yield a pulse.
        buffer_frames = max(128, math.ceil(args.window * args.fps))
        buffer_frames += -buffer_frames % 4  # PhysNet input is divisible by 4.
        self.frames = deque(maxlen=buffer_frames)
        self.times = deque(maxlen=buffer_frames)
        self.history = []
        self.prior = self.bpm = None
        self.bpm_updated_at = None
        self.bpm_stale = False
        self.last_sample = 0
        self.last_inference = None
        self.count = self.since_job = 0
        self.box = self.target = None
        self.fs = self.elapsed = 0
        self.last_ts_ms = -1
        self.concentration = None
        self.started = None
        # Per-frame features for the fusion risk model; bounded so long sessions stay small.
        self.trace = deque(maxlen=int(TRACE_SECONDS * args.fps))

    def reset(self):
        self.frames.clear()
        self.times.clear()
        self.history.clear()
        self.prior = None
        self.bpm_stale = self.bpm is not None
        self.fs = self.elapsed = 0
        self.since_job = 0
        self.last_inference = None

    def process(self, frame, now):
        # Limit resolution before running detectors on untrusted remote frames.
        if max(frame.shape[:2]) > 960:
            scale = 960 / max(frame.shape[:2])
            frame = cv2.resize(frame, None, fx=scale, fy=scale)
        ts_ms = max(self.last_ts_ms + 1, int(now * 1000))
        self.last_ts_ms = ts_ms
        analyzed = bool(self.analyzer and self.count % 3 == 0)
        if analyzed:
            self.analyzer.analyze(frame, ts_ms)
        if self.started is None:
            self.started = now
        if self.count % 15 == 0:
            faces = self.detector.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                                                  scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            self.target = np.array(max(faces, key=lambda b: b[2] * b[3]), dtype=float) if len(faces) else None
        self.count += 1
        if self.target is None:
            self.box = None
            self.reset()
        else:
            self.box = self.target.copy() if self.box is None else self.box + 0.2 * (self.target - self.box)
            if self.model is not None and now - self.last_sample >= 0.9 / self.args.fps:
                x, y, w, h = map(int, self.box)
                x1, y1 = max(0, x - w // 4), max(0, y - h // 4)
                x2, y2 = min(frame.shape[1], x + w + w // 4), min(frame.shape[0], y + h + h // 4)
                crop = cv2.resize(frame[y1:y2, x1:x2], (72, 72), interpolation=cv2.INTER_AREA)
                self.frames.append(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                self.times.append(now)
                self.last_sample = now
                self.since_job += 1
                if (len(self.frames) >= self.args.min_frames
                        and (self.last_inference is None or now - self.last_inference >= 0.5 - 1e-9)):
                    self.infer()
                    self.last_inference = now
                    self.since_job = 0
            x, y, w, h = map(int, self.box)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        self.record(frame, now, analyzed)
        if self.analyzer:
            self.analyzer.draw(frame)
        result = dict(timestamp=time.time(), face_detected=self.box is not None,
                      heart_rate_bpm=self.bpm, heart_rate_stale=self.bpm_stale,
                      heart_rate_updated_at=self.bpm_updated_at,
                      sampling_fps=self.fs, window_seconds=self.elapsed,
                      landmarks=self.analyzer.points if self.analyzer else None,
                      landmarks_timestamp_ms=self.analyzer.timestamp_ms if self.analyzer else None,
                      frame_width=frame.shape[1], frame_height=frame.shape[0],
                      status='preview' if self.model is None else ('stale' if self.bpm_stale else ('measuring' if self.bpm is not None else 'warming_up')))
        return frame, result

    def record(self, frame, now, analyzed):
        height, width = frame.shape[:2]
        sample = dict(t=round((now - self.started) * 1000, 1), width=width,
                      bpm=None if self.bpm_stale else self.bpm,
                      concentration=None if self.bpm_stale else self.concentration,
                      face_crop_valid=self.box is not None)
        if analyzed:
            face = self.analyzer.points['face']
            shapes = self.analyzer.blendshapes
            sample['blendshapes'] = [shapes.get(name) for name in TRACE_BLENDSHAPES] if shapes else None
            sample['posture'] = posture_metrics(self.analyzer.points['pose'], width, height)
            if face:
                xs, ys = [p['x'] * width for p in face], [p['y'] * height for p in face]
                sample['face_bbox'] = [min(xs), min(ys), max(xs), max(ys)]
            else:
                sample['face_bbox'] = None
        self.trace.append(sample)

    def snapshot(self):
        return dict(blendshapes=list(TRACE_BLENDSHAPES), samples=list(self.trace),
                    started_epoch_ms=(time.time() - (time.monotonic() - self.started)) * 1000 if self.started is not None else None)

    def infer(self):
        n = len(self.frames) // 4 * 4
        timestamps = np.asarray(self.times)[-n:]
        times = np.linspace(timestamps[0], timestamps[-1], n)
        raw = np.asarray(self.frames, dtype=np.float32)[-n:]
        right = np.clip(np.searchsorted(timestamps, times), 1, n - 1)
        left = right - 1
        alpha = (times - timestamps[left]) / (timestamps[right] - timestamps[left])
        raw = raw[left] * (1 - alpha[:, None, None, None]) + raw[right] * alpha[:, None, None, None]
        tensor = torch.from_numpy(normalize_frames(raw).transpose(3, 0, 1, 2).copy()).unsqueeze(0)
        self.model.poolspa = torch.nn.AdaptiveAvgPool3d((n, 1, 1))
        with torch.inference_mode():
            prediction = self.model(tensor.to(self.args.device))[0].cpu().numpy().ravel()
        self.history = [h for h in self.history if times[-1] - self.args.window <= h[0] < times[0]]
        self.history.extend(zip(times, prediction))
        t, p = np.asarray(self.history).T
        self.fs = (n - 1) / (times[-1] - times[0])
        self.elapsed = float(t[-1] - t[0])
        pulse = np.interp(np.linspace(t[0], t[-1], len(t)), t, p)
        bpm = estimate_bpm(pulse, (len(t) - 1) / self.elapsed, self.prior)
        try:
            self.concentration = spectral_concentration(pulse, (len(t) - 1) / self.elapsed, bpm)
        except Exception:
            self.concentration = None
        if bpm is None:
            self.prior = None
            self.bpm_stale = self.bpm is not None
        else:
            self.prior = bpm
            self.bpm = bpm if self.bpm is None or self.bpm_stale else 0.7 * self.bpm + 0.3 * bpm
            self.bpm_updated_at = time.time()
            self.bpm_stale = False

    def close(self):
        if self.analyzer:
            self.analyzer.pose.close()
            self.analyzer.face.close()


class Session:
    def __init__(self, args):
        self.id = uuid.uuid4().hex
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=args.ice_servers))
        self.args = args
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.processor = None
        self.task = self.timeout_task = None
        self.output = OutputTrack()
        self.latest = measurement_output(self.id)
        self.subscribers = set()
        self.closed = False

    def publish(self, result):
        self.latest = measurement_output(self.id, **result)
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(self.latest)

    async def consume(self, track):
        loop = asyncio.get_running_loop()
        try:
            initialization = loop.run_in_executor(self.executor, Processor, self.args)
            try:
                self.processor = await asyncio.shield(initialization)
            except asyncio.CancelledError:
                # Model construction cannot be interrupted in a worker thread.
                # Retain its result so close() can release the landmarkers.
                self.processor = await initialization
                raise
            # Drain incoming media independently: a slow model never builds a frame backlog.
            incoming = asyncio.Queue(maxsize=1)
            async def drain():
                try:
                    while True:
                        frame = await track.recv()
                        if incoming.full():
                            incoming.get_nowait()
                        incoming.put_nowait((frame, time.monotonic()))
                finally:
                    if incoming.full():
                        incoming.get_nowait()
                    incoming.put_nowait(None)
            reader = asyncio.create_task(drain())
            try:
                while True:
                    item = await incoming.get()
                    if item is None:
                        break
                    frame, captured = item
                    image, result = await loop.run_in_executor(
                        self.executor, self.processor.process, frame.to_ndarray(format='bgr24'), captured)
                    output = VideoFrame.from_ndarray(image, format='bgr24')
                    output.pts, output.time_base = frame.pts, frame.time_base
                    self.output.push(output)
                    self.publish(result)
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except MediaStreamError:
            pass
        except Exception:
            LOG.exception('Processing failed for session %s', self.id)
            self.publish(dict(status='error', error='Video processing failed; check server logs', heart_rate_bpm=None))
        finally:
            self.output.stop()
            if not self.closed and self.latest['status'] != 'error':
                self.publish(dict(status='ended', heart_rate_bpm=None))

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timeout_task and self.timeout_task is not asyncio.current_task():
            self.timeout_task.cancel()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.pc.close()
        self.output.stop()
        if self.processor:
            await asyncio.get_running_loop().run_in_executor(self.executor, self.processor.close)
        self.executor.shutdown(wait=False)
        self.publish(dict(status='closed', heart_rate_bpm=None))


class OutputTrack(MediaStreamTrack):
    kind = 'video'

    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue(maxsize=1)

    def push(self, frame):
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(frame)

    def stop(self):
        super().stop()
        self.push(None)

    async def recv(self):
        frame = await self.queue.get()
        if frame is None or self.readyState != 'live':
            raise MediaStreamError
        return frame


class FrameSession:
    def __init__(self, args):
        self.id = 'frame-' + uuid.uuid4().hex
        self.args = args
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.processor = None
        self.lock = asyncio.Lock()
        self.latest = measurement_output(self.id)
        self.closed = False

    async def initialize(self):
        initialization = asyncio.get_running_loop().run_in_executor(self.executor, Processor, self.args)
        try:
            self.processor = await asyncio.shield(initialization)
        except asyncio.CancelledError:
            self.processor = await initialization
            raise

    async def process(self, jpeg):
        async with self.lock:
            if self.closed:
                raise web.HTTPNotFound(text='Unknown or expired session')
            try:
                with Image.open(BytesIO(jpeg)) as header:
                    if header.format != 'JPEG' or max(header.size) > 960:
                        raise web.HTTPBadRequest(text='Expected JPEG frame no larger than 960 pixels per side')
            except (UnidentifiedImageError, OSError, ValueError):
                raise web.HTTPBadRequest(text='Invalid JPEG frame')
            array = np.frombuffer(jpeg, dtype=np.uint8)
            image = cv2.imdecode(array, cv2.IMREAD_COLOR)
            if image is None or max(image.shape[:2]) > 960:
                raise web.HTTPBadRequest(text='Expected JPEG frame no larger than 960 pixels per side')
            loop = asyncio.get_running_loop()
            frame, result = await loop.run_in_executor(self.executor, self.processor.process, image, time.monotonic())
            encoded = await loop.run_in_executor(self.executor, cv2.imencode, '.jpg', frame)
            ok, buffer = encoded
            if not ok:
                raise RuntimeError('Could not encode annotated frame')
            self.latest = measurement_output(self.id, **result)
            return {'measurement': self.latest, 'image': base64.b64encode(buffer).decode('ascii')}

    async def close(self):
        async with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.processor:
                await asyncio.get_running_loop().run_in_executor(self.executor, self.processor.close)
            self.executor.shutdown(wait=True)


def create_app(args):
    app = web.Application(client_max_size=256 * 1024)
    sessions = {}
    frame_sessions = {}

    async def remove(session):
        sessions.pop(session.id, None)
        await session.close()

    async def offer(request):
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text='Expected JSON containing sdp and type=offer')
        if not isinstance(data, dict) or data.get('type') != 'offer' or not isinstance(data.get('sdp'), str):
            raise web.HTTPBadRequest(text='Expected sdp string and type=offer')
        if len(sessions) + len(frame_sessions) >= args.max_sessions:
            raise web.HTTPServiceUnavailable(text='Session limit reached')
        session = Session(args)
        sessions[session.id] = session
        @session.pc.on('track')
        def on_track(track):
            if track.kind == 'video' and session.task is None:
                session.pc.addTrack(session.output)
                session.task = asyncio.create_task(session.consume(track))
        @session.pc.on('connectionstatechange')
        async def on_state():
            if session.pc.connectionState in ('failed', 'closed'):
                await remove(session)
        async def expire():
            await asyncio.sleep(args.session_timeout)
            await remove(session)
        session.timeout_task = asyncio.create_task(expire())
        try:
            await session.pc.setRemoteDescription(RTCSessionDescription(sdp=data['sdp'], type='offer'))
            if session.task is None:
                raise ValueError('Offer must contain a video track')
            await session.pc.setLocalDescription(await session.pc.createAnswer())
        except Exception as exc:
            await remove(session)
            LOG.warning('Rejected offer: %s', exc)
            raise web.HTTPBadRequest(text='Invalid WebRTC video offer')
        base = f'/api/sessions/{session.id}'
        return web.json_response(dict(sdp=session.pc.localDescription.sdp, type='answer',
                                      session_id=session.id, output_url=base + '/output',
                                      events_url=base + '/events'))

    def get_session(request):
        session = sessions.get(request.match_info['session_id'])
        if session is None:
            raise web.HTTPNotFound(text='Unknown or expired session')
        return session

    async def output(request):
        return web.json_response(get_session(request).latest)

    async def events(request):
        session = get_session(request)
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        queue = asyncio.Queue(maxsize=1)
        session.subscribers.add(queue)
        queue.put_nowait(session.latest)
        async def send():
            while True:
                result = await queue.get()
                await ws.send_json(result)
                if result['status'] == 'closed':
                    await ws.close()
                    return
        sender = asyncio.create_task(send())
        try:
            async for _ in ws:
                pass
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            session.subscribers.discard(queue)
        return ws

    async def trace(request):
        key = request.match_info['session_id']
        session = sessions.get(key) or frame_sessions.get(key)
        if session is None or session.closed:
            raise web.HTTPNotFound(text='Unknown or expired session')
        if session.processor is None:
            return web.json_response(dict(blendshapes=list(TRACE_BLENDSHAPES), samples=[]))
        return web.json_response(await asyncio.get_running_loop().run_in_executor(
            session.executor, session.processor.snapshot))

    async def delete(request):
        await remove(get_session(request))
        return web.Response(status=204)

    async def index(request):
        return web.FileResponse(ROOT / 'static/webrtc.html')

    async def health(request):
        return web.json_response(dict(status='ok', sessions=len(sessions) + len(frame_sessions)))

    async def create_frame_session(request):
        if len(sessions) + len(frame_sessions) >= args.max_sessions:
            raise web.HTTPServiceUnavailable(text='Session limit reached')
        session = FrameSession(args)
        frame_sessions[session.id] = session
        try:
            await session.initialize()
        except asyncio.CancelledError:
            frame_sessions.pop(session.id, None)
            await session.close()
            raise
        except Exception:
            frame_sessions.pop(session.id, None)
            await session.close()
            LOG.exception('Could not initialize frame processor')
            raise web.HTTPServiceUnavailable(text='Camera analysis unavailable')
        async def expire():
            await asyncio.sleep(args.session_timeout)
            frame_sessions.pop(session.id, None)
            await session.close()
        session.timeout_task = asyncio.create_task(expire())
        return web.json_response({'session_id': session.id})

    def frame_session(request):
        session = frame_sessions.get(request.match_info['session_id'])
        if session is None:
            raise web.HTTPNotFound(text='Unknown or expired session')
        return session

    async def process_frame(request):
        if request.content_type != 'image/jpeg':
            raise web.HTTPUnsupportedMediaType(text='Expected image/jpeg')
        session = frame_session(request)
        try:
            return web.json_response(await session.process(await request.read()))
        except (web.HTTPException, asyncio.CancelledError):
            raise
        except Exception:
            LOG.exception('Frame processing failed for session %s', session.id)
            raise web.HTTPInternalServerError(text='Frame processing failed')

    async def delete_frame_session(request):
        session = frame_session(request)
        frame_sessions.pop(session.id, None)
        session.timeout_task.cancel()
        await session.close()
        return web.Response(status=204)

    async def cleanup(app):
        await asyncio.gather(*(s.close() for s in list(sessions.values())))
        sessions.clear()
        await asyncio.gather(*(s.close() for s in list(frame_sessions.values())))
        frame_sessions.clear()

    app.router.add_get('/', index)
    app.router.add_get('/health', health)
    app.router.add_post('/api/webrtc/offer', offer)
    app.router.add_get('/api/sessions/{session_id}/output', output)
    app.router.add_get('/api/sessions/{session_id}/events', events)
    app.router.add_get('/api/sessions/{session_id}/trace', trace)
    app.router.add_delete('/api/sessions/{session_id}', delete)
    app.router.add_post('/api/frames/sessions', create_frame_session)
    app.router.add_post('/api/frames/sessions/{session_id}/frame', process_frame)
    app.router.add_delete('/api/frames/sessions/{session_id}', delete_frame_session)
    app.on_shutdown.append(cleanup)
    return app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--ssl-cert', type=Path, help='TLS certificate file for HTTPS camera access')
    parser.add_argument('--ssl-key', type=Path, help='TLS private key file for HTTPS camera access')
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu')
    parser.add_argument('--preview-only', action='store_true')
    parser.add_argument('--no-analysis', action='store_true')
    parser.add_argument('--pose-model', type=Path, default=ROOT.parent / 'models/mediapipe/pose_landmarker_lite.task')
    parser.add_argument('--face-model', type=Path, default=ROOT.parent / 'models/mediapipe/face_landmarker.task')
    parser.add_argument('--fps', type=float, default=30)
    parser.add_argument('--window', type=float, default=10)
    parser.add_argument('--stride', type=int, default=1, help='legacy option; updates now run every 0.5 seconds')
    parser.add_argument('--min-frames', type=int, default=32)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--max-sessions', type=int, default=4)
    parser.add_argument('--session-timeout', type=float, default=3600, help='maximum session lifetime in seconds')
    parser.add_argument('--ice-servers', default='[]', help='JSON array of RTCIceServer settings (STUN/TURN)')
    args = parser.parse_args(argv)
    args.device = resolve_device(args.device)
    if bool(args.ssl_cert) != bool(args.ssl_key):
        parser.error('ssl-cert and ssl-key must be provided together')
    if args.fps <= 6.6 or args.window < 5 or min(args.stride, args.threads, args.max_sessions, args.session_timeout) <= 0:
        parser.error('fps must exceed 6.6, window >= 5, and other limits must be positive')
    if args.min_frames < 16 or args.min_frames > 128 or args.min_frames % 4:
        parser.error('min-frames must be a multiple of 4 between 16 and 128')
    try:
        args.ice_servers = [RTCIceServer(**item) for item in json.loads(args.ice_servers)]
    except (TypeError, ValueError):
        parser.error('ice-servers must be a JSON array of RTCIceServer settings')
    args.weights = args.weights or ROOT.parent / 'models/physnet/UBFC-rPPG_PhysNet_DiffNormalized.pth'
    return args


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    import runpy
    downloader = runpy.run_path(str(ROOT.parent / 'scripts/download_models.py'))
    downloader['prepare_models'](args)
    torch.set_num_threads(args.threads)
    ssl_context = None
    if args.ssl_cert:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.ssl_cert, args.ssl_key)
    web.run_app(create_app(args), host=args.host, port=args.port, ssl_context=ssl_context)
