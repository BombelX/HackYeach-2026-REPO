#!/usr/bin/env python3
"""Indexed, bounded parallel extraction of one unusually long recording.

This adapter leaves preprocessing package files unchanged. A video is remuxed
without encoding, preserving packet PTS. Each core is decoded with temporal
context on both sides. Only real core features and an exact 30 Hz pulse grid
are retained. Pulse amplitudes/history remain independent between model parts.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _WindowContainer:
    """Seek an indexed source and expose an exact grid anchor outside the core."""
    def __init__(self, container, spec):
        self.container = container
        self.spec = spec
        self.streams = container.streams
        self.duration = container.duration
        self.stats = dict(core_decoded_frames=0, core_duplicate_pts=0,
                          synthetic_warmup_anchor=False, first_core_pts=None,
                          last_core_pts=None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.container.close()

    def decode(self, video=0):
        import av
        spec = self.spec
        stream = self.streams.video[video]
        origin = spec['source_pts_start_seconds']
        anchor = origin + spec['warmup_start_seconds']
        end = origin + spec['decode_end_seconds']
        offset = math.floor(anchor / float(stream.time_base))
        self.container.seek(offset, stream=stream, backward=True, any_frame=False)
        anchored = False
        previous_core_pts = None
        for frame in self.container.decode(video=video):
            if frame.pts is None or frame.time_base is None:
                raise ValueError('Segment frame lacks presentation clock')
            stamp = float(frame.pts * frame.time_base)
            if stamp < anchor - 1e-7:
                continue
            if stamp > end + 1e-7:
                break
            if not anchored:
                if stamp > anchor + 1e-7:
                    if spec['core_start_sample'] == 0:
                        raise ValueError('The first source frame must be a real grid origin')
                    # This frame belongs only to warmup, never a core. Its exact
                    # timestamp establishes the trained global 30 Hz grid.
                    synthetic = av.VideoFrame.from_ndarray(frame.to_ndarray(format='rgb24'), format='rgb24')
                    synthetic.time_base = Fraction(1, 1_000_000)
                    synthetic.pts = round(anchor * 1_000_000)
                    self.stats['synthetic_warmup_anchor'] = True
                    yield synthetic
                anchored = True
            seconds = stamp - origin
            if spec['core_start_seconds'] - 1e-7 <= seconds < spec['core_end_seconds'] - 1e-7:
                if previous_core_pts == stamp:
                    self.stats['core_duplicate_pts'] += 1
                else:
                    self.stats['core_decoded_frames'] += 1
                    self.stats['first_core_pts'] = stamp if self.stats['first_core_pts'] is None else self.stats['first_core_pts']
                    self.stats['last_core_pts'] = stamp
                previous_core_pts = stamp
            yield frame
        if not anchored:
            raise ValueError(f'No decoded frames near warmup anchor {anchor}')


def _segment_worker(indexed_path, output_dir, device, config_dict, spec):
    # Import numerical packages only after inheriting parent thread limits.
    from preprocessing.vision import VisionConfig, VisionExtractor
    import av
    original_open = av.open
    window = None

    def indexed_open(path, *args, **kwargs):
        nonlocal window
        if str(path) != str(indexed_path):
            return original_open(path, *args, **kwargs)
        window = _WindowContainer(original_open(path, *args, **kwargs), spec)
        return window

    config = VisionConfig(**config_dict)
    config.max_seconds = None  # The global cutoff is already in the segment spec.
    extractor = VisionExtractor(device, config)
    av.open = indexed_open
    try:
        summary = extractor.extract(indexed_path, output_dir)
    finally:
        av.open = original_open
    return {'spec': spec, 'summary': summary, 'window_stats': window.stats,
            'output_dir': str(output_dir), 'device': device}


def _packet_metadata(path, max_seconds=None):
    """Packet PTS equals decoded frame PTS for the collector's VP8 streams."""
    import av
    times = []
    keyframes = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        codec = stream.codec_context.name
        if codec not in {'vp8', 'vp9'}:
            raise ValueError(f'Parallel adapter currently supports collector VP8/VP9, got {codec}')
        nominal = float(stream.average_rate) if stream.average_rate else None
        width, height = stream.codec_context.width, stream.codec_context.height
        for packet in container.demux(stream):
            if packet.pts is not None and packet.size:
                times.append(float(packet.pts * packet.time_base))
                keyframes.append(bool(packet.is_keyframe))
    if not times:
        raise ValueError('No video packets after indexed remux')
    start = min(times)
    if max_seconds is not None:
        selected = [(t, keyframe) for t, keyframe in zip(times, keyframes) if t - start <= max_seconds + 1e-7]
        times = [item[0] for item in selected]
        keyframes = [item[1] for item in selected]
    unique = sorted(set(times))
    if len(unique) != len(times):
        # Duplicate PTS is legal in the main extractor, which skips duplicates.
        duplicate_count = len(times) - len(unique)
    else:
        duplicate_count = 0
    end = max(unique)
    return dict(pts_start_seconds=start, pts_end_seconds=end, duration_seconds=end - start,
                nominal_fps=nominal, width=width, height=height, codec=codec,
                unique_packet_pts=unique, packet_duplicate_pts=duplicate_count,
                packet_pts_keyframes_sha256=hashlib.sha256(json.dumps(list(zip(times,keyframes)),separators=(',',':')).encode()).hexdigest())


def _segments(metadata, segment_seconds, warmup_seconds, lookahead_seconds, config):
    fps = config.pulse_fps
    stride_seconds = config.pulse_stride_frames / fps
    # Requests such as 30 s are rounded to 32 s so every model window retains
    # the original global phase. 307.2 s is already exactly 96 strides.
    core_strides = math.ceil(segment_seconds / stride_seconds - 1e-8)
    core_samples = core_strides * config.pulse_stride_frames
    warmup_strides = math.ceil(warmup_seconds / stride_seconds - 1e-8)
    warmup_samples = warmup_strides * config.pulse_stride_frames
    lookahead_strides = math.ceil(lookahead_seconds / stride_seconds - 1e-8)
    lookahead_samples = lookahead_strides * config.pulse_stride_frames
    final_sample = math.floor(metadata['duration_seconds'] * fps + 1e-7)
    stop_sample = final_sample + 1
    result = []
    for part_id, start in enumerate(range(0, stop_sample, core_samples)):
        stop = min(stop_sample, start + core_samples)
        result.append(dict(part_id=part_id, core_start_sample=start, core_stop_sample=stop,
                           core_start_seconds=start / fps, core_end_seconds=stop / fps,
                           warmup_start_sample=max(0, start - warmup_samples),
                           warmup_start_seconds=max(0, start - warmup_samples) / fps,
                           decode_end_seconds=min(metadata['duration_seconds'], (stop + lookahead_samples) / fps),
                           source_pts_start_seconds=metadata['pts_start_seconds'],
                           final_part=stop == stop_sample))
    return result


def _stream_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _implementation_sha256():
    return hashlib.sha256(b''.join(path.read_bytes() for path in sorted((ROOT / 'preprocessing').glob('*.py')))).hexdigest()


def _cache_artifacts_sha256(output_dir):
    return {name: _stream_sha256(Path(output_dir) / name) for name in
            ('video_frames.jsonl', 'pulse.jsonl', 'pulse_windows.jsonl', 'video_summary.json')}


def _read_rows(path):
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            yield json.loads(line)


def _merge_parts(parts, output_dir, metadata, config, *, validation=None):
    """Merge disjoint cores with exact grid coverage and explicit part history."""
    parts = sorted(parts, key=lambda part: part['spec']['part_id'])
    pts_to_index = {round(t * 1_000_000): i for i, t in enumerate(metadata['unique_packet_pts'])}
    origin = metadata['pts_start_seconds']
    fps = config.pulse_fps
    counts = dict(feature_frames=0, face_detected_frames=0, pose_detected_frames=0,
                  pulse_samples=0, valid_pulse_samples=0, pulse_windows=0,
                  valid_pulse_windows=0, invalid_uniform_samples=0,
                  interpolated_uniform_samples=0, model_history_parts=len(parts))
    next_sample = 0
    last_frame_pts = -float('inf')
    segment_ids = {}
    core_boundaries = []
    expected_features = []
    pulse_last = -float('inf')
    with ((output_dir / 'video_frames.jsonl').open('w', encoding='utf-8') as frames_out,
          (output_dir / 'pulse.jsonl').open('w', encoding='utf-8') as pulse_out,
          (output_dir / 'pulse_windows.jsonl').open('w', encoding='utf-8') as windows_out):
        for part in parts:
            spec = part['spec']; folder = Path(part['output_dir']); part_id = spec['part_id']
            start, end = spec['core_start_seconds'], spec['core_end_seconds']
            for row in _read_rows(folder / 'video_frames.jsonl'):
                stamp = row['pts_seconds']
                seconds = stamp - origin
                if not start - 1e-7 <= seconds < end - 1e-7:
                    continue
                key = round(stamp * 1_000_000)
                if key not in pts_to_index:
                    raise ValueError('A synthetic or unknown source frame entered the core output')
                if stamp <= last_frame_pts:
                    raise ValueError('Duplicate or backward feature PTS across model parts')
                row['segment_frame_index'] = row['frame_index']
                row['frame_index'] = pts_to_index[key]
                row['video_seconds'] = seconds
                row['model_history_segment_id'] = part_id
                row['temporal_segment_core_start_seconds'] = start
                last_frame_pts = stamp
                frames_out.write(json.dumps(row, allow_nan=False) + '\n')
                counts['feature_frames'] += 1
                counts['face_detected_frames'] += bool(row['face_detected'])
                counts['pose_detected_frames'] += bool(row['pose_detected'])
            for row in _read_rows(folder / 'pulse.jsonl'):
                index = spec['warmup_start_sample'] + row['sample_index']
                if not spec['core_start_sample'] <= index < spec['core_stop_sample']:
                    continue
                if index != next_sample:
                    raise ValueError(f'Lost/duplicate pulse sample at a core seam: {index} != {next_sample}')
                if not row['pulse_valid'] and any(row.get(key) is not None for key in ('pulse_difference', 'pulse_value', 'heart_rate_bpm')):
                    raise ValueError('Invalid pulse sample contains a numeric signal or BPM')
                if row.get('heart_rate_bpm') is not None and row.get('pulse_window_seconds', 0) < config.minimum_hr_seconds - 1e-7:
                    raise ValueError('BPM sample emitted before its required history warmup')
                if row['pulse_valid'] and row['model_padded_window'] and not spec['final_part']:
                    raise ValueError('Padded neural window leaked into an interior core')
                row['sample_index'] = index
                row['video_seconds'] = index / fps
                row['pts_seconds'] = origin + index / fps
                row['model_history_segment_id'] = part_id
                row['core_boundary'] = index == spec['core_start_sample']
                row['model_history_independent'] = True
                row['pulse_value_status'] = 'relative_part_integral' if row['pulse_value'] is not None else 'missing_or_invalid_face'
                if row['core_boundary'] and part_id > 0:
                    row['pulse_value'] = None
                    row['pulse_value_status'] = 'model_history_boundary'
                if row['core_boundary']:
                    core_boundaries.append({key: row.get(key) for key in ('sample_index', 'video_seconds', 'model_history_segment_id',
                                                                            'pulse_window_seconds', 'pulse_valid', 'heart_rate_bpm',
                                                                            'pulse_value', 'pulse_value_status')})
                local_segment = row['pulse_segment_id']
                if local_segment is not None:
                    key = (part_id, local_segment)
                    segment_ids.setdefault(key, len(segment_ids) + 1)
                    row['pulse_segment_id'] = segment_ids[key]
                next_sample += 1
                if row['video_seconds'] <= pulse_last:
                    raise ValueError('Pulse grid lost strict monotonicity')
                pulse_last = row['video_seconds']
                pulse_out.write(json.dumps(row, allow_nan=False) + '\n')
                counts['pulse_samples'] += 1
                counts['valid_pulse_samples'] += bool(row['pulse_valid'])
                counts['invalid_uniform_samples'] += not row['face_crop_valid']
                counts['interpolated_uniform_samples'] += bool(row['temporal_interpolated'])
            for row in _read_rows(folder / 'pulse_windows.jsonl'):
                offset = spec['warmup_start_seconds']
                window_start = offset + row['video_seconds_start']
                window_end = offset + row['video_seconds_end']
                # Context windows overlapping a core are retained as provenance.
                if window_end < start - 1e-7 or window_start >= end - 1e-7:
                    continue
                row['segment_window_id'] = row['window_id']
                row['window_id'] = counts['pulse_windows']
                row['video_seconds_start'] = window_start
                row['video_seconds_end'] = window_end
                row['model_history_segment_id'] = part_id
                row['core_start_seconds'] = start
                row['core_end_seconds'] = end
                windows_out.write(json.dumps(row, allow_nan=False) + '\n')
                counts['pulse_windows'] += 1
                counts['valid_pulse_windows'] += row['status'] == 'estimate'
    expected_samples = math.floor(metadata['duration_seconds'] * fps + 1e-7) + 1
    if next_sample != expected_samples:
        raise ValueError(f'Final pulse coverage mismatch: {next_sample} != {expected_samples}')
    # Feature selection must match the full-file 5 Hz timestamp scheduling.
    next_feature = 0.0
    for stamp in metadata['unique_packet_pts']:
        seconds = stamp - origin
        if seconds + 1e-8 >= next_feature:
            expected_features.append(stamp)
            next_feature = (math.floor((seconds + 1e-8) * config.feature_fps) + 1) / config.feature_fps
    merged_features = [row['pts_seconds'] for row in _read_rows(output_dir / 'video_frames.jsonl')]
    if merged_features != expected_features:
        raise ValueError('Feature PTS coverage differs from the single-pass global feature schedule')
    counts['decoded_frames'] = sum(p['window_stats']['core_decoded_frames'] for p in parts)
    if counts['decoded_frames'] != len(metadata['unique_packet_pts']):
        raise ValueError('Core decoded-frame coverage does not match indexed source packet PTS')
    counts['duplicate_timestamp_frames_skipped'] = sum(p['window_stats']['core_duplicate_pts'] for p in parts)
    if len(core_boundaries) != len(parts):
        raise ValueError('Model part boundaries are missing from the pulse core outputs')
    if validation is not None:
        validation.update(status='PASS', errors=[],
                          frames=counts['feature_frames'], expected_feature_frames=len(expected_features),
                          pulse_samples=counts['pulse_samples'], expected_pulse_samples=expected_samples,
                          first_sample_index=0, last_sample_index=next_sample - 1,
                          decoded_unique_frames=counts['decoded_frames'], expected_decoded_unique_frames=len(metadata['unique_packet_pts']),
                          invalid_pulse_samples=counts['pulse_samples'] - counts['valid_pulse_samples'],
                          parts=len(parts), padded_interior_samples=0,
                          actual_feature_pts_match_single_pass_schedule=True,
                          synthetic_core_frames=0, duplicate_or_missing_core_samples=0,
                          core_boundaries=core_boundaries, pulse_value_seam_gaps=max(0, len(parts) - 1),
                          independently_numbered_pulse_segments=len(segment_ids),
                          bpm_minimum_history_seconds=config.minimum_hr_seconds)
    return counts


class ParallelVisionExtractor:
    """VisionExtractor-compatible adapter with four-GPU temporal partitioning."""
    def __init__(self, device='cuda:0', config=None, *, workers=16, gpu_ids=(0, 1, 2, 3),
                 segment_seconds=307.2, warmup_seconds=16.0, lookahead_seconds=12.8):
        from preprocessing.vision import VisionConfig
        self.config = config if isinstance(config, VisionConfig) else VisionConfig(**(config or {}))
        self.config.validate()
        if self.config.feature_fps != 5 or self.config.pulse_stride_frames != 96:
            raise ValueError('Parallel adapter currently supports the trained/default 5 Hz feature and 96-frame stride grids')
        if not str(device).startswith('cpu') and not gpu_ids:
            raise ValueError('At least one CUDA GPU ID is required')
        required_warmup = self.config.hr_history_seconds + self.config.pulse_window_frames / self.config.pulse_fps + self.config.hr_update_seconds
        if warmup_seconds < required_warmup:
            raise ValueError(f'Warmup must cover model context and full HR history: >= {required_warmup:.3f} seconds')
        if workers < 1 or segment_seconds <= 0:
            raise ValueError('Workers and segment duration must be positive')
        if warmup_seconds < 16.0 or lookahead_seconds < self.config.pulse_window_frames / self.config.pulse_fps:
            raise ValueError('Require >=16.0 s warmup and a complete model window of lookahead')
        self.workers = int(workers)
        self.gpu_ids = tuple(gpu_ids)
        self.device = device
        self.segment_seconds = float(segment_seconds)
        self.warmup_seconds = float(warmup_seconds)
        self.lookahead_seconds = float(lookahead_seconds)

    def extract(self, video_path, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        helper_sha256 = _stream_sha256(Path(__file__))
        implementation_sha256 = _implementation_sha256()
        model_sha256 = {name: _stream_sha256(getattr(self.config, name))
                        for name in ('face_model', 'pose_model', 'rppg_weights')}
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            os.environ[name] = str(self.config.torch_threads)
        with tempfile.TemporaryDirectory(prefix='.parallel-video-', dir=output_dir) as temporary:
            temp = Path(temporary)
            indexed = temp / 'indexed.mkv'
            remux_started = time.perf_counter()
            command = ['ffmpeg', '-v', 'error', '-nostdin', '-copyts', '-i', str(video_path),
                       '-map', '0:v:0', '-c', 'copy', '-avoid_negative_ts', 'disabled', '-y', str(indexed)]
            remux = subprocess.run(command, capture_output=True, text=True)
            if remux.returncode:
                raise RuntimeError('Indexed remux failed: ' + remux.stderr[-4000:])
            remux_seconds = time.perf_counter() - remux_started
            source_sha256 = _stream_sha256(video_path)
            metadata = _packet_metadata(indexed, self.config.max_seconds)
            source_metadata = _packet_metadata(video_path, self.config.max_seconds)
            if metadata['packet_pts_keyframes_sha256'] != source_metadata['packet_pts_keyframes_sha256']:
                raise ValueError('Indexed remux changed source packet PTS, ordering, or keyframe flags')
            parts = _segments(metadata, self.segment_seconds, self.warmup_seconds,
                              self.lookahead_seconds, self.config)
            devices = [f'cuda:{i}' for i in self.gpu_ids] if not str(self.device).startswith('cpu') else ['cpu']
            actual_workers = min(self.workers, len(parts))
            results = []
            context = multiprocessing.get_context('spawn')
            with ProcessPoolExecutor(max_workers=actual_workers, mp_context=context) as executor:
                pending = {}
                for spec in parts:
                    folder = temp / f"part-{spec['part_id']:04d}"
                    device = devices[spec['part_id'] % len(devices)]
                    future = executor.submit(_segment_worker, str(indexed), str(folder), device,
                                             asdict(self.config), spec)
                    pending[future] = spec
                for future in as_completed(pending):
                    result = future.result()
                    results.append(result)
                    print(json.dumps({'parallel_part_complete':result['spec']['part_id'],
                                      'parts':len(parts), 'device':result['device'],
                                      'core_seconds':result['spec']['core_end_seconds'] - result['spec']['core_start_seconds']}), flush=True)
            merge_started = time.perf_counter()
            validation = {}
            counts = _merge_parts(results, output_dir, metadata, self.config, validation=validation)
            elapsed = time.perf_counter() - started
            first = results[0]['summary']
            actual_fps = (counts['decoded_frames'] - 1) / metadata['duration_seconds'] if metadata['duration_seconds'] else None
            summary = {key: value for key, value in first.items() if key not in {'config', 'video_source'}}
            summary.update(counts)
            summary.update(schema_version=1, video_source=str(video_path), source_video_sha256=source_sha256,
                           pts_start_seconds=metadata['pts_start_seconds'], pts_end_seconds=metadata['pts_end_seconds'],
                           first_pts=round(metadata['pts_start_seconds'] * 1_000_000),
                           last_pts=round(metadata['pts_end_seconds'] * 1_000_000),
                           summary_pts_time_base_numerator=1, summary_pts_time_base_denominator=1_000_000,
                           duration_seconds=metadata['duration_seconds'], nominal_fps=metadata['nominal_fps'],
                           actual_fps=actual_fps, width=metadata['width'], height=metadata['height'],
                           wall_seconds=elapsed, video_seconds_per_wall_second=metadata['duration_seconds']/elapsed,
                           decoded_frames_per_second=counts['decoded_frames']/elapsed,
                           parallel_workers=actual_workers, parallel_devices=devices,
                           indexed_remux_seconds=remux_seconds, parallel_merge_seconds=time.perf_counter()-merge_started,
                           source_packet_duplicate_pts=metadata['packet_duplicate_pts'],
                           source_packet_pts_keyframes_sha256=metadata['packet_pts_keyframes_sha256'],
                           indexed_remux_pts_verified=True,
                           pulse_sampling_fps=self.config.pulse_fps, pulse_device='multiple CUDA devices' if devices != ['cpu'] else 'cpu',
                           device='parallel:' + ','.join(devices), truncated=self.config.max_seconds is not None,
                           parallel_extractor_sha256=helper_sha256,
                           preprocessing_implementation_sha256=implementation_sha256,
                           face_model_sha256=model_sha256['face_model'],
                           pose_model_sha256=model_sha256['pose_model'],
                           rppg_weights_sha256=model_sha256['rppg_weights'],
                           config=asdict(self.config),
                           parallel_provenance={
                               'method':'indexed MKV remux with copyts; disjoint real-frame cores; stride-aligned 30Hz grid',
                               'requested_core_seconds':self.segment_seconds,
                               'effective_core_seconds':parts[0]['core_end_seconds'] - parts[0]['core_start_seconds'],
                               'warmup_seconds':self.warmup_seconds, 'lookahead_seconds':self.lookahead_seconds,
                               'history_continuous_across_parts':False,
                               'pulse_value_boundary_mask':'first pulse_value of parts after0 is null to prevent scalar interpolation across independent integral baselines',
                               'pulse_value_amplitude':'relative per-part integral; globally unique pulse_segment_id; do not combine parts for HRV',
                               'tracker_state':'MediaPipe tracker reinitialized for each part with warmup; coordinates may differ from a full single pass',
                               'bpm_refresh_phase':'independent per-part 0.5s update cache after warmup',
                               'synthetic_anchor':'exact timestamp anchor only in warmup; all exported core feature PTS verified against real source packets',
                               'parts':[{'spec':p['spec'], 'window_stats':p['window_stats'], 'device':p['device'],
                                         'wall_seconds':p['summary']['wall_seconds'],
                                         'pulse_inference_seconds':p['summary']['pulse_inference_seconds']} for p in sorted(results,key=lambda p:p['spec']['part_id'])]})
            for key in ('pulse_inference_seconds', 'pulse_inference_batches', 'decode_seconds', 'landmarks_seconds',
                        'crop_resample_seconds', 'pulse_postprocess_seconds'):
                summary[key] = sum(p['summary'].get(key, 0) for p in results)
            summary['gpu_max_memory_allocated_bytes'] = max(p['summary'].get('gpu_max_memory_allocated_bytes',0) for p in results)
            if _implementation_sha256() != implementation_sha256:
                raise RuntimeError('Preprocessing implementation changed during parallel extraction')
            if any(_stream_sha256(getattr(self.config, name)) != value for name, value in model_sha256.items()):
                raise RuntimeError('Model assets changed during parallel extraction')
            validation.update(source_index_packetPTS_verified=True,
                              source_video_sha256=source_sha256,
                              source_packet_pts_keyframes_sha256=metadata['packet_pts_keyframes_sha256'],
                              wall_seconds=elapsed, duration_seconds=metadata['duration_seconds'],
                              realtime_speed=summary['video_seconds_per_wall_second'],
                              parallel_extractor_sha256=summary['parallel_extractor_sha256'],
                              preprocessing_implementation_sha256=implementation_sha256,
                              face_model_sha256=model_sha256['face_model'],
                              pose_model_sha256=model_sha256['pose_model'],
                              rppg_weights_sha256=model_sha256['rppg_weights'])
            (output_dir / 'video_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
            validation['cache_artifacts_sha256'] = _cache_artifacts_sha256(output_dir)
            (output_dir / 'parallel_validation.json').write_text(json.dumps(validation, indent=2, allow_nan=False)+'\n', encoding='utf-8')
            return summary


if __name__ == '__main__':
    import argparse
    from preprocessing.vision import VisionConfig
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--segment-seconds', type=float, default=307.2)
    parser.add_argument('--max-seconds', type=float)
    args = parser.parse_args()
    result = ParallelVisionExtractor(config=VisionConfig(max_seconds=args.max_seconds), workers=args.workers,
                                     segment_seconds=args.segment_seconds).extract(args.video, args.output)
    print(json.dumps({key:value for key,value in result.items() if key not in {'config','parallel_provenance'}},indent=2))
