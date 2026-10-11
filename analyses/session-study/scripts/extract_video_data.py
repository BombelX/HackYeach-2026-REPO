#!/usr/bin/env python3
"""Group collector recordings into four conditions and extract live-model features."""
import argparse
import csv
import json
import math
import os
from collections import Counter
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ('calm', 'dictation', 'scam', 'intruder')


class ExtractionProgress:
    def __init__(self, session_id, duration):
        self.session_id = session_id
        self.duration = duration
        self.started = time.monotonic()
        self.last_update = self.started - 0.5
        self.displayed = False

    def update(self, frames, seconds, features, force=False):
        now = time.monotonic()
        if not force and now - self.last_update < 0.5:
            return
        elapsed = max(now - self.started, 1e-6)
        prefix = f"[{self.session_id[:8]}]"
        if self.duration:
            percent = min(100.0, seconds / self.duration * 100)
            status = f"{percent:5.1f}% | {seconds:6.1f}/{self.duration:.1f}s"
        else:
            status = f"{seconds:6.1f}s"
        speed = f"{frames / elapsed:.1f} frames/s" if elapsed >= 1 else 'starting'
        message = (f"\r{prefix} {status} | {frames} frames | "
                   f"{features} features | {speed}")
        sys.stderr.write(message)
        sys.stderr.flush()
        self.last_update = now
        self.displayed = True

    def finish(self):
        if self.displayed:
            sys.stderr.write('\n')
            sys.stderr.flush()
            self.displayed = False


def group_for(condition):
    if condition == 'calm' or re.fullmatch(r'calm_\d+', condition or ''):
        return 'calm'
    return condition if condition in GROUPS else None


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def inventory(data):
    records = {}
    db = data / 'participants.sqlite'
    if db.exists():
        with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute('SELECT s.id AS session_id, s.condition, s.order_index, '
                                    's.ended_at, p.code AS participant_code, p.deleted_at '
                                    'FROM sessions s JOIN participants p ON p.id=s.participant_id'):
                records[row['session_id']] = dict(row)
    sessions_dir = data / 'sessions'
    if not sessions_dir.is_dir():
        raise FileNotFoundError(f'Sessions directory not found: {sessions_dir}')
    for folder in sorted(sessions_dir.iterdir()):
        if not folder.is_dir():
            continue
        meta = {**records.get(folder.name, {}), **read_json(folder / 'meta.json')}
        chunks = [p for p in (folder / 'video').glob('*')
                  if p.is_file() and p.suffix.lower() in ('.webm', '.mp4')]
        chunks.sort(key=lambda p: (int(p.stem) if p.stem.isdigit() else float('inf'), p.name))
        indexes = [int(p.stem) for p in chunks if p.stem.isdigit()]
        contiguous = (len(indexes) == len(chunks) and indexes == list(range(len(chunks))))
        group = group_for(meta.get('condition'))
        status = ('deleted' if meta.get('deleted_at') else
                  'excluded_condition' if not group else
                  'no_video' if not chunks else
                  'missing_chunks' if not contiguous else
                  'incomplete_session' if not meta.get('ended_at') else 'ready')
        yield dict(session_id=folder.name, participant_code=meta.get('participant_code', 'unknown'),
                   condition=meta.get('condition'), group=group, order_index=meta.get('order_index'),
                   status=status, chunks=len(chunks), bytes=sum(p.stat().st_size for p in chunks),
                   source=str(folder), chunk_paths=chunks)


def pack_landmarks(result):
    return [dict(x=p.x, y=p.y, z=p.z, v=p.visibility) for p in result]


def posture_metrics(points, width, height):
    if not points or any(points[i]['v'] < 0.5 for i in (7, 8, 11, 12)):
        return None
    def xy(i):
        return points[i]['x'] * width, points[i]['y'] * height
    def tilt(a, b):
        angle = abs(math.degrees(math.atan2(a[1] - b[1], a[0] - b[0])))
        return min(angle, 180 - angle)
    le, re_, ls, rs = (xy(i) for i in (7, 8, 11, 12))
    width_px = math.hypot(ls[0] - rs[0], ls[1] - rs[1])
    return dict(shoulder_tilt_degrees=tilt(ls, rs), head_tilt_degrees=tilt(le, re_),
                head_shoulder_ratio=((ls[1] + rs[1] - le[1] - re_[1]) / (2 * width_px)
                                     if width_px > 1e-6 else None))


def extract(row, args, target):
    import av
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    from webrtc_server import Processor

    cv2.setNumThreads(1)
    processor_args = SimpleNamespace(toolbox=args.live_root / 'rPPG-Toolbox', weights=args.weights,
                                    device=args.device, preview_only=False, no_analysis=True,
                                    fps=30, min_frames=32, stride=15, window=10)
    processor = Processor(processor_args)
    face_options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(args.live_root / 'models/face_landmarker.task')),
        running_mode=vision.RunningMode.VIDEO, output_face_blendshapes=True)
    pose_options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(args.live_root / 'models/pose_landmarker_lite.task')),
        running_mode=vision.RunningMode.VIDEO)
    # MediaRecorder timeslices are byte fragments of ONE container, not independent clips.
    with tempfile.TemporaryDirectory(prefix='collector-video-') as temp:
        joined = Path(temp) / ('recording' + row['chunk_paths'][0].suffix)
        with joined.open('wb') as dst:
            for path in row['chunk_paths']:
                with path.open('rb') as src:
                    shutil.copyfileobj(src, dst)
        with (vision.FaceLandmarker.create_from_options(face_options) as face,
              vision.PoseLandmarker.create_from_options(pose_options) as pose,
              av.open(str(joined)) as container,
              (target / 'frames.jsonl.tmp').open('w') as out):
            stream = container.streams.video[0]
            duration = (float(stream.duration * stream.time_base)
                        if stream.duration is not None and stream.time_base is not None else
                        float(container.duration / av.time_base) if container.duration else None)
            if args.max_seconds is not None:
                duration = min(duration, args.max_seconds) if duration else args.max_seconds
            progress = ExtractionProgress(row['group'], duration)
            origin = previous = None
            last_processed = None
            last_output = -float('inf')
            count = output_count = bpm_count = duplicate_timestamps = 0
            bpm_sum = 0.0
            last_ms = -1
            for frame in container.decode(video=0):
                if frame.time is None:
                    raise ValueError('Frame lacks presentation timestamp; cannot align measurements')
                origin = frame.time if origin is None else origin
                t = float(frame.time - origin)
                if previous is not None and t < previous:
                    raise ValueError('Decreasing video timestamps')
                if previous is not None and t == previous:
                    duplicate_timestamps += 1
                    continue
                previous = t
                if args.max_seconds and t > args.max_seconds:
                    break
                bgr = frame.to_ndarray(format='bgr24')
                # Pulse sees all frames, regardless of the landmark export rate.
                _, pulse = processor.process(bgr.copy(), t + 1)
                count += 1
                last_processed = t
                if t - last_output < 1 / args.feature_fps - 1e-6:
                    progress.update(count, last_processed, output_count)
                    continue
                last_output = t
                last_ms = max(last_ms + 1, round(t * 1000))
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame.to_ndarray(format='rgb24'))
                fr = face.detect_for_video(image, last_ms)
                pr = pose.detect_for_video(image, last_ms)
                pts = pack_landmarks(pr.pose_landmarks[0]) if pr.pose_landmarks else []
                shapes = {c.category_name: c.score for c in fr.face_blendshapes[0]} if fr.face_blendshapes else {}
                bpm = pulse['heart_rate_bpm'] if pulse['window_seconds'] >= 5 else None
                item = dict(video_seconds=t, heart_rate_bpm=bpm,
                            heart_rate_status='estimate' if bpm is not None else 'warming_up_or_no_face',
                            pulse_window_seconds=pulse['window_seconds'], sampling_fps=pulse['sampling_fps'],
                            pulse_face_detected=pulse['face_detected'],
                            face_detected=bool(fr.face_landmarks), blendshapes=shapes,
                            face_landmarks=[dict(x=p.x, y=p.y, z=p.z) for p in fr.face_landmarks[0]]
                            if fr.face_landmarks else [], pose=pts,
                            posture=posture_metrics(pts, frame.width, frame.height))
                out.write(json.dumps(item, allow_nan=False) + '\n')
                output_count += 1
                if bpm is not None:
                    bpm_count += 1
                    bpm_sum += bpm
                progress.update(count, last_processed, output_count)
            if count:
                progress.update(count, last_processed, output_count, force=True)
            progress.finish()
            if not count:
                raise ValueError('No decodable video frames')
        (target / 'frames.jsonl.tmp').replace(target / 'frames.jsonl')
    return dict(decoded_frames=count, feature_frames=output_count, duration_seconds=last_processed,
                bpm_frames=bpm_count, duplicate_timestamp_frames_skipped=duplicate_timestamps,
                mean_heart_rate_bpm=bpm_sum / bpm_count if bpm_count else None,
                truncated=bool(args.max_seconds), pulse_method='live PhysNet',
                note='Experimental camera-based pulse estimate; no heartbeat/ECG ground truth.')


def process_group(args, rows):
    group_dir = args.output / args.group
    group_dir.mkdir(parents=True, exist_ok=True)
    frames_tmp = group_dir / 'frames.jsonl.tmp'
    manifest_tmp = group_dir / 'manifest.csv.tmp'
    summary_tmp = group_dir / 'summary.json.tmp'
    eligible = [row for row in rows if row['group'] == args.group and (
        row['status'] == 'ready' or
        (args.include_incomplete and row['status'] == 'incomplete_session'))]
    eligible_ids = {row['session_id'] for row in eligible}
    failures = 0
    totals = Counter()
    bpm_sum = 0.0
    manifest_rows = []
    with frames_tmp.open('w', encoding='utf-8') as aggregate:
        for index, row in enumerate(rows, start=1):
            entry = dict(
                session_id=row['session_id'],
                condition=row['condition'],
                order_index=row['order_index'],
                source_status=row['status'],
                status=row['status'],
                chunks=row['chunks'],
                bytes=row['bytes'],
                decoded_frames=0,
                feature_frames=0,
                error='',
            )
            if row['session_id'] not in eligible_ids:
                manifest_rows.append(entry)
                continue

            print(f"Processing {args.group} recording {index}/{len(rows)}: "
                  f"{row['session_id']}", flush=True)
            try:
                with tempfile.TemporaryDirectory(prefix='collector-features-') as temp:
                    summary = extract(row, args, Path(temp))
                    enriched_path = Path(temp) / 'enriched.jsonl'
                    with ((Path(temp) / 'frames.jsonl').open(encoding='utf-8') as frames,
                          enriched_path.open('w', encoding='utf-8') as enriched):
                        for line in frames:
                            feature = json.loads(line)
                            feature.update(
                                session_id=row['session_id'],
                                condition=row['condition'],
                                order_index=row['order_index'],
                            )
                            enriched.write(json.dumps(feature, allow_nan=False) + '\n')
                    with enriched_path.open(encoding='utf-8') as enriched:
                        shutil.copyfileobj(enriched, aggregate)
                entry.update(
                    status='processed',
                    decoded_frames=summary['decoded_frames'],
                    feature_frames=summary['feature_frames'],
                )
                totals.update({key: summary[key] for key in (
                    'decoded_frames', 'feature_frames', 'bpm_frames',
                    'duplicate_timestamp_frames_skipped')})
                if summary['mean_heart_rate_bpm'] is not None:
                    bpm_sum += summary['mean_heart_rate_bpm'] * summary['bpm_frames']
            except Exception as exc:
                failures += 1
                entry.update(status='error', error=str(exc))
                print(f"Failed to process {args.group} recording {row['session_id']}: {exc}",
                      file=sys.stderr, flush=True)
            manifest_rows.append(entry)

    fields = ('session_id', 'condition', 'order_index', 'source_status', 'status',
              'chunks', 'bytes', 'decoded_frames', 'feature_frames', 'error')
    with manifest_tmp.open('w', encoding='utf-8', newline='') as manifest_file:
        writer = csv.DictWriter(manifest_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest_rows)

    processed = len(eligible) - failures
    summary = dict(
        group=args.group,
        recordings_processed=processed,
        recordings_failed=failures,
        recordings_skipped=len(rows) - len(eligible),
        decoded_frames=totals['decoded_frames'],
        feature_frames=totals['feature_frames'],
        bpm_frames=totals['bpm_frames'],
        duplicate_timestamp_frames_skipped=totals['duplicate_timestamp_frames_skipped'],
        mean_heart_rate_bpm=bpm_sum / totals['bpm_frames'] if totals['bpm_frames'] else None,
        pulse_method='live PhysNet',
        note='Experimental camera-based pulse estimate; no heartbeat/ECG ground truth.',
    )
    summary_tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    frames_tmp.replace(group_dir / 'frames.jsonl')
    manifest_tmp.replace(group_dir / 'manifest.csv')
    summary_tmp.replace(group_dir / 'summary.json')
    print(json.dumps({**summary, 'output': str(group_dir.resolve())}), flush=True)
    return 1 if failures else 0


def launch_all_groups(args, parser):
    import torch

    if not torch.cuda.is_available():
        parser.error('Four CUDA GPUs are required for automatic scenario processing')
    if len(args.gpu_ids) != len(GROUPS) or len(set(args.gpu_ids)) != len(GROUPS):
        parser.error(f'Provide exactly {len(GROUPS)} distinct GPU IDs with --gpu-ids')
    if min(args.gpu_ids) < 0 or max(args.gpu_ids) >= torch.cuda.device_count():
        parser.error(f'GPU IDs {args.gpu_ids} are unavailable; '
                     f'found {torch.cuda.device_count()} CUDA device(s)')

    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment['OMP_NUM_THREADS'] = '4'
    environment['MKL_NUM_THREADS'] = '4'
    environment['OPENBLAS_NUM_THREADS'] = '4'
    workers = []
    for group, gpu_id in zip(GROUPS, args.gpu_ids):
        command = [
            sys.executable, str(Path(__file__).resolve()),
            '--data', str(args.data),
            '--output', str(args.output),
            '--live-root', str(args.live_root),
            '--weights', str(args.weights),
            '--group', group,
            '--device', f'cuda:{gpu_id}',
            '--feature-fps', str(args.feature_fps),
        ]
        if args.include_incomplete:
            command.append('--include-incomplete')
        if args.session:
            command.extend(('--session', args.session))
        if args.max_seconds is not None:
            command.extend(('--max-seconds', str(args.max_seconds)))
        print(f"Starting scenario {group} on cuda:{gpu_id}", flush=True)
        workers.append(subprocess.Popen(command, env=environment))

    exit_codes = [worker.wait() for worker in workers]
    if any(exit_codes):
        print(f"Scenario worker exit codes: {dict(zip(GROUPS, exit_codes))}",
              file=sys.stderr, flush=True)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/derived_video')
    parser.add_argument('--live-root', type=Path, default=Path('/workspace/hackyeah/HackYeach-2026-REPO'))
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--device', help='GPU for a single --group worker, e.g. cuda:0')
    parser.add_argument('--gpu-ids', type=int, nargs='+', default=[0, 1, 2, 3],
                        help='Four GPU IDs assigned to calm, dictation, scam, intruder')
    parser.add_argument('--group', choices=GROUPS, help='Process only this scenario group')
    parser.add_argument('--feature-fps', type=float, default=5)
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--session', help='Only process this session ID')
    parser.add_argument('--max-seconds', type=float, help='Limit decoding for a smoke test')
    parser.add_argument('--include-incomplete', action='store_true')
    args = parser.parse_args(argv)
    if args.feature_fps <= 0 or (args.max_seconds is not None and args.max_seconds <= 0):
        parser.error('Rates and duration must be positive')
    args.weights = args.weights or args.live_root / 'rPPG-Toolbox/final_model_release/UBFC-rPPG_PhysNet_DiffNormalized.pth'
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [row for row in inventory(args.data)
            if row['group'] and (args.group is None or row['group'] == args.group)
            and (not args.session or row['session_id'] == args.session)]
    if args.inventory_only:
        counts = {group: dict(Counter(row['status'] for row in rows if row['group'] == group))
                  for group in GROUPS if args.group is None or group == args.group}
        print(json.dumps(dict(groups=counts, output=str(args.output))))
        return 0
    if args.group is None:
        return launch_all_groups(args, parser)

    sys.path.insert(0, str(args.live_root))
    import torch
    if args.device is None:
        args.device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    if args.device.startswith('cuda') and not torch.cuda.is_available():
        parser.error(f'CUDA device requested ({args.device}), but CUDA is unavailable')
    if args.device.startswith('cuda:'):
        device_index = int(args.device.split(':', 1)[1])
        if device_index >= torch.cuda.device_count():
            parser.error(f'{args.device} is unavailable; found {torch.cuda.device_count()} CUDA device(s)')
    torch.set_num_threads(4)
    return process_group(args, rows)


if __name__ == '__main__':
    raise SystemExit(main())
