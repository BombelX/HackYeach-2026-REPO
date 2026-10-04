"""Integration tests of actual bank API; no mocked ledger or authentication."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer
from bank24_server import create_app, digest, password_hash, RECIPIENT, Store


class BankTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'bank.sqlite'
        self.app = create_app(self.path, demo=True)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.csrf = ''
        response = await self.call('/bootstrap', {})
        self.csrf = response['csrf']

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

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

    async def preview(self, amount=125000):
        return await self.call('/bank/transfers', {'recipient': 'North Studio sp. z o.o.', 'number': RECIPIENT, 'title': 'Faktura FV/2026/104', 'amount_grosz': amount}, expected=201)

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
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', ('older-match', 'demo-owner', 'Café Studio', 'Faktura 2026', -100, '2026-01-01T10:00:00Z', 'completed'))
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', ('newer-nonmatch', 'demo-owner', 'Inny sklep', 'Zakupy', -200, '2026-10-01T10:00:00Z', 'completed'))
        result = await self.call('/bank/transactions?q=cafe&direction=outgoing&limit=1&offset=0', method='GET')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], 'older-match')
        self.assertEqual((await self.call('/bank/transactions?q=studio', method='GET'))['total'], 1)

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
