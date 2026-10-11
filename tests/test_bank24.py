import asyncio
"""Integration tests of actual bank API; no mocked ledger or authentication."""
import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web
import cv2
import numpy as np
from bank24_server import create_app, digest, password_hash, RECIPIENT, Store
from webrtc_server import create_app as create_camera_app, parse_args as camera_args


class CameraProfileMigrationTest(unittest.TestCase):
    def test_old_samples_and_versions_are_not_trusted_by_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bank.sqlite'
            old = sqlite3.connect(path)
            old.executescript('''
                CREATE TABLE participants(id TEXT PRIMARY KEY,code_hash TEXT,username TEXT,salt TEXT,password TEXT,balance INTEGER);
                INSERT INTO participants VALUES('p',NULL,'owner','','',0);
                CREATE TABLE camera_profile_samples(participant TEXT,bank_session TEXT,profile BLOB,created_at REAL,
                    PRIMARY KEY(participant,bank_session));
                INSERT INTO camera_profile_samples VALUES('p','s',X'00',1);
                CREATE TABLE camera_profile_versions(participant TEXT,version INTEGER,model_version TEXT,
                    sample_count INTEGER,profile BLOB,created_at REAL,PRIMARY KEY(participant,version));
                INSERT INTO camera_profile_versions VALUES('p',1,'old',3,X'00',1);
            ''')
            old.close()
            migrated = Store(path)
            self.assertEqual(migrated.one('SELECT approved FROM camera_profile_samples')['approved'], 0)
            self.assertEqual(migrated.one('SELECT trusted FROM camera_profile_versions')['trusted'], 0)
            migrated.db.close()


class BankTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'bank.sqlite'
        self.app = create_app(self.path, demo=True)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.csrf = ''
        response = await self.call('/bootstrap', {})
        self.csrf = response['csrf']

    async def asyncTearDown(self):
        await self.client.close()

    async def request(self, path, body=None, method='POST', extra=None):
        return await self.client.request(method, '/api' + path, json=body, headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': self.csrf, **(extra or {})})

    async def call(self, path, body=None, method='POST', expected=200, extra=None):
        response = await self.request(path, body, method, extra)
        result = await response.json()
        self.assertEqual(response.status, expected, result)
        return result

    async def authenticate(self, telemetry=False, remember=False):
        await self.call('/session/permissions', {'telemetry': telemetry})
        challenge = await self.call('/bank/login', {'username': 'anna.demo', 'password': 'bank24', 'remember': remember})
        self.assertEqual(challenge['code_length'], 4)
        result = await self.call('/bank/verify', {'challenge_id': challenge['challenge_id'], 'code': '1234'})
        self.csrf = result['csrf']

    async def test_camera_frames_require_consent_and_return_real_worker_output(self):
        worker = TestClient(TestServer(create_camera_app(camera_args(['--preview-only', '--no-analysis']))))
        await worker.start_server()
        bank = TestClient(TestServer(create_app(Path(self.directory.name) / 'camera.sqlite', demo=True,
                                                camera_url=str(worker.make_url('/')).rstrip('/'))))
        await bank.start_server()
        try:
            async def post(path, headers, **kwargs):
                return await bank.post('/api' + path, headers={'Origin': 'http://localhost:5173', **headers}, **kwargs)

            boot = await (await post('/bootstrap', {}, json={})).json()
            headers = {'X-CSRF-Token': boot['csrf']}
            self.assertEqual((await post('/frames/sessions', headers)).status, 401)
            challenge = await (await post('/bank/login', headers, json={'username': 'anna.demo', 'password': 'bank24'})).json()
            verified = await (await post('/bank/verify', headers, json={'challenge_id': challenge['challenge_id'], 'code': '1234'})).json()
            headers = {'X-CSRF-Token': verified['csrf']}
            # Camera consent is granted at login: the camera runs for the whole signed-in session.
            self.assertTrue((await (await post('/session/permissions', headers, json={})).json())['camera'])
            self.assertEqual((await post('/session/permissions', headers, json={'camera': False})).status, 200)
            self.assertEqual((await post('/frames/sessions', headers)).status, 403)
            self.assertEqual((await post('/session/permissions', headers, json={'camera': True})).status, 200)
            response = await post('/frames/sessions', headers)
            self.assertEqual(response.status, 200, await response.text())
            camera_id = (await response.json())['session_id']
            frame = '/frames/sessions/' + camera_id + '/frame'
            self.assertEqual((await post(frame, headers, data=b'not-jpeg')).status, 415)
            ok, jpeg = cv2.imencode('.jpg', np.zeros((480, 640, 3), np.uint8))
            self.assertTrue(ok)
            response = await post(frame, {**headers, 'Content-Type': 'image/jpeg'}, data=jpeg.tobytes())
            self.assertEqual(response.status, 200, await response.text())
            self.assertEqual((await response.json())['measurement']['frame_width'], 640)
            self.assertEqual((await post('/session/permissions', headers, json={'camera': False})).status, 200)
            self.assertEqual((await post(frame, {**headers, 'Content-Type': 'image/jpeg'}, data=jpeg.tobytes())).status, 403)
            self.assertEqual((await (await worker.get('/health')).json())['sessions'], 0)
        finally:
            await bank.close()
            await worker.close()

    async def risk_bank(self, name, **options):
        worker = TestClient(TestServer(create_camera_app(camera_args(['--preview-only', '--no-analysis']))))
        await worker.start_server()
        repo = Path(self.directory.name) / 'fusion'
        (repo / 'training').mkdir(parents=True, exist_ok=True)
        (repo / 'training/inference_xgb_suspicious.py').write_text('')
        bank = TestClient(TestServer(create_app(Path(self.directory.name) / name, demo=True, fusion_repo=repo,
                                                camera_url=str(worker.make_url('/')).rstrip('/'), **options)))
        await bank.start_server()

        async def post(path, headers, **kwargs):
            return await bank.post('/api' + path, headers={'Origin': 'http://localhost:5173', **headers}, **kwargs)

        async def sign_in(code):
            boot = await (await post('/bootstrap', {}, json={})).json()
            challenge = await (await post('/bank/login', {'X-CSRF-Token': boot['csrf']}, json={'username': 'anna.demo', 'password': 'bank24'})).json()
            verified = await (await post('/bank/verify', {'X-CSRF-Token': boot['csrf']}, json={'challenge_id': challenge['challenge_id'], 'code': code})).json()
            return {'X-CSRF-Token': verified['csrf']}
        return worker, bank, post, sign_in

    async def profile_bank(self, name, admin_token=None):
        worker_app = web.Application()
        async def trace_response(_):
            return web.json_response({'samples': [{'t': 0}]})

        async def close_response(_):
            return web.json_response({})

        worker_app.router.add_get('/api/sessions/{id}/trace', trace_response)
        worker_app.router.add_delete('/api/sessions/{id}', close_response)
        worker = TestClient(TestServer(worker_app))
        await worker.start_server()
        repo = Path(self.directory.name) / 'fusion'
        (repo / 'training').mkdir(parents=True, exist_ok=True)
        (repo / 'training/inference_xgb_suspicious.py').write_text('')
        path = Path(self.directory.name) / name
        bank = TestClient(TestServer(create_app(path, demo=True, fusion_repo=repo, admin_token=admin_token,
                                                camera_url=str(worker.make_url('/')).rstrip('/'))))
        await bank.start_server()

        async def post(path, headers, **kwargs):
            return await bank.post('/api' + path, headers={'Origin': 'http://localhost:5173', **headers}, **kwargs)

        async def sign_in(code):
            boot = await (await post('/bootstrap', {}, json={})).json()
            challenge = await (await post('/bank/login', {'X-CSRF-Token': boot['csrf']},
                                          json={'username': 'anna.demo', 'password': 'bank24'})).json()
            verified = await (await post('/bank/verify', {'X-CSRF-Token': boot['csrf']},
                                         json={'challenge_id': challenge['challenge_id'], 'code': code})).json()
            store = bank.app['store']
            session = store.one('SELECT id FROM sessions WHERE authenticated=1 ORDER BY rowid DESC LIMIT 1')
            store.db.execute('INSERT INTO cameras(id,session) VALUES(?,?)', ('camera-' + session['id'], session['id']))
            return {'X-CSRF-Token': verified['csrf']}

        return worker, bank, post, sign_in

    async def test_unvalidated_camera_mismatch_requests_review_without_logout(self):
        worker, bank, post, sign_in = await self.profile_bank('mismatch.sqlite')
        sample = SimpleNamespace(participant='demo-owner', session_id='enrol')
        store = bank.app['store']
        store.db.execute('INSERT INTO camera_profile_versions(participant,version,model_version,sample_count,profile,created_at,trusted) VALUES(?,?,?,?,?,?,1)',
                         ('demo-owner', 1, 'test', 3, __import__('pickle').dumps(sample), time.time()))
        model = dict(p_not_owner=0.1, p_pressure=0.02, review_required=False, review_score=0.05,
                     review_threshold=0.13, probe_seconds=30, profile_enrolled_now=False)
        try:
            headers = await sign_in('1234')
            check = await post('/bank/risk-check', headers, json={})
            self.assertEqual((await check.json())['status'], 'insufficient_data')
            with mock.patch('bank24_camera_risk.load_profile', return_value=sample), \
                    mock.patch('bank24_camera_risk.assess_camera', return_value=model):
                check = await post('/bank/risk-check', headers, json={})
                self.assertEqual((await check.json())['account_takeover_risk'], 10)
                transfer = await post('/bank/transfers', headers, json={'recipient': 'North Studio sp. z o.o.', 'number': RECIPIENT,
                                                                        'title': 'Invoice', 'amount_grosz': 1000})
                self.assertEqual(transfer.status, 201)
                transfer_id = (await transfer.json())['id']
                model['p_not_owner'] = 0.85
                check = await post('/bank/risk-check', headers, json={})
                body = await check.json()
            self.assertEqual((check.status, body['account_takeover_risk']), (200, 85))
            self.assertEqual((await bank.get('/api/bank/account')).status, 200)
            row = store.one('SELECT status FROM transfers WHERE id=?', (transfer_id,))
            self.assertEqual(row['status'], 'review')
        finally:
            await bank.close()
            await worker.close()

    async def test_camera_profile_requires_three_explicit_verified_sessions(self):
        worker, bank, post, sign_in = await self.profile_bank('enrollment.sqlite', admin_token='operator-secret')
        sample = SimpleNamespace(participant='demo-owner', session_id='enrol')
        safe_score = dict(p_not_owner=0.04, p_pressure=0.02, review_required=False,
                          review_score=0.03, review_threshold=0.13, probe_seconds=30,
                          profile_enrolled_now=False)
        try:
            with mock.patch('bank24_camera_risk.build_enrollment_sample', return_value=sample), \
                    mock.patch('bank24_camera_risk.combine_samples', return_value=sample), \
                    mock.patch('bank24_camera_risk.load_profile', return_value=sample), \
                    mock.patch('bank24_camera_risk.assess_camera', return_value=safe_score):
                for n in range(1, 5):
                    headers = await sign_in('1234')
                    status = await (await bank.get('/api/bank/camera-profile')).json()
                    self.assertEqual(status['samples'], n - 1)
                    self.assertEqual(status['version'], None if n < 4 else 1)
                    self.assertFalse(status['activates_next_sign_in'])
                    check = await post('/bank/risk-check', headers, json={})
                    if n < 4:
                        self.assertEqual((await check.json())['status'], 'insufficient_data')
                    missing_start = await post('/bank/camera-profile/enroll', headers, json={'confirm_calm': True})
                    self.assertEqual((missing_start.status, (await missing_start.json())['code']),
                                     (409, 'enrolment_not_started'))
                    started = await post('/bank/camera-profile/enroll/start', headers, json={'confirm_calm': True})
                    self.assertEqual(started.status, 200)
                    self.assertIsNotNone((await started.json())['started_at'])
                    response = await post('/bank/camera-profile/enroll', headers, json={'confirm_calm': True})
                    result = await response.json()
                    self.assertEqual(response.status, 200, result)
                    self.assertEqual(result['samples'], min(n, 3))
                    self.assertEqual(result['version'], None if n < 3 else 1)
                    self.assertTrue(result['recorded_this_session'])
                    self.assertEqual(result['activates_next_sign_in'], n == 3)
                    if n == 4:
                        self.assertEqual(result['pending'], 1)
                        candidates = await bank.get('/api/admin/camera-profile/candidates', headers={
                            'Authorization': 'Bearer operator-secret'})
                        self.assertEqual(candidates.status, 200)
                        candidate = (await candidates.json())['items'][0]
                        denied = await bank.post('/api/admin/camera-profile/candidates/' + candidate['bank_session'] + '/approve',
                                                 headers={'Origin': 'http://localhost:5173',
                                                          'Authorization': 'Bearer operator-secret'},
                                                 json={'verified': False})
                        self.assertEqual(denied.status, 422)
                        approved = await bank.post('/api/admin/camera-profile/candidates/' + candidate['bank_session'] + '/approve',
                                                   headers={'Origin': 'http://localhost:5173',
                                                            'Authorization': 'Bearer operator-secret'},
                                                   json={'verified': True})
                        approved_body = await approved.json()
                        self.assertEqual((approved.status, approved_body['version'], approved_body['samples']), (200, 2, 4))
                        self.assertTrue(approved_body['activates_next_sign_in'])
                    if n >= 3:
                        check = await post('/bank/risk-check', headers, json={})
                        checked = await check.json()
                        if n == 3:
                            self.assertEqual(checked['status'], 'insufficient_data')
                        else:
                            self.assertEqual(checked['account_takeover_risk'], 4)
                    duplicate = await post('/bank/camera-profile/enroll', headers, json={'confirm_calm': True})
                    self.assertEqual((duplicate.status, (await duplicate.json())['code']), (409, 'sample_exists'))
                    await post('/bank/logout', headers, json={})
            store = Store(Path(self.directory.name) / 'enrollment.sqlite')
            self.addCleanup(store.db.close)
            versions = store.db.execute('SELECT version,sample_count FROM camera_profile_versions ORDER BY version').fetchall()
            self.assertEqual([(row['version'], row['sample_count']) for row in versions], [(1, 3), (2, 4)])
            legacy = Path(self.directory.name) / 'camera_profiles' / 'demo-owner.pkl'
            legacy.parent.mkdir()
            legacy.write_bytes(b'legacy')
            headers = await sign_in('1234')
            removed = await bank.delete('/api/bank/camera-profile', headers={
                'Origin': 'http://localhost:5173', **headers})
            self.assertEqual((removed.status, (await removed.json())['samples']), (200, 0))
            self.assertEqual(store.one('SELECT COUNT(*) n FROM camera_profile_versions')['n'], 0)
            self.assertFalse(legacy.exists())
        finally:
            await bank.close()
            await worker.close()

    async def test_camera_profile_rejects_alarm_and_queues_updates(self):
        worker, bank, post, sign_in = await self.profile_bank('untrusted.sqlite', admin_token='operator-secret')
        try:
            headers = await sign_in('4321')
            denied = await post('/bank/camera-profile/enroll', headers, json={'confirm_calm': True})
            self.assertEqual((denied.status, (await denied.json())['code']), (403, 'untrusted_session'))
            await post('/bank/logout', headers, json={})
            store = Store(Path(self.directory.name) / 'untrusted.sqlite')
            self.addCleanup(store.db.close)
            sample = SimpleNamespace(participant='demo-owner', session_id='enrol')
            store.db.execute('INSERT INTO camera_profile_versions(participant,version,model_version,sample_count,profile,created_at,trusted) VALUES(?,?,?,?,?,?,1)',
                             ('demo-owner', 1, 'test', 3, __import__('pickle').dumps(sample), time.time()))
            headers = await sign_in('1234')
            started = await post('/bank/camera-profile/enroll/start', headers, json={'confirm_calm': True})
            self.assertEqual(started.status, 200)
            with mock.patch('bank24_camera_risk.build_enrollment_sample', return_value=sample):
                queued = await post('/bank/camera-profile/enroll', headers, json={'confirm_calm': True})
            self.assertEqual(queued.status, 200)
            self.assertEqual((await queued.json())['pending'], 1)
            self.assertEqual(store.one('SELECT MAX(version) n FROM camera_profile_versions')['n'], 1)
            score = dict(p_not_owner=0.8, p_pressure=0.02, review_required=True,
                         review_score=0.8, review_threshold=0.13, probe_seconds=40,
                         profile_enrolled_now=False)
            with mock.patch('bank24_camera_risk.load_profile', return_value=sample), \
                    mock.patch('bank24_camera_risk.assess_camera', return_value=score):
                checked = await post('/bank/risk-check', headers, json={})
            self.assertEqual((checked.status, (await checked.json())['account_takeover_risk']), (200, 80))
        finally:
            await bank.close()
            await worker.close()

    async def test_alarm_code_forces_high_mismatch_and_logout(self):
        worker, bank, post, sign_in = await self.risk_bank('alarm.sqlite', alarm_delay=0.5)
        try:
            headers = await sign_in('4321')
            self.assertEqual((await bank.get('/api/bank/account')).status, 200)
            check = await post('/bank/risk-check', headers, json={})
            body = await check.json()
            self.assertEqual(check.status, 200)
            self.assertGreater(body['retry_after'], 0)
            await asyncio.sleep(0.6)
            check = await post('/bank/risk-check', headers, json={})
            body = await check.json()
            self.assertEqual((check.status, body['code']), (403, 'anomaly_detected'))
            self.assertGreaterEqual(body['account_takeover_risk'], 90)
            self.assertEqual((await bank.get('/api/bank/account')).status, 401)
            headers = await sign_in('1234')
            check = await post('/bank/risk-check', headers, json={})
            self.assertEqual((check.status, (await check.json())['status']), (200, 'insufficient_data'))
        finally:
            await bank.close()
            await worker.close()

    async def test_alarm_code_holds_transfer_until_delayed_logout(self):
        worker, bank, post, sign_in = await self.risk_bank('alarm-transfer.sqlite', alarm_delay=0.5)
        try:
            headers = await sign_in('1234')
            transfer = await (await post('/bank/transfers', headers, json={'recipient': 'North Studio sp. z o.o.', 'number': RECIPIENT,
                                                                            'title': 'Invoice', 'amount_grosz': 1000})).json()
            path = '/bank/transfers/' + transfer['id']
            await post(path + '/intervention', headers, json={'version': transfer['version'], 'independent': True, 'compared': True})
            challenge = await (await post(path + '/challenge', headers, json={})).json()
            held = await post(path + '/submit', {**headers, 'Idempotency-Key': 'alarm-operation-key-1'},
                              json={'challenge_id': challenge['challenge_id'], 'code': '4321', 'version': transfer['version']})
            self.assertEqual((held.status, (await held.json())['code']), (409, 'transfer_held'))
            self.assertEqual((await bank.get('/api/bank/account')).status, 200)
            await asyncio.sleep(0.6)
            check = await post('/bank/risk-check', headers, json={})
            self.assertEqual((check.status, (await check.json())['code']), (403, 'anomaly_detected'))
            store = Store(Path(self.directory.name) / 'alarm-transfer.sqlite')
            self.addCleanup(store.db.close)
            self.assertEqual(store.one('SELECT status FROM transfers WHERE id=?', (transfer['id'],))['status'], 'cancelled')
            self.assertEqual(store.one('SELECT balance FROM participants WHERE username=?', ('anna.demo',))['balance'], 1842050)
        finally:
            await bank.close()
            await worker.close()

    async def preview(self, amount=125000):
        return await self.call('/bank/transfers', {'recipient': 'North Studio sp. z o.o.', 'number': RECIPIENT, 'title': 'Invoice FV/2026/104', 'amount_grosz': amount}, expected=201)

    async def ready(self, transfer):
        await self.call('/bank/transfers/' + transfer['id'] + '/intervention', {'version': transfer['version'], 'independent': True, 'compared': True})
        return await self.call('/bank/transfers/' + transfer['id'] + '/challenge', {})

    async def test_full_flow_once_only_and_persistence(self):
        await self.authenticate(remember=True)
        account = await self.call('/bank/account', method='GET')
        self.assertTrue(account['trusted_device'])
        transfer = await self.preview()
        self.assertIsNone(transfer['risk']['account_takeover_risk'])
        self.assertIsNone(transfer['risk']['coercion_risk'])
        challenge = await self.ready(transfer)
        data = dict(challenge_id=challenge['challenge_id'], code='1234', version=1)
        endpoint = '/bank/transfers/' + transfer['id'] + '/submit'
        first = await self.call(endpoint, data, extra={'Idempotency-Key': 'test-operation-key-1'})
        second = await self.call(endpoint, data, extra={'Idempotency-Key': 'test-operation-key-2'})
        self.assertEqual(first['status'], second['status'])
        account = await self.call('/bank/account', method='GET')
        self.assertEqual(account['balance_grosz'], 1717050)
        ledger = await self.call('/bank/transactions', method='GET')
        self.assertEqual(sum(item['id'] == transfer['id'] for item in ledger['items']), 1)
        other_store = Store(self.path)
        self.assertEqual(other_store.one('SELECT status FROM transfers WHERE id=?', (transfer['id'],))['status'], 'completed')
        other_store.db.close()
        await self.call('/bank/device', method='DELETE')
        self.assertFalse((await self.call('/bank/account', method='GET'))['trusted_device'])

    async def test_cannot_skip_review_or_override_hold(self):
        await self.authenticate()
        transfer = await self.preview()
        await self.call('/bank/transfers/' + transfer['id'] + '/challenge', {}, expected=409)
        held = await self.call('/bank/transfers/' + transfer['id'] + '/intervention', {'version': 1, 'independent': False, 'compared': True})
        self.assertEqual(held['status'], 'held')
        await self.call('/bank/transfers/' + transfer['id'] + '/intervention', {'version': 1, 'independent': True, 'compared': True}, expected=409)
        await self.call('/bank/transfers/' + transfer['id'] + '/submit', {'version': 1, 'code': '1234'}, expected=409, extra={'Idempotency-Key': 'held-operation-key'})
        self.assertEqual((await self.call('/bank/account', method='GET'))['balance_grosz'], 1842050)

    async def test_edit_invalidates_challenge_and_old_preview_version(self):
        await self.authenticate()
        transfer = await self.preview()
        challenge = await self.ready(transfer)
        data = dict(recipient='Edited recipient', number=RECIPIENT, title='Changed', amount_grosz=100, version=1)
        updated = await self.call('/bank/transfers/' + transfer['id'], data, method='PUT', expected=201)
        self.assertEqual(updated['version'], 2)
        self.assertEqual(updated['status'], 'review')
        await self.call('/bank/transfers/' + transfer['id'], data, method='PUT', expected=409)
        await self.call('/bank/transfers/' + transfer['id'] + '/submit', dict(challenge_id=challenge['challenge_id'], code='1234', version=1), expected=409, extra={'Idempotency-Key': 'edited-operation-key'})

    async def test_validation_integer_money_and_nrb_checksum(self):
        await self.authenticate()
        for amount in (0, -100, 1.25, True, 1842051):
            result = await self.call('/bank/transfers', dict(recipient='Test', number=RECIPIENT, title='test', amount_grosz=amount), expected=422)
            self.assertIn('amount', result['fields'])
        result = await self.call('/bank/transfers', dict(recipient='Test', number='12345678901234567890123456', title='test', amount_grosz=100), expected=422)
        self.assertIn('number', result['fields'])

    async def test_csrf_origin_ownership_and_unauthenticated_routes(self):
        await self.call('/bank/account', method='GET', expected=401)
        await self.call('/session/permissions', {'telemetry': True}, expected=403, extra={'X-CSRF-Token': 'incorrect'})
        await self.call('/session/permissions', {'telemetry': True}, expected=403, extra={'Origin': 'https://foreign.example'})
        legacy = await self.request('/study/join', {'code': 'DEMO-24'})
        self.assertIn(legacy.status, (404, 405))
        await self.authenticate()
        await self.call('/session/permissions', {'camera': True})
        await self.call('/sessions/foreign-camera/output', method='GET', expected=404)
        await self.call('/bank/transfers/foreign-transfer', method='GET', expected=404)
        await self.call('/bank/logout', {})
        await self.call('/bank/account', method='GET', expected=401)

    async def test_bad_otp_limits_and_expiry(self):
        challenge = await self.call('/bank/login', dict(username='anna.demo', password='bank24'))
        await self.call('/bank/login-challenge', {}, expected=429)
        for _ in range(5):
            await self.call('/bank/verify', dict(challenge_id=challenge['challenge_id'], code='0000'), expected=422)
        await self.call('/bank/verify', dict(challenge_id=challenge['challenge_id'], code='1234'), expected=409)

    async def test_credentials_choose_account_and_otp_is_required(self):
        session = await self.call('/bootstrap', {})
        self.assertFalse(session['authenticated'])
        self.assertFalse(session['telemetry'])
        self.assertFalse(session['camera'])
        await self.call('/bank/login', {'username': 'anna.demo', 'password': 'wrong'}, expected=422)
        self.assertIsNone(self.app['store'].one('SELECT participant FROM sessions')['participant'])
        challenge = await self.call('/bank/login', {'username': 'anna.demo', 'password': 'bank24'})
        self.assertEqual(challenge['code_length'], 4)
        await self.call('/bank/account', method='GET', expected=401)
        verified = await self.call('/bank/verify', {'challenge_id': challenge['challenge_id'], 'code': '1234'})
        self.csrf = verified['csrf']
        self.assertEqual((await self.call('/bank/account', method='GET'))['name'], 'Anna Kowalska')
        self.assertTrue((await self.call('/bootstrap', {}))['authenticated'])

    async def test_optional_permissions_are_independent_and_withdrawable(self):
        await self.authenticate()
        await self.call('/telemetry/events', dict(page='page', events=[]), expected=403)
        state = await self.call('/session/permissions', {'camera': True})
        self.assertTrue(state['camera'])
        self.assertFalse(state['telemetry'])
        await self.call('/session/permissions', {'telemetry': True})
        self.assertTrue((await self.call('/bootstrap', {}))['telemetry'])
        await self.call('/session/permissions', {'telemetry': False, 'camera': False})
        self.assertEqual(self.app['store'].one('SELECT COUNT(*) count FROM telemetry')['count'], 0)
        await self.call('/webrtc/offer', {'type': 'offer', 'sdp': 'fake'}, expected=403)

    async def test_history_search_filters_before_pagination(self):
        await self.authenticate()
        db = self.app['store'].db
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', ('older-match', 'demo-owner', 'Café Studio', 'Invoice 2026', -100, '2026-01-01T10:00:00Z', 'completed'))
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', ('newer-nonmatch', 'demo-owner', 'Other shop', 'Shopping', -200, '2026-10-01T10:00:00Z', 'completed'))
        result = await self.call('/bank/transactions?q=cafe&direction=outgoing&limit=1&offset=0', method='GET')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], 'older-match')
        self.assertEqual((await self.call('/bank/transactions?q=studio', method='GET'))['total'], 1)

    async def test_multimodal_metadata_is_validated_and_keyboard_keys_not_stored(self):
        await self.authenticate(telemetry=True)
        base = dict(sequence=0, time_ms=100, stage='transfer', field='title')
        events = [{**base, 'type': 'environment', 'env': {'platform': 'test', 'screen': {'width': 1920, 'height': 1080}}},
                  {**base, 'sequence': 1, 'type': 'ping', 'duration_ms': 20},
                  {**base, 'sequence': 2, 'type': 'keyboard_window', 'duration_ms': 90, 'length': 16,
                   'keys': [66] * 16, 'features': [[3, 4, 2, 1, 0, 0, 0, 0]] * 16}]
        with mock.patch('bank24_inputs.encode_keyboard', return_value=[0.1] * 128):
            await self.call('/telemetry/events', dict(page='multimodal', page_anchor_ms=1000000, events=events))
        saved = [json.loads(row['event']) for row in self.app['store'].db.execute('SELECT event FROM telemetry')]
        keyboard = next(event for event in saved if event['type'] == 'keyboard_embedding')
        self.assertEqual(len(keyboard['embedding']), 128)
        self.assertNotIn('keys', keyboard)
        self.assertNotIn('features', keyboard)
        for invalid in [dict(events[2], field='password'), dict(events[2], keys=[66]),
                        dict(events[0], keys=[66]), dict(events[0], env={'screen': 'invalid'})]:
            await self.call('/telemetry/events', dict(page='invalid', events=[invalid]), expected=422)

    async def test_telemetry_consent_allowlist_dedup_withdraw(self):
        await self.authenticate(telemetry=True)
        event = dict(sequence=0, time_ms=200, type='input', stage='login', field='username', length=3)
        batch = dict(page='test-page', events=[event])
        await self.call('/telemetry/events', batch)
        await self.call('/telemetry/events', batch)
        self.assertEqual(self.app['store'].one('SELECT COUNT(*) count FROM telemetry')['count'], 1)
        await self.call('/telemetry/events', dict(page='test-page', events=[{**event, 'value': 'secret'}]), expected=422)
        await self.call('/study/survey', dict(rating=4, comment='Clear'))
        await self.call('/session/withdraw', {})
        self.assertEqual(self.app['store'].one('SELECT COUNT(*) count FROM telemetry')['count'], 0)
        self.assertEqual(self.app['store'].one('SELECT COUNT(*) count FROM surveys')['count'], 0)

    async def test_no_silent_sms_demo_in_non_demo_mode(self):
        await self.authenticate()
        self.assertTrue((await self.call('/bootstrap', {}))['demo_mode'])
        # Non-demo challenge generation must not silently provide the demo OTP.
        second = TestClient(TestServer(create_app(self.path, demo=False)))
        await second.start_server()
        try:
            headers = {'Origin': 'http://localhost:5173'}
            boot = await (await second.post('/api/bootstrap', json={}, headers=headers)).json()
            headers['X-CSRF-Token'] = boot['csrf']
            response = await second.post('/api/bank/login', json=dict(username='anna.demo', password='bank24'), headers=headers)
            self.assertEqual(response.status, 503)
        finally:
            await second.close()

    async def test_expired_challenge_and_atomic_insufficient_balance(self):
        await self.authenticate()
        transfer = await self.preview()
        challenge = await self.ready(transfer)
        endpoint = '/bank/transfers/' + transfer['id'] + '/submit'
        data = dict(version=1, challenge_id=challenge['challenge_id'], code='1234')
        self.app['store'].db.execute('UPDATE challenges SET expires=0 WHERE id=?', (challenge['challenge_id'],))
        await self.call(endpoint, data, expected=409, extra={'Idempotency-Key': 'expired-operation-key'})
        self.app['store'].db.execute('UPDATE challenges SET expires=? WHERE id=?', (time.time() + 100, challenge['challenge_id']))
        self.app['store'].db.execute('UPDATE participants SET balance=0 WHERE id="demo-owner"')
        await self.call(endpoint, data, expected=422, extra={'Idempotency-Key': 'balance-operation-key'})
        self.assertEqual(self.app['store'].one('SELECT status FROM transfers WHERE id=?', (transfer['id'],))['status'], 'ready')
        self.assertFalse(self.app['store'].one('SELECT 1 FROM ledger WHERE id=?', (transfer['id'],)))

    async def test_telemetry_without_opt_in_and_other_participant_ownership(self):
        await self.authenticate()
        transfer = await self.preview()
        await self.call('/telemetry/events', dict(page='page', events=[]), expected=403)
        salt = 'another-participant-salt'
        self.app['store'].db.execute('INSERT INTO participants VALUES(?,?,?,?,?,?)', ('second', None, 'second.user', salt, password_hash('second.password', salt), 100000))
        second = TestClient(TestServer(create_app(self.path, demo=True)))
        await second.start_server()
        try:
            headers = {'Origin': 'http://localhost:5173'}
            boot = await (await second.post('/api/bootstrap', json={}, headers=headers)).json()
            headers['X-CSRF-Token'] = boot['csrf']
            challenge = await (await second.post('/api/bank/login', json=dict(username='second.user', password='second.password'), headers=headers)).json()
            verify = await (await second.post('/api/bank/verify', json=dict(challenge_id=challenge['challenge_id'], code='1234'), headers=headers)).json()
            headers['X-CSRF-Token'] = verify['csrf']
            response = await second.get('/api/bank/transfers/' + transfer['id'], headers=headers)
            self.assertEqual(response.status, 404)
        finally:
            await second.close()


if __name__ == '__main__':
    unittest.main()
