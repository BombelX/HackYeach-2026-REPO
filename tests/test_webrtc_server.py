import asyncio
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
import json

from camera_estimator import LandmarkDetector

from aiohttp.test_utils import TestClient, TestServer
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
import numpy as np
import torch

from webrtc_server import Processor, create_app, parse_args


class ProcessorTests(unittest.TestCase):
    def test_landmarks_json_without_classification(self):
        points = LandmarkDetector.serialize([
            SimpleNamespace(x=0.5, y=0.25, z=-0.1, visibility=0.9, presence=None)])
        self.assertEqual(points, [dict(index=0, x=0.5, y=0.25, z=-0.1, visibility=0.9)])
        processor = Processor(parse_args(['--preview-only', '--no-analysis']))
        processor.analyzer = Mock()
        processor.analyzer.points = {'pose': points, 'face': []}
        processor.analyzer.timestamp_ms = 1000
        processor.count = 1
        try:
            _, result = processor.process(np.zeros((240, 320, 3), dtype=np.uint8), 1)
            self.assertEqual(result['landmarks']['pose'], points)
            self.assertEqual(result['landmarks']['face'], [])
            self.assertEqual(result['landmarks_timestamp_ms'], 1000)
            self.assertEqual(result['frame_width'], 320)
            self.assertNotIn('posture', result)
            self.assertNotIn('expression', result)
            json.dumps(result)
        finally:
            processor.close()

    def test_half_second_updates_preserve_frames_across_gaps(self):
        args = parse_args(['--preview-only', '--no-analysis'])
        processor = Processor(args)
        processor.model = object()
        processor.detector = Mock()
        processor.detector.detectMultiScale.return_value = [(80, 80, 100, 100)]
        windows = []
        processor.infer = lambda: windows.append(list(processor.times))
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        try:
            for i in range(140):
                processor.process(frame.copy(), 1 + i / 30)
            self.assertEqual(len(windows), 8)
            self.assertEqual(len(windows[0]), args.min_frames)
            self.assertEqual(len(windows[-1]), 128)
            for i, window in enumerate(windows):
                self.assertAlmostEqual(window[-1], 1 + (31 + i * 15) / 30)
                if i:
                    self.assertAlmostEqual(window[-1] - windows[i - 1][-1], 0.5)
            previous_times = list(processor.times)
            processor.history = [(1.0, 0.25)]
            processor.process(frame.copy(), previous_times[-1] + 0.4)
            self.assertEqual(list(processor.times)[:-1], previous_times[1:])
            self.assertEqual(processor.history, [(1.0, 0.25)])
            self.assertEqual(len(windows), 9)
        finally:
            processor.close()

    def test_physnet_inference_and_reset(self):
        args = parse_args(['--no-analysis', '--device', 'cpu'])
        torch.set_num_threads(2)
        processor = Processor(args)
        try:
            rng = np.random.default_rng(42)
            for i in range(32):
                processor.frames.append(rng.integers(40, 200, (72, 72, 3), dtype=np.uint8))
                processor.times.append(i / 30)
            processor.infer()
            self.assertAlmostEqual(processor.fs, 30)
            self.assertTrue(processor.history)
            self.assertIsNone(processor.bpm)  # One second is still warming up.
            # Keep publishing the previous measured value during reacquisition.
            processor.bpm = processor.prior = 72.0
            processor.bpm_updated_at = 123.0
            processor.infer()  # Insufficient history must not erase the reading.
            self.assertEqual(processor.bpm, 72.0)
            self.assertTrue(processor.bpm_stale)
            self.assertIsNone(processor.prior)
            processor.reset()
            self.assertEqual(processor.bpm, 72.0)
            processor.target = None
            processor.count = 1  # Avoid running the detector on the blank test frame.
            _, result = processor.process(np.zeros((480, 640, 3), dtype=np.uint8), 10)
            self.assertEqual(result['heart_rate_bpm'], 72.0)
            self.assertTrue(result['heart_rate_stale'])
            self.assertEqual(result['heart_rate_updated_at'], 123.0)
            self.assertEqual(result['status'], 'stale')
            self.assertEqual(processor.history, [])
        finally:
            processor.close()


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        args = parse_args(['--preview-only', '--no-analysis', '--max-sessions', '1'])
        self.client = TestClient(TestServer(create_app(args)))
        await self.client.start_server()
        self.peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))

    async def asyncTearDown(self):
        await self.peer.close()
        await self.client.close()

    async def test_bad_input(self):
        for body in ({}, {'type': 'answer', 'sdp': ''}, [], {'type':'offer', 'sdp':'invalid'}):
            response = await self.client.post('/api/webrtc/offer', json=body)
            self.assertEqual(response.status, 400)
        response = await self.client.get('/health')
        self.assertEqual((await response.json())['sessions'], 0)
        response = await self.client.get('/api/sessions/missing/output')
        self.assertEqual(response.status, 404)

    async def test_media_output_events_and_cleanup(self):
        received = asyncio.get_running_loop().create_future()
        @self.peer.on('track')
        def on_track(track):
            received.set_result(track)
        self.peer.addTrack(VideoStreamTrack())
        await self.peer.setLocalDescription(await self.peer.createOffer())
        response = await self.client.post('/api/webrtc/offer', json={
            'sdp':self.peer.localDescription.sdp, 'type':'offer'})
        self.assertEqual(response.status, 200, await response.text())
        answer = await response.json()
        await self.peer.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
        track = await asyncio.wait_for(received, 10)
        frame = await asyncio.wait_for(track.recv(), 15)
        self.assertEqual((frame.width, frame.height), (640, 480))
        ws = await self.client.ws_connect(answer['events_url'])
        result = await ws.receive_json(timeout=5)
        self.assertEqual(result['status'], 'preview')
        self.assertIsNone(result['heart_rate_bpm'])
        result = await (await self.client.get(answer['output_url'])).json()
        self.assertEqual(result['session_id'], answer['session_id'])
        response = await self.client.post('/api/webrtc/offer', json={'sdp':self.peer.localDescription.sdp, 'type':'offer'})
        self.assertEqual(response.status, 503)
        response = await self.client.delete('/api/sessions/' + answer['session_id'])
        self.assertEqual(response.status, 204)
        response = await self.client.get(answer['output_url'])
        self.assertEqual(response.status, 404)
        await ws.close()
        self.assertEqual((await (await self.client.get('/health')).json())['sessions'], 0)

    async def test_sendonly_input_still_produces_results(self):
        self.peer.addTransceiver(VideoStreamTrack(), direction='sendonly')
        await self.peer.setLocalDescription(await self.peer.createOffer())
        response = await self.client.post('/api/webrtc/offer', json={
            'sdp': self.peer.localDescription.sdp, 'type': 'offer'})
        self.assertEqual(response.status, 200)
        answer = await response.json()
        await self.peer.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type='answer'))
        ws = await self.client.ws_connect(answer['events_url'])
        while True:
            result = await ws.receive_json(timeout=10)
            if result['status'] != 'waiting':
                break
        self.assertEqual(result['status'], 'preview')
        await ws.close()
        await self.client.delete('/api/sessions/' + answer['session_id'])
