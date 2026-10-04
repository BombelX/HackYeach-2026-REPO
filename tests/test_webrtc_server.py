import asyncio
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
import numpy as np
import torch

from camera_estimator import LandmarkDetector
from webrtc_server import Processor, create_app, measurement_output, parse_args


class ProcessorTests(unittest.TestCase):
    def test_measurement_output_has_a_stable_contract(self):
        result = measurement_output('camera-123', status='error', error='worker failed')
        self.assertEqual(result['session_id'], 'camera-123')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'worker failed')
        self.assertIsNone(result['heart_rate_bpm'])
        self.assertFalse(result['heart_rate_stale'])
        self.assertFalse(result['face_detected'])
        self.assertIsNone(result['landmarks'])
        self.assertIsNone(result['frame_width'])
        self.assertIsNone(result['frame_height'])

    def test_landmark_overlay_uses_cyan_points(self):
        detector = LandmarkDetector.__new__(LandmarkDetector)
        detector.points = {
            'pose': [{'index': 0, 'x': 0.5, 'y': 0.5, 'z': 0.0}],
            'face': [{'index': 0, 'x': 0.25, 'y': 0.25, 'z': 0.0}],
        }
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        detector.draw(frame)
        self.assertTrue(np.any(np.all(frame == (255, 255, 0), axis=2)))

    @unittest.skipUnless(
        (Path(__file__).resolve().parents[1] / 'rPPG-Toolbox/neural_methods/model/PhysNet.py').is_file()
        and (Path(__file__).resolve().parents[1] / 'rPPG-Toolbox/final_model_release/UBFC-rPPG_PhysNet_DiffNormalized.pth').is_file(),
        'PhysNet source and checkpoint are absent; transport tests still run',
    )
    def test_physnet_inference_and_reset(self):
        args = parse_args(['--no-analysis', '--device', 'cpu'])
        torch.set_num_threads(2)
        processor = Processor(args)
        try:
            rng = np.random.default_rng(42)
            self.assertGreaterEqual(processor.frames.maxlen, 152)
            for i in range(160):
                processor.frames.append(rng.integers(40, 200, (72, 72, 3), dtype=np.uint8))
                processor.times.append(i / 30)
            processor.infer()
            self.assertAlmostEqual(processor.fs, 30)
            self.assertTrue(processor.history)
            self.assertIsNotNone(processor.bpm)
            reading = processor.bpm
            processor.reset()
            self.assertEqual(processor.bpm, reading)
            self.assertTrue(processor.bpm_stale)
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
        self.assertFalse(result['heart_rate_stale'])
        self.assertIsNone(result['heart_rate_updated_at'])
        self.assertIsNone(result['landmarks'])
        self.assertIsNone(result['landmarks_timestamp_ms'])
        self.assertEqual((result['frame_width'], result['frame_height']), (640, 480))
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
