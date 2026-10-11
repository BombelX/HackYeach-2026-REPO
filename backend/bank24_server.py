"""Bank24 local demonstration API. SQLite state; authenticated camera gateway.

The demo moves fictional money only. No SMS provider or validated biometric risk
model is shipped. --demo explicitly enables documented credentials and OTP 1234.
Run the existing WebRTC worker on loopback separately; its protocol is unchanged.
"""
import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import math
import os
import pickle
from pathlib import Path
import secrets
import sqlite3
import time
import unicodedata
import uuid
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

import bank24_camera_risk
from bank24_risk import MODEL_VERSION, extract_features, rebuild_owner_profile, compare_with_profile

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def folded(value):
    normalized = unicodedata.normalize('NFKD', str(value))
    return ''.join(char for char in normalized.casefold() if not unicodedata.combining(char))


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def nrb(payload):
    """Generate valid *fictional* NRB from a 24-digit bank/account payload."""
    return f'{98 - int(payload + "252100") % 97:02d}' + payload


ACCOUNT = nrb('109000000000000000000024')
RECIPIENT = nrb('114000000000000000000024')
STUDY_SCENARIOS = {
    'calm_owner': 'Calm owner transfer',
    'calm_dictation': 'Calm dictation of details',
    'pressure': 'Pressure during transfer',
    'intruder': 'Non-owner operator',
}


def validate_transfer(data, balance):
    errors = {}
    recipient = str(data.get('recipient', '')).strip()
    number = ''.join(str(data.get('number', '')).split())
    title = str(data.get('title', '')).strip()
    amount = data.get('amount_grosz')
    if not 2 <= len(recipient) <= 100:
        errors['recipient'] = 'Enter a recipient name (2–100 characters).'
    if len(number) != 26 or not number.isascii() or not number.isdigit() or int(number[2:] + '2521' + number[:2]) % 97 != 1:
        errors['number'] = 'Enter all 26 digits of a valid NRB account number.'
    elif number == ACCOUNT:
        errors['number'] = 'Choose an account other than the source account.'
    if not 1 <= len(title) <= 140:
        errors['title'] = 'Enter a transfer reference (up to 140 characters).'
    if type(amount) is not int or amount <= 0:
        errors['amount'] = 'Enter a positive amount with up to two decimal places.'
    elif amount > balance:
        errors['amount'] = 'The amount exceeds available funds.'
    if errors:
        raise ApiError(422, 'fields', 'Correct the highlighted transfer details.', errors)
    return recipient, number, title, amount


class ApiError(Exception):
    def __init__(self, status, code, message, fields=None):
        self.status, self.code, self.message, self.fields = status, code, message, fields or {}


class Store:
    def __init__(self, path, demo=False):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('bank24_fold', 1, folded, deterministic=True)
        self.db.executescript('''
          PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS participants(id TEXT PRIMARY KEY,code_hash TEXT UNIQUE,username TEXT UNIQUE,salt TEXT,password TEXT,balance INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS study_participants(id TEXT PRIMARY KEY,code_hash TEXT UNIQUE NOT NULL,label TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'operator',bank_participant TEXT NOT NULL REFERENCES participants(id),created_at REAL NOT NULL,withdrawn INTEGER NOT NULL DEFAULT 0,withdrawn_at REAL);
          CREATE TABLE IF NOT EXISTS study_assignments(id TEXT PRIMARY KEY,study_participant TEXT NOT NULL REFERENCES study_participants(id),scenario TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'assigned',created_at REAL NOT NULL,used_at REAL);
          CREATE TABLE IF NOT EXISTS study_sessions(id TEXT PRIMARY KEY,study_participant TEXT NOT NULL REFERENCES study_participants(id),bank_participant TEXT NOT NULL REFERENCES participants(id),assignment_id TEXT NOT NULL REFERENCES study_assignments(id),scenario TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,telemetry_allowed INTEGER NOT NULL,camera_allowed INTEGER NOT NULL,created_at REAL NOT NULL,started_at REAL,ended_at REAL,abort_reason TEXT);
          CREATE TABLE IF NOT EXISTS study_consents(id TEXT PRIMARY KEY,study_participant TEXT NOT NULL REFERENCES study_participants(id),bank_session TEXT NOT NULL,telemetry INTEGER NOT NULL,camera INTEGER NOT NULL,recording INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL,created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,id TEXT UNIQUE,participant TEXT REFERENCES participants(id),study_participant TEXT REFERENCES study_participants(id),study_session TEXT REFERENCES study_sessions(id),csrf TEXT,consent INTEGER DEFAULT 0,telemetry INTEGER DEFAULT 0,authenticated INTEGER DEFAULT 0,expires REAL,login_failures INTEGER DEFAULT 0,locked_until REAL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,session TEXT REFERENCES sessions(id),kind TEXT,transfer_id TEXT,version INTEGER,code_hash TEXT,expires REAL,attempts INTEGER DEFAULT 0,used INTEGER DEFAULT 0,created REAL,remember INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY,participant TEXT REFERENCES participants(id),study_session TEXT REFERENCES study_sessions(id),version INTEGER,recipient TEXT,number TEXT,title TEXT,amount_grosz INTEGER,status TEXT,risk TEXT,created TEXT,confirmed TEXT,idempotency TEXT,risk_acknowledged INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,participant TEXT REFERENCES participants(id),recipient TEXT,title TEXT,amount_grosz INTEGER,created TEXT,status TEXT);
          CREATE TABLE IF NOT EXISTS devices(token_hash TEXT PRIMARY KEY,participant TEXT REFERENCES participants(id),expires REAL);
          CREATE TABLE IF NOT EXISTS telemetry(session TEXT REFERENCES sessions(id),study_session TEXT REFERENCES study_sessions(id),page TEXT,sequence INTEGER,event TEXT,PRIMARY KEY(session,page,sequence));
          CREATE TABLE IF NOT EXISTS surveys(session TEXT PRIMARY KEY REFERENCES sessions(id),rating INTEGER,comment TEXT);
          CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY,session TEXT REFERENCES sessions(id),study_session TEXT REFERENCES study_sessions(id));
          CREATE TABLE IF NOT EXISTS study_stage_events(id TEXT PRIMARY KEY,study_session TEXT NOT NULL REFERENCES study_sessions(id),stage TEXT NOT NULL,created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS owner_profiles(bank_participant TEXT NOT NULL REFERENCES participants(id),stage TEXT NOT NULL,version TEXT NOT NULL,observations INTEGER NOT NULL,features TEXT NOT NULL,modalities TEXT NOT NULL DEFAULT '[]',ready INTEGER NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(bank_participant,stage));
          CREATE TABLE IF NOT EXISTS camera_profile_samples(participant TEXT NOT NULL REFERENCES participants(id),bank_session TEXT NOT NULL,profile BLOB NOT NULL,created_at REAL NOT NULL,approved INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(participant,bank_session));
          CREATE TABLE IF NOT EXISTS camera_profile_versions(participant TEXT NOT NULL REFERENCES participants(id),version INTEGER NOT NULL,model_version TEXT NOT NULL,sample_count INTEGER NOT NULL,profile BLOB NOT NULL,created_at REAL NOT NULL,trusted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(participant,version));
          CREATE TABLE IF NOT EXISTS camera_enrollment_attempts(participant TEXT NOT NULL REFERENCES participants(id),bank_session TEXT NOT NULL,camera_id TEXT NOT NULL,start_ms REAL NOT NULL,started_at REAL NOT NULL,PRIMARY KEY(participant,bank_session));
          CREATE TABLE IF NOT EXISTS risk_assessments(id TEXT PRIMARY KEY,study_session TEXT NOT NULL REFERENCES study_sessions(id),stage TEXT NOT NULL,assessment TEXT NOT NULL,features TEXT NOT NULL,created_at REAL NOT NULL);
        ''')
        migrations = {
            'study_participants': {'role': "TEXT NOT NULL DEFAULT 'operator'"},
            'sessions': {
                'camera_consent': 'INTEGER NOT NULL DEFAULT 0',
                'study_participant': 'TEXT REFERENCES study_participants(id)',
                'study_session': 'TEXT REFERENCES study_sessions(id)',
            },
            'telemetry': {'study_session': 'TEXT REFERENCES study_sessions(id)'},
            'transfers': {
                'study_session': 'TEXT REFERENCES study_sessions(id)',
                'risk_acknowledged': 'INTEGER NOT NULL DEFAULT 0',
            },
            'owner_profiles': {'modalities': "TEXT NOT NULL DEFAULT '[]'"},
            'cameras': {'study_session': 'TEXT REFERENCES study_sessions(id)'},
            'camera_profile_samples': {'approved': 'INTEGER NOT NULL DEFAULT 0'},
            'camera_profile_versions': {'trusted': 'INTEGER NOT NULL DEFAULT 0'},
        }
        for table, definitions in migrations.items():
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            for name, definition in definitions.items():
                if name not in columns:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        # Participant-code entry was removed; do not retain or seed its credential hash.
        self.db.execute('UPDATE participants SET code_hash=NULL WHERE code_hash IS NOT NULL')
        if demo and not self.db.execute('SELECT 1 FROM participants').fetchone():
            salt = secrets.token_hex(16)
            self.db.execute('INSERT INTO participants VALUES(?,?,?,?,?,?)', ('demo-owner', None, 'anna.demo', salt, password_hash('bank24', salt), 1842050))
            for who, title, amount, date in [('Employer', 'Salary', 720000, '2026-10-01T08:00:00Z'), ('Property management', 'Rent · October', -245000, '2026-10-02T09:00:00Z'), ('Online store', 'Accessories purchase', -8990, '2026-09-28T12:00:00Z')]:
                self.db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, 'demo-owner', who, title, amount, date, 'completed'))

    def one(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()


def create_app(db_path, demo=False, camera_url='http://127.0.0.1:8080', origin='http://localhost:5173', secure=False, otp_provider=None, admin_token=None, turn_urls=(), turn_secret=None, turn_ttl=3600, fusion_repo=None, camera_profiles=None, risk_logout=70, alarm_code='4321', alarm_delay=7.0):
    store = Store(db_path, demo)
    db = store.db
    allowed_origins = set()
    for item in filter(None, (part.strip() for part in origin.split(','))):
        allowed_origins.add(item)
        origin_parts = urlsplit(item)
        if origin_parts.hostname in ('localhost', '127.0.0.1'):
            other_host = '127.0.0.1' if origin_parts.hostname == 'localhost' else 'localhost'
            allowed_origins.add(f'{origin_parts.scheme}://{other_host}' + (f':{origin_parts.port}' if origin_parts.port else ''))

    @web.middleware
    async def security(request, handler):
        try:
            request['session'] = store.one('SELECT * FROM sessions WHERE token_hash=? AND expires>?', (digest(request.cookies.get('bank24_session', '')), time.time()))
            operator_request = request.path.startswith('/api/admin/') or (request.path == '/api/study/participants' and request.method == 'POST')
            if operator_request:
                if not admin_token:
                    raise ApiError(503, 'admin_disabled', 'The operator panel requires a configured BANK24_ADMIN_TOKEN.')
                if not hmac.compare_digest(request.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + admin_token).encode('utf-8')):
                    raise ApiError(401, 'admin_authentication', 'No valid operator token.')
            if request.path.startswith('/api/') and (request.method not in ('GET', 'HEAD') or request.headers.get('Upgrade', '').lower() == 'websocket'):
                if request.headers.get('Origin') not in allowed_origins:
                    raise ApiError(403, 'origin', 'Request origin is not allowed.')
                if request.method not in ('GET', 'HEAD') and request.path != '/api/bootstrap' and not operator_request:
                    session = need_session(request)
                    if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session['csrf']):
                        raise ApiError(403, 'csrf', 'Refresh the page to renew your session.')
            response = await handler(request)
        except ApiError as exc:
            response = web.json_response(dict(code=exc.code, message=exc.message, fields=exc.fields), status=exc.status)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = web.json_response(dict(code='json', message='Invalid request format.'), status=400)
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    app = web.Application(middlewares=[security], client_max_size=256 * 1024)
    app['store'] = store

    forced_mismatch = {}  # bank session id -> (forced p_not_owner, time it takes effect) for the demo alarm code
    def alarm_state(session):
        """(forced p_not_owner or None, seconds until it takes effect)."""
        if session['id'] not in forced_mismatch:
            return None, 0.0
        value, active_at = forced_mismatch[session['id']]
        return value, max(0.0, active_at - time.time())

    def need_session(request, auth=False, telemetry=False):
        session = request.get('session')
        if session is None:
            raise ApiError(401, 'session', 'Session expired. Sign in again.')
        if auth and not session['authenticated']:
            raise ApiError(401, 'authentication', 'Sign in to access your account.')
        if telemetry and not session['telemetry']:
            raise ApiError(403, 'telemetry_consent', 'Optional measurement is disabled.')
        return session

    def need_admin(request):
        if not admin_token:
            raise ApiError(503, 'admin_disabled', 'The operator panel requires a configured BANK24_ADMIN_TOKEN.')
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode('utf-8'), ('Bearer ' + admin_token).encode('utf-8')):
            raise ApiError(401, 'admin_authentication', 'No valid operator token.')

    def get_study_session(request, study_session_id):
        session = need_session(request)
        study = store.one('SELECT * FROM study_sessions WHERE id=?', (study_session_id,))
        if not study or session['study_participant'] != study['study_participant'] or session['study_session'] != study_session_id:
            raise ApiError(404, 'study_session', 'Study session not found.')
        if session['authenticated'] and session['participant'] != study['bank_participant']:
            raise ApiError(404, 'study_session', 'Study session not found.')
        return session, study

    def evaluate_stage(study_session_id, stage):
        study = store.one('SELECT * FROM study_sessions WHERE id=?', (study_session_id,))
        extracted = extract_features(db, study_session_id, stage)
        if not study or study['status'] not in ('running', 'completed'):
            return extracted, None, [], 'insufficient_data'
        profile = store.one('SELECT * FROM owner_profiles WHERE bank_participant=? AND stage=?', (study['bank_participant'], stage))
        score, explanations, status = compare_with_profile(extracted, profile)
        return extracted, score, explanations, status

    def assess_study_session(study_session_id, current_stage):
        login_features, account_score, account_explanations, account_status = evaluate_stage(study_session_id, 'login')
        transfer_features, coercion_score, coercion_explanations, coercion_status = evaluate_stage(study_session_id, 'transfer')
        if current_stage == 'login':
            coercion_score = None
            coercion_explanations = []
            coercion_status = 'not_assessed'
        available = []
        missing = []
        if account_score is not None:
            available.append('login_behavior')
        elif account_status == 'insufficient_data':
            missing.append('No ready owner profile or sufficient sign-in data.')
        if current_stage != 'login':
            if coercion_score is not None:
                available.append('transfer_behavior')
            elif coercion_status == 'insufficient_data':
                missing.append('No ready owner profile or sufficient transfer data.')
        scored = [value for value in (account_score, coercion_score) if value is not None]
        status = 'limited' if scored else 'insufficient_data'
        interventions = []
        action = 'review_required'
        if account_score is not None and account_score >= 70:
            action = 'additional_verification'
            interventions.append('additional_transaction_verification')
        if coercion_score is not None and coercion_score >= 70:
            action = 'coercion_review'
            interventions.append('independent_recipient_check')
        elif scored and not missing and not interventions:
            action = 'standard_confirmation'
        if missing:
            interventions.append('do_not_treat_as_low_risk')
        explanations = account_explanations + coercion_explanations
        reasons = [item['message'] for item in explanations]
        reasons.extend(missing)
        reasons.append('Indicators are heuristic and unvalidated; they are not fraud probabilities.')
        assessment = {
            'account_takeover_risk': account_score,
            'coercion_risk': coercion_score,
            'assessment_status': status,
            'quality': 'limited' if scored else 'insufficient',
            'available_signals': available,
            'available_modalities': {
                'login': login_features['modalities'],
                'transfer': transfer_features['modalities'],
            },
            'missing_reasons': missing,
            'action': action,
            'recommended_interventions': interventions,
            'reasons': reasons,
            'explanations': explanations,
            'model_version': MODEL_VERSION,
            'validated': False,
            'assessed_at': time.time(),
        }
        features = {'login': login_features, 'transfer': transfer_features}
        return assessment, features

    def save_assessment(study_session_id, stage, assessment, features):
        db.execute(
            'INSERT INTO risk_assessments(id,study_session,stage,assessment,features,created_at) VALUES(?,?,?,?,?,?)',
            (uuid.uuid4().hex, study_session_id, stage, json.dumps(assessment), json.dumps(features), assessment['assessed_at']),
        )

    async def body(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ApiError(400, 'json', 'Expected a JSON object.')
        return data

    def cookie(response, name, value, age):
        response.set_cookie(name, value, httponly=True, samesite='Strict', secure=secure, max_age=age, path='/')

    def session_data(session):
        return dict(csrf=session['csrf'], session_id=session['id'], telemetry=bool(session['telemetry']), camera=bool(session['camera_consent']), authenticated=bool(session['authenticated']), demo_mode=demo, camera_transmission=bool(session['camera_consent']), study_participant=bool(session['study_participant']), study_session_id=session['study_session'])

    async def bootstrap(request):
        session = request['session']
        token = None
        if session is None:
            token = secrets.token_urlsafe(32)
            session_id = uuid.uuid4().hex
            db.execute('INSERT INTO sessions(token_hash,id,csrf,expires) VALUES(?,?,?,?)', (digest(token), session_id, secrets.token_urlsafe(32), time.time() + 7200))
            session = store.one('SELECT * FROM sessions WHERE id=?', (session_id,))
        response = web.json_response(session_data(session))
        if token:
            cookie(response, 'bank24_session', token, 7200)
        return response

    async def permissions(request):
        session = need_session(request)
        data = await body(request)
        if set(data) - {'telemetry', 'camera'} or any(type(value) is not bool for value in data.values()):
            raise ApiError(422, 'permissions', 'Set consent separately for each measurement.')
        telemetry = int(data.get('telemetry', bool(session['telemetry'])))
        camera = int(data.get('camera', bool(session['camera_consent'])))
        study = store.one('SELECT * FROM study_sessions WHERE id=?', (session['study_session'],)) if session['study_session'] else None
        if study:
            if telemetry and not study['telemetry_allowed']:
                raise ApiError(403, 'telemetry_consent', 'Enable telemetry using the separate research consent form.')
            if camera and not study['camera_allowed']:
                raise ApiError(403, 'camera_consent', 'Enable the camera using the separate research consent form.')
        db.execute('UPDATE sessions SET consent=?,telemetry=?,camera_consent=? WHERE id=?',
                   (telemetry, telemetry, camera, session['id']))
        if not telemetry:
            if study:
                db.execute('UPDATE study_sessions SET telemetry_allowed=0 WHERE id=?', (study['id'],))
                db.execute('DELETE FROM telemetry WHERE study_session=?', (study['id'],))
                db.execute('DELETE FROM risk_assessments WHERE study_session=?', (study['id'],))
                for stage in ('login', 'transfer'):
                    rebuild_owner_profile(db, study['bank_participant'], stage)
            else:
                db.execute('DELETE FROM telemetry WHERE session=?', (session['id'],))
        if study and not camera:
            db.execute('UPDATE study_sessions SET camera_allowed=0 WHERE id=?', (study['id'],))
        if not camera:
            await close_cameras(session)
        return web.json_response(session_data(store.one('SELECT * FROM sessions WHERE id=?', (session['id'],))))

    async def withdraw(request):
        session = need_session(request, auth=True)
        if session['study_participant']:
            await withdraw_participant_data(session['study_participant'])
            return web.json_response(dict(ok=True, authenticated=True, study_data_deleted=True))
        await close_cameras(session)
        db.execute('DELETE FROM telemetry WHERE session=?', (session['id'],))
        db.execute('DELETE FROM camera_profile_versions WHERE participant=?', (session['participant'],))
        db.execute('DELETE FROM camera_profile_samples WHERE participant=?', (session['participant'],))
        db.execute('DELETE FROM camera_enrollment_attempts WHERE participant=?', (session['participant'],))
        remove_legacy_camera_profile(session['participant'])
        db.execute('DELETE FROM surveys WHERE session=?', (session['id'],))
        db.execute('DELETE FROM challenges WHERE session=? AND kind="login"', (session['id'],))
        db.execute('UPDATE sessions SET consent=0,telemetry=0,camera_consent=0 WHERE id=?', (session['id'],))
        response = web.json_response(dict(ok=True, authenticated=True))
        return response

    async def make_challenge(session, kind, transfer=None, remember=False):
        recent = store.one('SELECT created FROM challenges WHERE session=? AND kind=? ORDER BY created DESC LIMIT 1', (session['id'], kind))
        if recent and time.time() - recent['created'] < 30:
            raise ApiError(429, 'cooldown', 'Wait 30 seconds before requesting another code.')
        code = '1234' if demo else f'{secrets.randbelow(1000000):06d}'
        if not demo and otp_provider is None:
            raise ApiError(503, 'sms_unavailable', 'SMS delivery is not configured. Contact the facilitator.')
        challenge_id = uuid.uuid4().hex
        db.execute('UPDATE challenges SET used=1 WHERE session=? AND kind=? AND used=0', (session['id'], kind))
        db.execute('INSERT INTO challenges(id,session,kind,transfer_id,version,code_hash,expires,created,remember) VALUES(?,?,?,?,?,?,?,?,?)', (challenge_id, session['id'], kind, transfer['id'] if transfer else None, transfer['version'] if transfer else None, digest(challenge_id + code), time.time() + 300, time.time(), int(remember)))
        if otp_provider:
            await otp_provider(session['participant'], code)
        return dict(challenge_id=challenge_id, expires_at=time.time() + 300, resend_at=time.time() + 30, demo_mode=demo, code_length=len(code))

    async def login(request):
        session = need_session(request)
        data = await body(request)
        if session['locked_until'] > time.time():
            raise ApiError(429, 'locked', 'Too many attempts. Try again in five minutes.')
        if session['authenticated']:
            raise ApiError(409, 'already_authenticated', 'Sign out before switching accounts.')
        owner = store.one('SELECT * FROM participants WHERE username=?', (str(data.get('username', '')).strip()[:100],))
        salt = owner['salt'] if owner else 'bank24-unknown-login-salt'
        candidate = password_hash(str(data.get('password', ''))[:256], salt)
        expected = owner['password'] if owner else password_hash('invalid-password', salt)
        correct = bool(owner) and hmac.compare_digest(candidate, expected)
        if not correct:
            attempts = session['login_failures'] + 1
            db.execute('UPDATE sessions SET login_failures=?,locked_until=? WHERE id=?', (attempts, time.time() + 300 if attempts >= 5 else 0, session['id']))
            raise ApiError(422, 'credentials', 'The username or password is incorrect. Check both fields.')
        if session['study_participant']:
            study_person = store.one('SELECT bank_participant,withdrawn FROM study_participants WHERE id=?', (session['study_participant'],))
            if not study_person or study_person['withdrawn'] or study_person['bank_participant'] != owner['id']:
                raise ApiError(403, 'study_account', 'This account is not assigned to the participant code. Contact the facilitator.')
        db.execute('UPDATE challenges SET used=1 WHERE session=? AND kind="login" AND used=0', (session['id'],))
        db.execute('UPDATE sessions SET participant=?,login_failures=0,locked_until=0 WHERE id=?', (owner['id'], session['id']))
        session = store.one('SELECT * FROM sessions WHERE id=?', (session['id'],))
        challenge = await make_challenge(session, 'login', remember=data.get('remember') is True)
        return web.json_response(challenge)

    def check_challenge(session, data, kind, transfer=None):
        challenge = store.one('SELECT * FROM challenges WHERE id=? AND session=? AND kind=?', (str(data.get('challenge_id', '')), session['id'], kind))
        if not challenge or challenge['used'] or challenge['expires'] < time.time() or challenge['attempts'] >= 5:
            raise ApiError(409, 'challenge_expired', 'The code expired or the attempt limit was reached. Request a new code.')
        if transfer and (challenge['transfer_id'] != transfer['id'] or challenge['version'] != transfer['version']):
            raise ApiError(409, 'version', 'Transfer details changed. Request a code for the current details.')
        db.execute('UPDATE challenges SET attempts=attempts+1 WHERE id=?', (challenge['id'],))
        if demo and alarm_code and hmac.compare_digest(str(data.get('code', '')), alarm_code):
            # Demo scenario: the alarm code is accepted but raises the profile mismatch to the top of the scale.
            if session['id'] not in forced_mismatch:
                forced_mismatch[session['id']] = (0.93 + secrets.randbelow(60) / 1000, time.time() + alarm_delay)
            return challenge
        if not hmac.compare_digest(digest(challenge['id'] + str(data.get('code', ''))), challenge['code_hash']):
            raise ApiError(422, 'fields', 'The code is incorrect.', {'code': 'Check the code and try again.'})
        return challenge

    async def verify(request):
        session = need_session(request)
        challenge = check_challenge(session, await body(request), 'login')
        if session['study_session']:
            study = store.one('SELECT * FROM study_sessions WHERE id=? AND status="running"', (session['study_session'],))
            if study:
                assessment, features = assess_study_session(study['id'], 'login')
                save_assessment(study['id'], 'login', assessment, features)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        db.execute('UPDATE challenges SET used=1 WHERE id=?', (challenge['id'],))
        db.execute('UPDATE sessions SET authenticated=1,token_hash=?,csrf=? WHERE id=?', (digest(token), csrf, session['id']))
        if not session['study_session']:
            # The camera runs for the whole signed-in session (fusion risk needs it from login on).
            db.execute('UPDATE sessions SET camera_consent=1 WHERE id=?', (session['id'],))
        response = web.json_response(dict(ok=True, csrf=csrf))
        cookie(response, 'bank24_session', token, 7200)
        if challenge['remember']:
            device = secrets.token_urlsafe(32)
            db.execute('INSERT INTO devices VALUES(?,?,?)', (digest(device), session['participant'], time.time() + 30 * 86400))
            cookie(response, 'bank24_device', device, 30 * 86400)
        return response

    async def login_challenge(request):
        session = need_session(request)
        challenge = store.one('SELECT * FROM challenges WHERE session=? AND kind="login" AND used=0 ORDER BY created DESC LIMIT 1', (session['id'],))
        if not challenge:
            raise ApiError(409, 'no_challenge', 'Enter your username and password first.')
        if request.method == 'POST':
            return web.json_response(await make_challenge(session, 'login', remember=bool(challenge['remember'])))
        return web.json_response(dict(challenge_id=challenge['id'], expires_at=challenge['expires'], resend_at=challenge['created'] + 30, demo_mode=demo, code_length=4 if demo else 6))

    async def account(request):
        session = need_session(request, auth=True)
        owner = store.one('SELECT * FROM participants WHERE id=?', (session['participant'],))
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        totals = store.one('SELECT COALESCE(SUM(CASE WHEN amount_grosz>0 THEN amount_grosz ELSE 0 END),0) incoming,COALESCE(-SUM(CASE WHEN amount_grosz<0 THEN amount_grosz ELSE 0 END),0) outgoing FROM ledger WHERE participant=? AND substr(created,1,7)=?', (owner['id'], month))
        trusted = bool(store.one('SELECT 1 FROM devices WHERE token_hash=? AND participant=? AND expires>?', (digest(request.cookies.get('bank24_device', '')), owner['id'], time.time())))
        return web.json_response(dict(name='Anna Kowalska', number=ACCOUNT, balance_grosz=owner['balance'], currency='PLN', month=month, incoming_grosz=totals['incoming'], outgoing_grosz=totals['outgoing'], trusted_device=trusted, invoice=dict(recipient='North Studio sp. z o.o.', number=RECIPIENT, amount_grosz=125000, title='Invoice FV/2026/104', reference='FV/2026/104')))

    async def transactions(request):
        session = need_session(request, auth=True)
        try:
            offset = max(0, int(request.query.get('offset', 0)))
            limit = min(100, max(1, int(request.query.get('limit', 30))))
        except ValueError:
            raise ApiError(400, 'pagination', 'Niepoprawny zakres historii.')
        search = str(request.query.get('q', '')).strip()[:100]
        direction = request.query.get('direction', 'all')
        if direction not in ('all', 'incoming', 'outgoing'):
            raise ApiError(400, 'direction', 'Choose a valid history filter.')
        clauses = ['participant=?']
        params = [session['participant']]
        if search:
            clauses.append("bank24_fold(recipient || ' ' || title || ' ' || created || ' ' || COALESCE(strftime('%d.%m.%Y', created), '')) LIKE ?")
            params.append('%' + folded(search) + '%')
        if direction == 'incoming':
            clauses.append('amount_grosz>0')
        elif direction == 'outgoing':
            clauses.append('amount_grosz<0')
        where = ' AND '.join(clauses)
        total = store.one('SELECT COUNT(*) count FROM ledger WHERE ' + where, params)['count']
        rows = [dict(row) for row in db.execute('SELECT * FROM ledger WHERE ' + where + ' ORDER BY created DESC,id DESC LIMIT ? OFFSET ?', (*params, limit, offset))]
        return web.json_response(dict(items=rows, total=total, offset=offset, limit=limit))

    def get_transfer(request):
        session = need_session(request, auth=True)
        transfer = store.one('SELECT * FROM transfers WHERE id=? AND participant=?', (request.match_info['id'], session['participant']))
        if not transfer:
            raise ApiError(404, 'transfer', 'This transfer was not found in your account.')
        return session, transfer

    def transfer_data(transfer):
        data = dict(transfer)
        data.pop('participant')
        data.pop('study_session', None)
        data.pop('idempotency')
        data.pop('risk_acknowledged', None)
        data['risk'] = json.loads(data['risk'])
        return data

    def assess():
        # Deliberately no trained classifier / biometric identity inference.
        reason = 'No linked study session, owner profile or sufficient telemetry.'
        empty_modalities = {name: False for name in ('keyboard', 'pointer', 'form')}
        return dict(account_takeover_risk=None, coercion_risk=None, assessment_status='insufficient_data', quality='insufficient', available_signals=[], available_modalities={'login': empty_modalities, 'transfer': dict(empty_modalities)}, missing_reasons=[reason], action='review_required', recommended_interventions=['do_not_treat_as_low_risk'], reasons=[reason], explanations=[], model_version=MODEL_VERSION, validated=False, assessed_at=time.time())

    async def camera_assess(session):
        """Fusion-model risk from the session's live camera trace, or (None, reason)."""
        p_not_owner, pending = alarm_state(session)
        if p_not_owner is not None and not pending:
            return bank24_camera_risk.risk_from_camera(dict(
                p_not_owner=p_not_owner, p_pressure=0.02, review_required=True, review_score=p_not_owner,
                review_threshold=0.1285, probe_seconds=0, profile_enrolled_now=False)), None
        if fusion_repo is None:
            return None, None
        saved = store.one('SELECT version,profile FROM camera_profile_versions WHERE participant=? AND trusted=1 ORDER BY version DESC LIMIT 1', (session['participant'],))
        if saved and store.one('SELECT 1 FROM camera_profile_samples WHERE participant=? AND bank_session=? AND approved=1',
                               (session['participant'], session['id'])):
            # The current recording contributed to the newest version. Score against the prior
            # version to keep enrolment and probe data separate; version 1 starts next login.
            saved = store.one('SELECT version,profile FROM camera_profile_versions WHERE participant=? AND trusted=1 AND version<? ORDER BY version DESC LIMIT 1',
                              (session['participant'], saved['version']))
        if not saved:
            return None, 'The camera profile is not ready for assessment. Three samples from separate sign-ins will activate it at the next sign-in.'
        try:
            trace = await current_camera_trace(session)
            profile = bank24_camera_risk.load_profile(saved['profile'], Path(fusion_repo))
            result = await asyncio.get_running_loop().run_in_executor(
                None, bank24_camera_risk.assess_camera, trace, session['participant'], Path(fusion_repo), profile)
        except bank24_camera_risk.CameraRiskUnavailable as exc:
            return None, str(exc)
        except Exception:
            logging.exception('camera fusion risk failed')
            return None, 'The camera assessment model reported an error.'
        risk = bank24_camera_risk.risk_from_camera(result)
        risk['camera_model']['profile_version'] = saved['version']
        return risk, None

    async def current_camera_trace(session):
        row = store.one('SELECT id FROM cameras WHERE session=? ORDER BY rowid DESC LIMIT 1', (session['id'],))
        if not row:
            raise bank24_camera_risk.CameraRiskUnavailable('The camera was not enabled.')
        try:
            async with app['http'].get(camera_url + '/api/sessions/' + row['id'] + '/trace') as upstream:
                if upstream.status >= 400:
                    raise bank24_camera_risk.CameraRiskUnavailable('Camera session expired — turn the camera on again.')
                trace = await upstream.json()
                trace['telemetry'] = [json.loads(row['event']) for row in db.execute(
                    'SELECT event FROM telemetry WHERE session=? ORDER BY page,sequence', (session['id'],))] if session['telemetry'] else []
                return trace
        except (OSError, asyncio.TimeoutError, ValueError) as exc:
            raise bank24_camera_risk.CameraRiskUnavailable('Camera analysis service is unavailable.') from exc

    def camera_profile_status(participant, bank_session):
        count = store.one('SELECT COUNT(*) n FROM camera_profile_samples WHERE participant=? AND approved=1', (participant,))['n']
        pending = store.one('SELECT COUNT(*) n FROM camera_profile_samples WHERE participant=? AND approved=0', (participant,))['n']
        saved = store.one('SELECT version,sample_count,created_at FROM camera_profile_versions WHERE participant=? AND trusted=1 ORDER BY version DESC LIMIT 1', (participant,))
        recorded = bool(store.one('SELECT 1 FROM camera_profile_samples WHERE participant=? AND bank_session=?',
                                  (participant, bank_session)))
        approved_this_session = bool(store.one('SELECT 1 FROM camera_profile_samples WHERE participant=? AND bank_session=? AND approved=1',
                                               (participant, bank_session)))
        attempt = store.one('SELECT started_at FROM camera_enrollment_attempts WHERE participant=? AND bank_session=?',
                            (participant, bank_session))
        return dict(status='ready' if saved else 'collecting', samples=count, pending=pending, required=3,
                    version=saved['version'] if saved else None,
                    activates_next_sign_in=bool(saved and approved_this_session),
                    updated_at=saved['created_at'] if saved else None,
                    recorded_this_session=recorded, model_available=fusion_repo is not None,
                    started_at=attempt['started_at'] if attempt else None,
                    approval_available=bool(admin_token),
                    can_enroll=bool(fusion_repo) and bool(admin_token or (demo and not saved)))

    def remove_legacy_camera_profile(participant):
        # Older builds stored automatically enrolled profiles as individual files.
        if Path(participant).name == participant:
            directory = Path(camera_profiles) if camera_profiles else Path(db_path).parent / 'camera_profiles'
            (directory / f'{participant}.pkl').unlink(missing_ok=True)

    async def camera_profile_get(request):
        session = need_session(request, auth=True)
        return web.json_response(camera_profile_status(session['participant'], session['id']))

    async def camera_profile_delete(request):
        session = need_session(request, auth=True)
        db.execute('DELETE FROM camera_profile_versions WHERE participant=?', (session['participant'],))
        db.execute('DELETE FROM camera_profile_samples WHERE participant=?', (session['participant'],))
        db.execute('DELETE FROM camera_enrollment_attempts WHERE participant=?', (session['participant'],))
        remove_legacy_camera_profile(session['participant'])
        return web.json_response(camera_profile_status(session['participant'], session['id']))

    def check_enrollment_session(session):
        if fusion_repo is None:
            raise ApiError(503, 'model_unavailable', 'Camera model is unavailable.')
        current_profile = store.one('SELECT 1 FROM camera_profile_versions WHERE participant=? AND trusted=1 LIMIT 1',
                                    (session['participant'],))
        if not admin_token and (not demo or current_profile):
            raise ApiError(503, 'operator_unavailable', 'Updating the profile requires a configured operator.')
        if not session['camera_consent'] or session['study_session']:
            raise ApiError(403, 'camera_permission', 'Saving a profile requires an active camera in a regular banking session.')
        if session['id'] in forced_mismatch:
            raise ApiError(403, 'untrusted_session', 'This session cannot update the profile.')
        if store.one('SELECT 1 FROM camera_profile_samples WHERE participant=? AND bank_session=?',
                     (session['participant'], session['id'])):
            raise ApiError(409, 'sample_exists', 'A sample from this session is already saved. Sign in again to add another.')
        if not store.one('SELECT 1 FROM challenges WHERE session=? AND kind="login" AND used=1', (session['id'],)):
            raise ApiError(403, 'untrusted_session', 'Saving a sample requires sign-in verified with a code.')

    def save_approved_camera_version(participant, now):
        rows = db.execute('SELECT profile FROM camera_profile_samples WHERE participant=? AND approved=1 ORDER BY created_at DESC,bank_session DESC LIMIT 5',
                          (participant,)).fetchall()
        if len(rows) < 3:
            return
        combined = bank24_camera_risk.combine_samples(
            [bank24_camera_risk.load_profile(row['profile'], Path(fusion_repo)) for row in reversed(rows)],
            participant)
        latest = store.one('SELECT MAX(version) version FROM camera_profile_versions WHERE participant=?', (participant,))
        version = (latest['version'] or 0) + 1
        db.execute('INSERT INTO camera_profile_versions(participant,version,model_version,sample_count,profile,created_at,trusted) VALUES(?,?,?,?,?,?,1)',
                   (participant, version, bank24_camera_risk.MODEL_LABEL, len(rows), pickle.dumps(combined), now))

    async def camera_profile_start(request):
        session = need_session(request, auth=True)
        check_enrollment_session(session)
        data = await body(request)
        if set(data) != {'confirm_calm'} or data['confirm_calm'] is not True:
            raise ApiError(422, 'enrolment_confirmation', 'Explicitly confirm starting a calm sample.')
        row = store.one('SELECT id FROM cameras WHERE session=? ORDER BY rowid DESC LIMIT 1', (session['id'],))
        if not row:
            raise ApiError(422, 'camera_sample', 'Start the camera first.')
        try:
            trace = await current_camera_trace(session)
        except bank24_camera_risk.CameraRiskUnavailable as exc:
            raise ApiError(422, 'camera_sample', str(exc)) from exc
        samples = trace.get('samples') or []
        start_ms = float(samples[-1]['t']) if samples else 0.0
        now = time.time()
        db.execute('''INSERT INTO camera_enrollment_attempts(participant,bank_session,camera_id,start_ms,started_at)
                      VALUES(?,?,?,?,?) ON CONFLICT(participant,bank_session) DO UPDATE SET
                      camera_id=excluded.camera_id,start_ms=excluded.start_ms,started_at=excluded.started_at''',
                   (session['participant'], session['id'], row['id'], start_ms, now))
        return web.json_response(camera_profile_status(session['participant'], session['id']))

    async def camera_profile_enroll(request):
        session = need_session(request, auth=True)
        check_enrollment_session(session)
        attempt = store.one('SELECT camera_id,start_ms,started_at FROM camera_enrollment_attempts WHERE participant=? AND bank_session=?',
                            (session['participant'], session['id']))
        if not attempt:
            raise ApiError(409, 'enrolment_not_started', 'Start a calm sample first.')
        if time.time() - attempt['started_at'] > 600:
            raise ApiError(409, 'enrolment_expired', 'The sample expired. Start a new sample.')
        camera_row = store.one('SELECT id FROM cameras WHERE session=? ORDER BY rowid DESC LIMIT 1', (session['id'],))
        if not camera_row or camera_row['id'] != attempt['camera_id']:
            raise ApiError(409, 'camera_changed', 'The camera was restarted. Start a new sample.')
        data = await body(request)
        if set(data) != {'confirm_calm'} or data['confirm_calm'] is not True:
            raise ApiError(422, 'enrolment_confirmation', 'Explicitly confirm saving the calm sample.')
        try:
            trace = await current_camera_trace(session)
            latest = store.one('SELECT version,profile FROM camera_profile_versions WHERE participant=? AND trusted=1 ORDER BY version DESC LIMIT 1', (session['participant'],))
            sample = await asyncio.get_running_loop().run_in_executor(
                None, bank24_camera_risk.build_enrollment_sample, trace, session['participant'], Path(fusion_repo),
                attempt['start_ms'])
        except bank24_camera_risk.CameraRiskUnavailable as exc:
            raise ApiError(422, 'camera_sample', str(exc)) from exc
        except Exception as exc:
            logging.exception('camera profile enrollment failed')
            raise ApiError(503, 'camera_model', 'The camera profile analysis service is temporarily unavailable.') from exc
        now = time.time()
        approved = int(demo and latest is None)
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('INSERT INTO camera_profile_samples(participant,bank_session,profile,created_at,approved) VALUES(?,?,?,?,?)',
                       (session['participant'], session['id'], pickle.dumps(sample), now, approved))
            db.execute('DELETE FROM camera_enrollment_attempts WHERE participant=? AND bank_session=?',
                       (session['participant'], session['id']))
            if approved:
                save_approved_camera_version(session['participant'], now)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
        return web.json_response(camera_profile_status(session['participant'], session['id']))

    async def admin_camera_candidates(request):
        need_admin(request)
        rows = db.execute('''SELECT s.participant,p.username,s.bank_session,s.created_at
                             FROM camera_profile_samples s JOIN participants p ON p.id=s.participant
                             WHERE s.approved=0 ORDER BY s.created_at,s.bank_session''').fetchall()
        return web.json_response(dict(items=[dict(row) for row in rows]))

    async def admin_camera_candidate_decision(request):
        need_admin(request)
        data = await body(request)
        if set(data) != {'verified'} or data['verified'] is not True:
            raise ApiError(422, 'verification_required', 'Confirm independent owner verification before approving the sample.')
        bank_session = request.match_info['bank_session']
        row = store.one('SELECT participant FROM camera_profile_samples WHERE bank_session=? AND approved=0', (bank_session,))
        if not row:
            raise ApiError(404, 'candidate', 'Pending sample not found.')
        if fusion_repo is None:
            raise ApiError(503, 'model_unavailable', 'Camera model is unavailable.')
        now = time.time()
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('UPDATE camera_profile_samples SET approved=1 WHERE bank_session=? AND approved=0', (bank_session,))
            save_approved_camera_version(row['participant'], now)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
        return web.json_response(camera_profile_status(row['participant'], bank_session))

    async def admin_camera_candidate_reject(request):
        need_admin(request)
        bank_session = request.match_info['bank_session']
        deleted = db.execute('DELETE FROM camera_profile_samples WHERE bank_session=? AND approved=0',
                             (bank_session,)).rowcount
        if not deleted:
            raise ApiError(404, 'candidate', 'Pending sample not found.')
        return web.json_response(dict(ok=True, deleted=True))

    async def preview(request):
        session = need_session(request, auth=True)
        data = await body(request)
        balance = store.one('SELECT balance FROM participants WHERE id=?', (session['participant'],))['balance']
        recipient, number, title, amount = validate_transfer(data, balance)
        transfer_id = uuid.uuid4().hex
        version = 1
        study_session_id = session['study_session']
        study = store.one('SELECT * FROM study_sessions WHERE id=? AND status="running"', (study_session_id,)) if study_session_id else None
        if study:
            if study['stage'] == 'login':
                db.execute('UPDATE study_sessions SET stage="transfer" WHERE id=?', (study['id'],))
                db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], 'transfer', time.time()))
            risk, features = assess_study_session(study['id'], 'transfer')
            save_assessment(study['id'], 'transfer', risk, features)
        else:
            risk, reason = await camera_assess(session)
            if risk_exceeded(session, risk):
                return await risk_logout_response(session, risk)
            if risk is None:
                risk = assess()
                if reason:
                    risk['missing_reasons'].insert(0, reason)
                    risk['reasons'].insert(0, reason)
        if request.match_info.get('id'):
            _, previous = get_transfer(request)
            if previous['status'] in ('completed', 'cancelled', 'held'):
                raise ApiError(409, 'terminal', 'This transaction cannot be changed. Prepare a new transfer.')
            if data.get('version') != previous['version']:
                raise ApiError(409, 'version', 'Open the current transfer version and compare the details.')
            transfer_id, version = previous['id'], previous['version'] + 1
            study_session_id = previous['study_session'] or study_session_id
            db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer_id,))
            db.execute('UPDATE transfers SET version=?,recipient=?,number=?,title=?,amount_grosz=?,status="review",risk=?,study_session=?,risk_acknowledged=0 WHERE id=?', (version, recipient, number, title, amount, json.dumps(risk), study_session_id, transfer_id))
        else:
            db.execute('INSERT INTO transfers(id,participant,study_session,version,recipient,number,title,amount_grosz,status,risk,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (transfer_id, session['participant'], study_session_id, version, recipient, number, title, amount, 'review', json.dumps(risk), datetime.now(timezone.utc).isoformat()))
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer_id,))), status=201)

    async def transfer_get(request):
        _, transfer = get_transfer(request)
        return web.json_response(transfer_data(transfer))

    async def intervention(request):
        session, transfer = get_transfer(request)
        data = await body(request)
        if set(data) - {'version', 'independent', 'compared', 'risk_acknowledged'}:
            raise ApiError(422, 'review', 'The request contains unsupported fields.')
        if transfer['status'] != 'review' or data.get('version') != transfer['version']:
            raise ApiError(409, 'state', 'Read the current transfer status.')
        if type(data.get('independent')) is not bool or data.get('compared') is not True:
            raise ApiError(422, 'review', 'Compare the details and answer whether this is your own decision.')
        acknowledged = data.get('risk_acknowledged', False)
        if type(acknowledged) is not bool:
            raise ApiError(422, 'review', 'Invalid response to the additional check.')
        risk = json.loads(transfer['risk'])
        if data['independent'] and (risk.get('coercion_risk') or 0) >= 70 and not acknowledged:
            raise ApiError(422, 'risk_acknowledgement', 'Independently verify the recipient through an official channel before continuing.')
        # A declaration of pressure is a server-enforced hold. "No" cannot undo it.
        next_status = 'ready' if data['independent'] else 'held'
        db.execute('UPDATE transfers SET status=?,risk_acknowledged=? WHERE id=?', (next_status, int(acknowledged), transfer['id']))
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer['id'],))))

    async def transaction_challenge(request):
        session, transfer = get_transfer(request)
        if transfer['status'] != 'ready':
            raise ApiError(409, 'state', 'Review the transfer details first.')
        if request.method == 'GET':
            challenge = store.one('SELECT * FROM challenges WHERE transfer_id=? AND session=? AND version=? AND used=0 ORDER BY created DESC LIMIT 1', (transfer['id'], session['id'], transfer['version']))
            if challenge:
                return web.json_response(dict(challenge_id=challenge['id'], expires_at=challenge['expires'], resend_at=challenge['created'] + 30, demo_mode=demo, code_length=4 if demo else 6))
            raise ApiError(404, 'no_challenge', 'Request a confirmation code for this transfer.')
        return web.json_response(await make_challenge(session, 'transfer', transfer))

    async def submit(request):
        session, transfer = get_transfer(request)
        data = await body(request)
        key = request.headers.get('Idempotency-Key', '')
        if len(key) < 16 or len(key) > 128:
            raise ApiError(400, 'idempotency', 'Missing confirmation ID.')
        if transfer['status'] == 'completed':
            return web.json_response(transfer_data(transfer))
        if transfer['status'] != 'ready' or data.get('version') != transfer['version']:
            raise ApiError(409, 'state', 'The transfer is not ready to send. Check its status.')
        if transfer['study_session']:
            study = store.one('SELECT status FROM study_sessions WHERE id=?', (transfer['study_session'],))
            if study and study['status'] == 'running':
                fresh_risk, fresh_features = assess_study_session(transfer['study_session'], 'transfer')
                save_assessment(transfer['study_session'], 'submit', fresh_risk, fresh_features)
                db.execute('UPDATE transfers SET risk=? WHERE id=?', (json.dumps(fresh_risk), transfer['id']))
                if (fresh_risk.get('coercion_risk') or 0) >= 70 and not transfer['risk_acknowledged']:
                    db.execute('UPDATE transfers SET status="review",risk_acknowledged=0 WHERE id=?', (transfer['id'],))
                    db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer['id'],))
                    raise ApiError(409, 'risk_review', 'New data requires checking the recipient again before sending.')
        challenge = check_challenge(session, data, 'transfer', transfer)
        if session['id'] in forced_mismatch:
            _, pending = alarm_state(session)
            if not pending:
                risk, _ = await camera_assess(session)
                return await risk_logout_response(session, risk)
            # The alarm takes effect a few seconds later; the transfer is held and never executed.
            db.execute('UPDATE transfers SET status="review",risk_acknowledged=0 WHERE id=?', (transfer['id'],))
            db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer['id'],))
            raise ApiError(409, 'transfer_held', 'The transfer was held for additional verification. Do not close the page.')
        now = datetime.now(timezone.utc).isoformat()
        db.execute('BEGIN IMMEDIATE')
        try:
            changed = db.execute('UPDATE participants SET balance=balance-? WHERE id=? AND balance>=?', (transfer['amount_grosz'], session['participant'], transfer['amount_grosz'])).rowcount
            if not changed:
                raise ApiError(422, 'balance', 'Insufficient funds. Go back and edit the amount.')
            db.execute('UPDATE transfers SET status="completed",confirmed=?,idempotency=? WHERE id=?', (now, key, transfer['id']))
            db.execute('UPDATE challenges SET used=1 WHERE id=?', (challenge['id'],))
            db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', (transfer['id'], session['participant'], transfer['recipient'], transfer['title'], -transfer['amount_grosz'], now, 'completed'))
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer['id'],))))

    async def cancel(request):
        _, transfer = get_transfer(request)
        if transfer['status'] == 'completed':
            raise ApiError(409, 'terminal', 'A completed transfer cannot be canceled.')
        db.execute('UPDATE transfers SET status="cancelled" WHERE id=?', (transfer['id'],))
        db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer['id'],))
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer['id'],))))

    async def telemetry(request):
        session = need_session(request, telemetry=True)
        if not session['telemetry']:
            raise ApiError(403, 'telemetry_consent', 'Behavioral measurement is disabled.')
        study_session_id = session['study_session']
        if study_session_id:
            study = store.one('SELECT status,telemetry_allowed FROM study_sessions WHERE id=? AND study_participant=?', (study_session_id, session['study_participant']))
            if not study or study['status'] != 'running':
                raise ApiError(409, 'study_session', 'The study session no longer accepts telemetry.')
            if not study['telemetry_allowed']:
                raise ApiError(403, 'telemetry_consent', 'The participant has not consented to telemetry in this session.')
        data = await body(request)
        page = str(data.get('page', ''))
        events = data.get('events')
        anchor = data.get('page_anchor_ms', 0)
        if type(anchor) not in (int, float) or not math.isfinite(anchor) or not 0 <= anchor <= 1e15:
            raise ApiError(422, 'telemetry', 'Invalid page time anchor.')
        if not 1 <= len(page) <= 64 or not isinstance(events, list) or len(events) > 100:
            raise ApiError(422, 'telemetry', 'Invalid metadata batch.')
        allowed = {'sequence', 'time_ms', 'type', 'stage', 'field', 'length', 'duration_ms', 'x', 'y', 'width', 'height', 'delta_y', 'env', 'status', 'keys', 'features'}
        stages = {'login', 'transfer'}
        fields = {'username', 'password', 'recipient', 'number', 'title', 'amount', 'none'}
        for event in events:
            if not isinstance(event, dict) or set(event) - allowed or type(event.get('sequence')) is not int or event['sequence'] < 0 or event.get('stage') not in stages or event.get('type') not in ('input', 'correction', 'pointer', 'focus', 'key_press', 'key_dwell', 'keyboard_window', 'environment', 'ping', 'server_request', 'pointerdown', 'pointerup', 'click', 'wheel', 'paste', 'copy', 'cut', 'window_blur', 'hidden') or event.get('field') not in fields:
                raise ApiError(422, 'telemetry', 'The batch contains disallowed data.')
            for name in ('time_ms', 'length', 'duration_ms', 'x', 'y'):
                value = event.get(name, 0)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e10:
                    raise ApiError(422, 'telemetry', 'Invalid metadata value.')
            if event.get('type') == 'key_dwell' and ('duration_ms' not in event or event['duration_ms'] > 5000):
                raise ApiError(422, 'telemetry', 'Invalid key-press timestamp.')
            if event.get('type') in ('pointer', 'pointerdown', 'pointerup', 'click') and not (0 <= event.get('x', -1) <= 1 and 0 <= event.get('y', -1) <= 1):
                raise ApiError(422, 'telemetry', 'Pointer coordinates must be normalized to the 0–1 range.')
            if event.get('type') == 'input' and event.get('length', 0) > 4096:
                raise ApiError(422, 'telemetry', 'Field-length metadata is outside the allowed range.')
        for event in events:
            extras = set(event) & {'env', 'keys', 'features', 'status'}
            permitted = {'environment': {'env'}, 'keyboard_window': {'keys', 'features'}, 'server_request': {'status'}}.get(event['type'], set())
            if extras - permitted:
                raise ApiError(422, 'telemetry', 'Unexpected metadata fields.')
            if event['type'] == 'environment':
                env = event.get('env')
                if not isinstance(env, dict) or set(env) - {'platform', 'userAgent', 'screen', 'devicePixelRatio', 'timezone', 'language', 'hardwareConcurrency', 'maxTouchPoints'}:
                    raise ApiError(422, 'telemetry', 'Invalid environment metadata.')
                if any(not isinstance(v, (str, int, float, dict)) or len(str(v)) > 512 for v in env.values()):
                    raise ApiError(422, 'telemetry', 'Invalid environment value.')
                screen = env.get('screen', {})
                if not isinstance(screen, dict) or set(screen) - {'width', 'height'} or any(type(v) is not int or not 0 < v <= 100000 for v in screen.values()):
                    raise ApiError(422, 'telemetry', 'Invalid screen metadata.')
            for name in ('width', 'height', 'status', 'delta_y'):
                v = event.get(name, 0)
                if type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000:
                    raise ApiError(422, 'telemetry', 'Invalid pointer or connection metadata.')
            if event['type'] == 'keyboard_window':
                keys, features = event.get('keys'), event.get('features')
                if event['field'] == 'password' or not isinstance(keys, list) or event.get('length') != len(keys) or 'duration_ms' not in event or not 16 <= len(keys) <= 96 or any(type(k) is not int or not 0 <= k < 32768 for k in keys) or not isinstance(features, list) or len(features) != len(keys) or any(not isinstance(f, list) or len(f) != 8 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 20 for v in f) for f in features):
                    raise ApiError(422, 'telemetry', 'Invalid keyboard feature window.')
        inserted = 0
        for event in events:
            if event['type'] == 'keyboard_window':
                bank24_camera_risk._import_model(Path(fusion_repo or Path(__file__).resolve().parents[1] / 'research'))
                from bank24_inputs import encode_keyboard
                try:
                    embedding = await asyncio.to_thread(encode_keyboard, event['keys'], event['features'])
                except (ValueError, OSError) as exc:
                    raise ApiError(503, 'keyboard_model', str(exc)) from exc
                event = {k: v for k, v in event.items() if k not in ('keys', 'features')}
                event.update(type='keyboard_embedding', embedding=embedding)

            inserted += db.execute('INSERT OR IGNORE INTO telemetry(session,study_session,page,sequence,event) VALUES(?,?,?,?,?)',
                                   (session['id'], study_session_id, page, event['sequence'], json.dumps({**event, 'page_anchor_ms': anchor, 'received_at': time.time()}))).rowcount
        return web.json_response(dict(accepted=inserted, duplicates=len(events) - inserted))

    async def survey(request):
        session = need_session(request, auth=True)
        data = await body(request)
        if type(data.get('rating')) is not int or not 1 <= data['rating'] <= 5 or len(str(data.get('comment', ''))) > 500:
            raise ApiError(422, 'survey', 'Choose a rating from 1 to 5. Comments may contain up to 500 characters.')
        db.execute('INSERT OR REPLACE INTO surveys VALUES(?,?,?)', (session['id'], data['rating'], str(data.get('comment', ''))))
        return web.json_response(dict(ok=True))

    async def resolve_study_code(request):
        session = need_session(request)
        if session['authenticated']:
            raise ApiError(409, 'study_login', 'Link the study code before signing in to Bank24.')
        if session['study_session']:
            active = store.one('SELECT 1 FROM study_sessions WHERE id=? AND status IN ("created","running")', (session['study_session'],))
            if active:
                raise ApiError(409, 'study_session_active', 'Finish or abort the current session before changing the participant code.')
        data = await body(request)
        code = str(data.get('code', '')).strip()
        if not 8 <= len(code) <= 128:
            raise ApiError(422, 'study_code', 'Enter the participant code provided by the facilitator.')
        participant = store.one('SELECT id,label FROM study_participants WHERE code_hash=? AND withdrawn=0', (digest(code),))
        if not participant:
            raise ApiError(404, 'study_code', 'No active participation found for this code.')
        db.execute('UPDATE sessions SET study_participant=? WHERE id=?', (participant['id'], session['id']))
        return web.json_response(dict(ok=True, participant_label=participant['label']))

    async def study_consent(request):
        session = need_session(request)
        if not session['study_participant']:
            raise ApiError(409, 'study_code', 'Confirm the participant code first.')
        active_study = store.one('SELECT 1 FROM study_sessions WHERE id=? AND status IN ("created","running")', (session['study_session'],)) if session['study_session'] else None
        if active_study:
            raise ApiError(409, 'study_consent_locked', 'During an active session, consent can only be withdrawn through permission settings.')
        participant = store.one('SELECT id,withdrawn FROM study_participants WHERE id=?', (session['study_participant'],))
        if not participant or participant['withdrawn']:
            raise ApiError(410, 'withdrawn', 'Study participation has been withdrawn.')
        data = await body(request)
        if set(data) - {'telemetry', 'camera', 'recording'} or type(data.get('telemetry')) is not bool or type(data.get('camera')) is not bool:
            raise ApiError(422, 'consent', 'Choose telemetry and camera transmission consent separately.')
        if data.get('recording', False) is not False:
            raise ApiError(422, 'consent', 'Saving recordings is not available in this version.')
        db.execute('UPDATE sessions SET consent=?,telemetry=?,camera_consent=? WHERE id=?',
                   (int(data['telemetry']), int(data['telemetry']), int(data['camera']), session['id']))
        consent_version = store.one('SELECT COALESCE(MAX(version),0)+1 version FROM study_consents WHERE study_participant=?', (participant['id'],))['version']
        db.execute('INSERT INTO study_consents(id,study_participant,bank_session,telemetry,camera,recording,version,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex, participant['id'], session['id'], int(data['telemetry']), int(data['camera']), 0, consent_version, time.time()))
        if not data['camera']:
            await close_cameras(session)
        return web.json_response(dict(ok=True, telemetry=data['telemetry'], camera=data['camera'], recording=False))

    async def create_study_session(request):
        session = need_session(request)
        if not session['study_participant']:
            raise ApiError(409, 'study_code', 'Confirm the participant code first.')
        participant = store.one('SELECT * FROM study_participants WHERE id=? AND withdrawn=0', (session['study_participant'],))
        if not participant:
            raise ApiError(410, 'withdrawn', 'Study participation has been withdrawn.')
        consent = store.one('SELECT * FROM study_consents WHERE study_participant=? AND bank_session=? ORDER BY created_at DESC LIMIT 1', (participant['id'], session['id']))
        if not consent:
            raise ApiError(409, 'consent_required', 'Save consent or refusal before starting the session.')
        if store.one('SELECT 1 FROM study_sessions WHERE study_participant=? AND status IN ("created","running")', (participant['id'],)):
            raise ApiError(409, 'study_session_active', 'The participant already has an active study session.')
        assignment = store.one('SELECT * FROM study_assignments WHERE study_participant=? AND status="assigned" ORDER BY created_at,id LIMIT 1', (participant['id'],))
        if not assignment:
            raise ApiError(409, 'scenario_unassigned', 'The facilitator has not assigned a scenario yet.')
        data = await body(request)
        if data:
            raise ApiError(422, 'study_session', 'The facilitator selects the scenario; the request accepts no fields.')
        study_id = uuid.uuid4().hex
        now = time.time()
        db.execute('INSERT INTO study_sessions(id,study_participant,bank_participant,assignment_id,scenario,status,stage,telemetry_allowed,camera_allowed,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (study_id, participant['id'], participant['bank_participant'], assignment['id'], assignment['scenario'], 'created', 'login', consent['telemetry'], consent['camera'], now))
        db.execute('UPDATE study_assignments SET status="used",used_at=? WHERE id=?', (now, assignment['id']))
        db.execute('UPDATE sessions SET study_session=? WHERE id=?', (study_id, session['id']))
        return web.json_response(dict(id=study_id, status='created', stage='login', scenario=assignment['scenario'], telemetry=bool(consent['telemetry']), camera=bool(consent['camera'])), status=201)

    async def start_study_session(request):
        session, study = get_study_session(request, request.match_info['id'])
        if study['status'] != 'created':
            raise ApiError(409, 'study_state', 'A session can only be started once after creation.')
        now = time.time()
        db.execute('UPDATE study_sessions SET status="running",started_at=? WHERE id=?', (now, study['id']))
        db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], 'login', now))
        return web.json_response(dict(id=study['id'], status='running', stage='login'))

    async def set_study_stage(request):
        session, study = get_study_session(request, request.match_info['id'])
        if study['status'] != 'running':
            raise ApiError(409, 'study_state', 'The stage can only be changed in an active session.')
        data = await body(request)
        stage = data.get('stage')
        order = {'login': 0, 'transfer': 1, 'result': 2}
        if set(data) != {'stage'} or not isinstance(stage, str) or stage not in order:
            raise ApiError(422, 'study_stage', 'Available stages are login, transfer and result.')
        current = order.get(study['stage'], -1)
        if order[stage] < current or order[stage] > current + 1:
            raise ApiError(409, 'study_stage', 'Study stages must be completed in order.')
        if stage != study['stage']:
            now = time.time()
            db.execute('UPDATE study_sessions SET stage=? WHERE id=?', (stage, study['id']))
            db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], stage, now))
        return web.json_response(dict(id=study['id'], status=study['status'], stage=stage))

    async def complete_study_session(request):
        session, study = get_study_session(request, request.match_info['id'])
        if study['status'] != 'running':
            raise ApiError(409, 'study_state', 'Only an active session can be finished.')
        now = time.time()
        db.execute('UPDATE study_sessions SET status="completed",ended_at=? WHERE id=?', (now, study['id']))
        db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], 'complete', now))
        await close_cameras(session)
        db.execute('UPDATE sessions SET consent=0,telemetry=0,camera_consent=0 WHERE id=?', (session['id'],))
        profiles = []
        if study['scenario'] == 'calm_owner' and study['telemetry_allowed']:
            profiles = [rebuild_owner_profile(db, study['bank_participant'], stage) for stage in ('login', 'transfer')]
        assessment, features = assess_study_session(study['id'], 'result')
        save_assessment(study['id'], 'complete', assessment, features)
        return web.json_response(dict(id=study['id'], status='completed', telemetry=False, camera=False, profiles=profiles, assessment=assessment))

    async def abort_study_session(request):
        session, study = get_study_session(request, request.match_info['id'])
        if study['status'] not in ('created', 'running'):
            raise ApiError(409, 'study_state', 'A finished session cannot be aborted.')
        data = await body(request)
        reason = str(data.get('reason', '')).strip()[:300]
        now = time.time()
        db.execute('UPDATE study_sessions SET status="aborted",ended_at=?,abort_reason=? WHERE id=?', (now, reason, study['id']))
        db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], 'abort', now))
        await close_cameras(session)
        db.execute('UPDATE sessions SET consent=0,telemetry=0,camera_consent=0 WHERE id=?', (session['id'],))
        return web.json_response(dict(id=study['id'], status='aborted', telemetry=False, camera=False))

    async def admin_scenarios(request):
        need_admin(request)
        return web.json_response(dict(items=[dict(id=key, label=value) for key, value in STUDY_SCENARIOS.items()]))

    async def admin_profiles(request):
        need_admin(request)
        bank_username = request.query.get('bank_username')
        where = ''
        params = []
        if bank_username:
            where = 'WHERE p.username=?'
            params.append(bank_username[:100])
        rows = db.execute(
            '''SELECT op.bank_participant,p.username,op.stage,op.version,op.observations,
                      op.ready,op.features,op.modalities,op.updated_at
               FROM owner_profiles op JOIN participants p ON p.id=op.bank_participant ''' + where +
            ' ORDER BY p.username,op.stage',
            params,
        ).fetchall()
        return web.json_response(dict(items=[{
            'bank_participant': row['bank_participant'],
            'bank_username': row['username'],
            'stage': row['stage'],
            'version': row['version'],
            'observations': row['observations'],
            'ready': bool(row['ready']),
            'features': json.loads(row['features']),
            'modalities': json.loads(row['modalities']),
            'updated_at': row['updated_at'],
        } for row in rows]))

    async def admin_participants(request):
        need_admin(request)
        if request.method == 'POST':
            data = await body(request)
            if set(data) - {'label', 'role', 'bank_username', 'username', 'password', 'starting_balance_grosz'}:
                raise ApiError(422, 'participant', 'The request contains unsupported fields.')
            label = str(data.get('label', '')).strip()
            if not 1 <= len(label) <= 100:
                raise ApiError(422, 'participant', 'The participant label must contain 1–100 characters.')
            role = data.get('role', 'operator')
            if role not in ('owner', 'operator'):
                raise ApiError(422, 'participant', 'Participant role must be owner or operator.')
            bank_username = str(data.get('bank_username', '')).strip()[:100]
            if bank_username:
                bank = store.one('SELECT id,username FROM participants WHERE username=?', (bank_username,))
                if not bank:
                    raise ApiError(404, 'bank_account', 'The specified fictional Bank24 account was not found.')
                if data.get('username') is not None or data.get('password') is not None:
                    raise ApiError(422, 'participant', 'Do not provide a username or password again for an existing account.')
                bank_id, bank_username = bank['id'], bank['username']
            else:
                username = str(data.get('username', '')).strip()[:100]
                password = str(data.get('password', ''))
                balance = data.get('starting_balance_grosz', 0)
                if not 3 <= len(username) <= 100 or len(password) < 8 or len(password) > 256:
                    raise ApiError(422, 'participant', 'A new account requires a username (3–100 characters) and password (8–256 characters).')
                if type(balance) is not int or not 0 <= balance <= 100_000_000_000:
                    raise ApiError(422, 'participant', 'The opening balance must be a nonnegative integer number of grosz.')
                bank_id = uuid.uuid4().hex
                salt = secrets.token_hex(16)
                try:
                    db.execute('INSERT INTO participants(id,code_hash,username,salt,password,balance) VALUES(?,?,?,?,?,?)',
                               (bank_id, None, username, salt, password_hash(password, salt), balance))
                except sqlite3.IntegrityError:
                    raise ApiError(409, 'username', 'This Bank24 username is already taken.')
                bank_username = username
            participant_id = uuid.uuid4().hex
            code = secrets.token_urlsafe(16)
            db.execute('INSERT INTO study_participants(id,code_hash,label,role,bank_participant,created_at) VALUES(?,?,?,?,?,?)',
                       (participant_id, digest(code), label, role, bank_id, time.time()))
            return web.json_response(dict(id=participant_id, label=label, role=role, bank_username=bank_username, study_code=code), status=201)

        rows = db.execute(
            '''SELECT sp.id,sp.label,sp.role,sp.bank_participant,sp.created_at,sp.withdrawn,p.username,
                      (SELECT COUNT(*) FROM study_assignments a WHERE a.study_participant=sp.id AND a.status='assigned') pending_assignments,
                      (SELECT COUNT(*) FROM study_sessions ss WHERE ss.study_participant=sp.id) session_count
               FROM study_participants sp JOIN participants p ON p.id=sp.bank_participant
               ORDER BY sp.created_at DESC'''
        ).fetchall()
        return web.json_response(dict(items=[dict(row) for row in rows]))

    async def admin_assignments(request):
        need_admin(request)
        participant_id = request.match_info['id']
        participant = store.one('SELECT id,role,withdrawn FROM study_participants WHERE id=?', (participant_id,))
        if not participant:
            raise ApiError(404, 'participant', 'Participant not found.')
        if participant['withdrawn']:
            raise ApiError(410, 'withdrawn', 'The participant withdrew participation.')
        data = await body(request)
        scenario = data.get('scenario')
        if set(data) != {'scenario'} or not isinstance(scenario, str) or scenario not in STUDY_SCENARIOS:
            raise ApiError(422, 'scenario', 'Choose an available scenario.')
        if scenario == 'calm_owner' and participant['role'] != 'owner':
            raise ApiError(422, 'scenario', 'A baseline profile can only be collected from a participant marked as the owner by the operator.')
        assignment_id = uuid.uuid4().hex
        db.execute('INSERT INTO study_assignments(id,study_participant,scenario,status,created_at) VALUES(?,?,?,?,?)',
                   (assignment_id, participant_id, scenario, 'assigned', time.time()))
        return web.json_response(dict(id=assignment_id, participant_id=participant_id, scenario=scenario, label=STUDY_SCENARIOS[scenario], status='assigned'), status=201)

    async def admin_sessions(request):
        need_admin(request)
        try:
            offset = max(0, int(request.query.get('offset', '0')))
            limit = min(100, max(1, int(request.query.get('limit', '30'))))
        except ValueError:
            raise ApiError(400, 'pagination', 'Invalid session range.')
        participant_id = request.query.get('participant_id')
        where = ''
        params = []
        if participant_id:
            where = 'WHERE ss.study_participant=?'
            params.append(participant_id)
        total = store.one('SELECT COUNT(*) total FROM study_sessions ss ' + where, params)['total']
        rows = db.execute(
            '''SELECT ss.id,ss.study_participant,sp.label,ss.bank_participant,p.username,
                      ss.scenario,ss.status,ss.stage,ss.telemetry_allowed,ss.camera_allowed,
                      ss.created_at,ss.started_at,ss.ended_at
               FROM study_sessions ss JOIN study_participants sp ON sp.id=ss.study_participant
               JOIN participants p ON p.id=ss.bank_participant ''' + where +
            ' ORDER BY ss.created_at DESC,ss.id LIMIT ? OFFSET ?', (*params, limit, offset)
        ).fetchall()
        return web.json_response(dict(items=[dict(row) for row in rows], total=total, offset=offset, limit=limit))

    async def admin_session_detail(request):
        need_admin(request)
        study_id = request.match_info['id']
        study = store.one(
            '''SELECT ss.*,sp.label,p.username FROM study_sessions ss
               JOIN study_participants sp ON sp.id=ss.study_participant
               JOIN participants p ON p.id=ss.bank_participant WHERE ss.id=?''',
            (study_id,),
        )
        if not study:
            raise ApiError(404, 'study_session', 'Study session not found.')
        stages = {}
        for stage in ('login', 'transfer'):
            stages[stage] = extract_features(db, study_id, stage)
        risks = [dict(row) for row in db.execute('SELECT id,stage,assessment,features,created_at FROM risk_assessments WHERE study_session=? ORDER BY created_at,id', (study_id,))]
        for risk in risks:
            risk['assessment'] = json.loads(risk['assessment'])
            risk['features'] = json.loads(risk['features'])
        events = [dict(row) for row in db.execute('SELECT page,sequence,event FROM telemetry WHERE study_session=? ORDER BY page,sequence', (study_id,))]
        for event in events:
            event['event'] = json.loads(event['event'])
        result = dict(study)
        result['scenario_label'] = STUDY_SCENARIOS.get(study['scenario'], study['scenario'])
        result['features'] = stages
        result['risk_assessments'] = risks
        result['events'] = events
        result['stage_history'] = [dict(row) for row in db.execute('SELECT stage,created_at FROM study_stage_events WHERE study_session=? ORDER BY created_at,id', (study_id,))]
        return web.json_response(result)

    async def admin_export(request):
        need_admin(request)
        data = await body(request)
        if set(data) - {'participant_id', 'session_id'}:
            raise ApiError(422, 'export', 'JSON export is available with an optional participant or session filter.')
        participant_id = data.get('participant_id')
        session_id = data.get('session_id')
        if participant_id and session_id:
            raise ApiError(422, 'export', 'Choose a participant or session filter.')
        if participant_id is not None and (not isinstance(participant_id, str) or len(participant_id) > 64):
            raise ApiError(422, 'export', 'Invalid participant ID.')
        if session_id is not None and (not isinstance(session_id, str) or len(session_id) > 64):
            raise ApiError(422, 'export', 'Invalid session ID.')
        if session_id:
            session_ids = [str(session_id)]
        elif participant_id:
            session_ids = [row['id'] for row in db.execute('SELECT id FROM study_sessions WHERE study_participant=? ORDER BY created_at,id', (participant_id,))]
        else:
            session_ids = [row['id'] for row in db.execute('SELECT id FROM study_sessions ORDER BY created_at,id')]
        if len(session_ids) > 5000:
            raise ApiError(413, 'export_limit', 'Exports may contain up to 5000 sessions; use a participant filter.')
        event_count = sum(store.one('SELECT COUNT(*) count FROM telemetry WHERE study_session=?', (study_id,))['count'] for study_id in session_ids)
        if event_count > 250000:
            raise ApiError(413, 'export_limit', 'Exports may contain up to 250,000 events; apply a filter.')
        items = []
        bank_ids = set()
        for study_id in session_ids:
            study = store.one('SELECT * FROM study_sessions WHERE id=?', (study_id,))
            if not study:
                continue
            bank_ids.add(study['bank_participant'])
            events = [dict(row) for row in db.execute('SELECT page,sequence,event FROM telemetry WHERE study_session=? ORDER BY page,sequence', (study_id,))]
            for item in events:
                item['event'] = json.loads(item['event'])
            risks = [dict(row) for row in db.execute('SELECT stage,assessment,features,created_at FROM risk_assessments WHERE study_session=? ORDER BY created_at,id', (study_id,))]
            for risk in risks:
                risk['assessment'] = json.loads(risk['assessment'])
                risk['features'] = json.loads(risk['features'])
            items.append({
                'session': dict(study),
                'features': {stage: extract_features(db, study_id, stage) for stage in ('login', 'transfer')},
                'events': events,
                'risk_assessments': risks,
            })
        profiles = []
        for bank_id in sorted(bank_ids):
            for row in db.execute('SELECT stage,version,observations,features,modalities,ready,updated_at FROM owner_profiles WHERE bank_participant=? ORDER BY stage', (bank_id,)):
                profiles.append({
                    'bank_participant': bank_id,
                    'stage': row['stage'],
                    'version': row['version'],
                    'observations': row['observations'],
                    'features': json.loads(row['features']),
                    'modalities': json.loads(row['modalities']),
                    'ready': bool(row['ready']),
                    'updated_at': row['updated_at'],
                })
        payload = json.dumps({'schema_version': 1, 'model_version': MODEL_VERSION, 'profiles': profiles, 'sessions': items}, ensure_ascii=False, indent=2)
        response = web.Response(text=payload, content_type='application/json')
        response.headers['Content-Disposition'] = 'attachment; filename="bank24-study-export.json"'
        return response

    async def risk_latest(request):
        session, study = get_study_session(request, request.match_info['id'])
        row = store.one('SELECT assessment FROM risk_assessments WHERE study_session=? ORDER BY created_at DESC,id DESC LIMIT 1', (study['id'],))
        if row:
            return web.json_response(json.loads(row['assessment']))
        assessment, features = assess_study_session(study['id'], study['stage'])
        return web.json_response(assessment)

    async def risk_timeline(request):
        session, study = get_study_session(request, request.match_info['id'])
        rows = db.execute('SELECT stage,assessment,features,created_at FROM risk_assessments WHERE study_session=? ORDER BY created_at,id', (study['id'],)).fetchall()
        return web.json_response(dict(items=[dict(stage=row['stage'], assessment=json.loads(row['assessment']), features=json.loads(row['features']), created_at=row['created_at']) for row in rows]))

    async def withdraw_participant_data(participant_id):
        participant = store.one('SELECT bank_participant FROM study_participants WHERE id=?', (participant_id,))
        if not participant:
            raise ApiError(404, 'participant', 'Study participant not found.')
        bank_id = participant['bank_participant']
        study_ids = [row['id'] for row in db.execute('SELECT id FROM study_sessions WHERE study_participant=?', (participant_id,))]
        auth_sessions = [row['id'] for row in db.execute('SELECT id FROM sessions WHERE study_participant=?', (participant_id,))]
        for bank_session in auth_sessions:
            row = store.one('SELECT * FROM sessions WHERE id=?', (bank_session,))
            if row:
                await close_cameras(row)
        for study_id in study_ids:
            db.execute('DELETE FROM telemetry WHERE study_session=?', (study_id,))
            db.execute('DELETE FROM risk_assessments WHERE study_session=?', (study_id,))
            db.execute('DELETE FROM study_stage_events WHERE study_session=?', (study_id,))
            db.execute('UPDATE transfers SET study_session=NULL,risk=? WHERE study_session=?', (json.dumps(assess()), study_id))
        db.execute('DELETE FROM surveys WHERE session IN (SELECT id FROM sessions WHERE study_participant=?)', (participant_id,))
        db.execute('UPDATE sessions SET study_participant=NULL,study_session=NULL,consent=0,telemetry=0,camera_consent=0 WHERE study_participant=?', (participant_id,))
        db.execute('DELETE FROM study_sessions WHERE study_participant=?', (participant_id,))
        db.execute('DELETE FROM study_assignments WHERE study_participant=?', (participant_id,))
        db.execute('DELETE FROM study_consents WHERE study_participant=?', (participant_id,))
        db.execute('DELETE FROM study_participants WHERE id=?', (participant_id,))
        profiles = [rebuild_owner_profile(db, bank_id, stage) for stage in ('login', 'transfer')]
        return profiles

    async def study_withdraw(request):
        session = need_session(request)
        participant_id = request.match_info['id']
        if session['study_participant'] != participant_id:
            raise ApiError(404, 'participant', 'Active participation not found.')
        profiles = await withdraw_participant_data(participant_id)
        return web.json_response(dict(ok=True, deleted=True, profiles=profiles))

    async def admin_withdraw(request):
        need_admin(request)
        profiles = await withdraw_participant_data(request.match_info['id'])
        return web.json_response(dict(ok=True, deleted=True, profiles=profiles))

    async def admin_abort_study_session(request):
        need_admin(request)
        study_id = request.match_info['id']
        study = store.one('SELECT status FROM study_sessions WHERE id=?', (study_id,))
        if not study:
            raise ApiError(404, 'study_session', 'Study session not found.')
        if study['status'] not in ('created', 'running'):
            raise ApiError(409, 'study_state', 'The session is not active.')
        data = await body(request)
        reason = str(data.get('reason', 'aborted by operator')).strip()[:300]
        now = time.time()
        db.execute('UPDATE study_sessions SET status="aborted",ended_at=?,abort_reason=? WHERE id=?', (now, reason, study_id))
        db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study_id, 'abort', now))
        for bank_session in db.execute('SELECT * FROM sessions WHERE study_session=?', (study_id,)).fetchall():
            await close_cameras(bank_session)
            db.execute('UPDATE sessions SET consent=0,telemetry=0,camera_consent=0 WHERE id=?', (bank_session['id'],))
        return web.json_response(dict(id=study_id, status='aborted'))

    async def device_revoke(request):
        session = need_session(request, auth=True)
        db.execute('DELETE FROM devices WHERE token_hash=? AND participant=?', (digest(request.cookies.get('bank24_device', '')), session['participant']))
        response = web.json_response(dict(ok=True))
        response.del_cookie('bank24_device')
        return response

    async def close_cameras(session):
        ids = [row['id'] for row in db.execute('SELECT id FROM cameras WHERE session=?', (session['id'],))]
        for camera_id in ids:
            try:
                target = '/api/frames/sessions/' if camera_id.startswith('frame-') else '/api/sessions/'
                async with app['http'].delete(camera_url + target + camera_id):
                    pass
            except (OSError, asyncio.TimeoutError):
                pass
        db.execute('DELETE FROM cameras WHERE session=?', (session['id'],))

    RISK_MESSAGE = ('A significant mismatch with the account owner profile was detected.\nFor security reasons '
                    'we stopped data entry and will sign you out shortly.')

    def risk_exceeded(session, risk):
        # Camera-only inference is not validated for automatic lockout. Keep the
        # deliberately forced demo alarm, and reserve real lockout for a validated model.
        return (risk_logout is not None and risk is not None and
                (risk.get('validated') is True or session['id'] in forced_mismatch) and
                any((risk.get(key) or 0) >= risk_logout for key in ('account_takeover_risk', 'coercion_risk')))

    async def risk_logout_response(session, risk):
        """End the session after the camera model reports a high profile mismatch."""
        logging.warning('risk logout: participant=%s not_owner=%s pressure=%s forced=%s', session['participant'],
                        risk['account_takeover_risk'], risk['coercion_risk'], session['id'] in forced_mismatch)
        await end_session(session)
        db.execute('UPDATE transfers SET status="cancelled" WHERE participant=? AND status IN ("review","ready")', (session['participant'],))
        db.execute('UPDATE challenges SET used=1 WHERE transfer_id IN (SELECT id FROM transfers WHERE participant=? AND status="cancelled")', (session['participant'],))
        response = web.json_response(dict(code='anomaly_detected', message=RISK_MESSAGE,
                                          account_takeover_risk=risk['account_takeover_risk']), status=403)
        response.del_cookie('bank24_session')
        return response

    async def risk_check(request):
        session = need_session(request, auth=True)
        risk, reason = await camera_assess(session)
        if risk_exceeded(session, risk):
            return await risk_logout_response(session, risk)
        _, pending = alarm_state(session)
        return web.json_response(dict(status='ok' if risk else 'insufficient_data', limit=risk_logout,
                                      account_takeover_risk=risk and risk['account_takeover_risk'], reason=reason,
                                      available_signals=risk['available_signals'] if risk else [],
                                      retry_after=round(pending, 2) if pending else None))

    async def logout(request):
        session = need_session(request)
        await end_session(session)
        response = web.json_response(dict(ok=True))
        response.del_cookie('bank24_session')
        return response

    async def end_session(session):
        await close_cameras(session)
        db.execute('DELETE FROM camera_enrollment_attempts WHERE bank_session=?', (session['id'],))
        if session['study_session']:
            study = store.one('SELECT status FROM study_sessions WHERE id=?', (session['study_session'],))
            if study and study['status'] in ('created', 'running'):
                now = time.time()
                db.execute('UPDATE study_sessions SET status="aborted",ended_at=?,abort_reason="logout" WHERE id=?', (now, session['study_session']))
                db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, session['study_session'], 'abort', now))
        db.execute('UPDATE sessions SET authenticated=0,consent=0,telemetry=0,camera_consent=0,expires=0 WHERE id=?', (session['id'],))
        forced_mismatch.pop(session['id'], None)

    async def camera(request):
        session = need_session(request, auth=True)
        if not session['camera_consent']:
            raise ApiError(403, 'camera_permission', 'Enable separate camera consent before transmission.')
        if session['study_session']:
            study = store.one('SELECT status,camera_allowed FROM study_sessions WHERE id=? AND study_participant=?', (session['study_session'], session['study_participant']))
            if not study or study['status'] != 'running' or not study['camera_allowed']:
                raise ApiError(403, 'camera_permission', 'Camera transmission is not enabled in the active study session.')
        camera_id = request.match_info.get('camera_id')
        if camera_id and not store.one('SELECT 1 FROM cameras WHERE id=? AND session=?', (camera_id, session['id'])):
            raise ApiError(404, 'camera', 'No active camera was found in this session.')
        frame_transport = request.path.startswith('/api/frames/')
        if camera_id and frame_transport != camera_id.startswith('frame-'):
            raise ApiError(404, 'camera', 'No active camera was found in this session.')
        target = (request.path if frame_transport else
                  '/api/webrtc/offer' if not camera_id else
                  '/api/sessions/' + camera_id + ('/output' if request.method == 'GET' else ''))
        try:
            payload = {}
            if request.method == 'POST':
                if camera_id:
                    if request.content_type != 'image/jpeg':
                        raise ApiError(415, 'camera_frame', 'Expected a JPEG frame.')
                    payload = {'data': await request.read(), 'headers': {'Content-Type': 'image/jpeg'}}
                elif not frame_transport:
                    payload = {'json': await body(request)}
            async with app['http'].request(request.method, camera_url + target, **payload) as upstream:
                raw = await upstream.read()
                if upstream.status >= 400:
                    raise ApiError(upstream.status, 'camera_worker', 'The camera service rejected the connection. Turn off the preview and try again.')
                if request.method == 'POST' and not camera_id:
                    answer = json.loads(raw)
                    db.execute('INSERT INTO cameras(id,session,study_session) VALUES(?,?,?)', (answer['session_id'], session['id'], session['study_session']))
                if request.method == 'DELETE':
                    db.execute('DELETE FROM cameras WHERE id=?', (camera_id,))
                return web.Response(body=raw, status=upstream.status, content_type='application/json' if raw else None)
        except (OSError, asyncio.TimeoutError):
            raise ApiError(503, 'camera_unavailable', 'Camera analysis service is unavailable. You can continue without the camera.')

    async def ice_servers(request):
        session = need_session(request, auth=True)
        if not session['camera_consent']:
            raise ApiError(403, 'camera_permission', 'Enable separate camera consent before transmission.')
        if not (turn_urls and turn_secret):
            return web.json_response(dict(iceServers=[], iceTransportPolicy='all'))
        # coturn use-auth-secret (TURN REST API): username "<expiry>:<user>", credential base64(HMAC-SHA1(secret, username)).
        username = f"{int(time.time()) + turn_ttl}:{session['id'][:16]}"
        credential = base64.b64encode(hmac.new(turn_secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        return web.json_response(dict(iceServers=[dict(urls=list(turn_urls), username=username, credential=credential)],
                                      iceTransportPolicy='relay'))

    async def health(request):
        return web.json_response(dict(status='ok', demo_mode=demo, risk_model=MODEL_VERSION, risk_validated=False, operator_api=bool(admin_token), storage='sqlite'))

    async def frontend(request):
        if request.path.startswith('/api/'):
            raise web.HTTPNotFound()
        dist = REPO_ROOT / 'frontend/dist'
        relative = request.match_info.get('path', '')
        candidate = (dist / relative).resolve()
        if not candidate.is_relative_to(dist.resolve()):
            raise web.HTTPForbidden()
        file = candidate if candidate.is_file() else dist / 'index.html'
        if not file.exists():
            return web.Response(text='Build the frontend with npm run build, or use Vite on port 5173.', status=503)
        return web.FileResponse(file)

    async def resources(app):
        app['http'] = ClientSession(timeout=ClientTimeout(total=15))
        yield
        await app['http'].close()
        db.close()

    app.cleanup_ctx.append(resources)
    app.router.add_get('/health', health)
    app.router.add_post('/api/bootstrap', bootstrap)
    app.router.add_post('/api/session/permissions', permissions)
    app.router.add_post('/api/session/withdraw', withdraw)
    app.router.add_post('/api/study/resolve-code', resolve_study_code)
    app.router.add_post('/api/study/consent', study_consent)
    app.router.add_post('/api/study/sessions', create_study_session)
    app.router.add_post('/api/study/sessions/{id}/start', start_study_session)
    app.router.add_post('/api/study/sessions/{id}/stage', set_study_stage)
    app.router.add_post('/api/study/sessions/{id}/complete', complete_study_session)
    app.router.add_post('/api/study/sessions/{id}/abort', abort_study_session)
    app.router.add_post('/api/study/participants/{id}/withdraw', study_withdraw)
    app.router.add_post('/api/study/participants', admin_participants)
    app.router.add_post('/api/study/survey', survey)
    app.router.add_get('/api/risk/study-sessions/{id}/latest', risk_latest)
    app.router.add_get('/api/risk/study-sessions/{id}/timeline', risk_timeline)
    app.router.add_get('/api/admin/scenarios', admin_scenarios)
    app.router.add_get('/api/admin/profiles', admin_profiles)
    app.router.add_get('/api/admin/participants', admin_participants)
    app.router.add_post('/api/admin/participants', admin_participants)
    app.router.add_post('/api/admin/participants/{id}/assignments', admin_assignments)
    app.router.add_get('/api/admin/sessions', admin_sessions)
    app.router.add_get('/api/admin/sessions/{id}', admin_session_detail)
    app.router.add_post('/api/admin/sessions/{id}/abort', admin_abort_study_session)
    app.router.add_post('/api/admin/participants/{id}/withdraw', admin_withdraw)
    app.router.add_post('/api/admin/exports', admin_export)
    app.router.add_post('/api/bank/login', login)
    app.router.add_post('/api/bank/verify', verify)
    app.router.add_get('/api/bank/login-challenge', login_challenge)
    app.router.add_post('/api/bank/login-challenge', login_challenge)
    app.router.add_post('/api/bank/logout', logout)
    app.router.add_delete('/api/bank/device', device_revoke)
    app.router.add_get('/api/bank/account', account)
    app.router.add_get('/api/bank/transactions', transactions)
    app.router.add_post('/api/bank/transfers', preview)
    app.router.add_post('/api/bank/risk-check', risk_check)
    app.router.add_get('/api/bank/camera-profile', camera_profile_get)
    app.router.add_delete('/api/bank/camera-profile', camera_profile_delete)
    app.router.add_post('/api/bank/camera-profile/enroll/start', camera_profile_start)
    app.router.add_post('/api/bank/camera-profile/enroll', camera_profile_enroll)
    app.router.add_get('/api/admin/camera-profile/candidates', admin_camera_candidates)
    app.router.add_post('/api/admin/camera-profile/candidates/{bank_session}/approve', admin_camera_candidate_decision)
    app.router.add_delete('/api/admin/camera-profile/candidates/{bank_session}', admin_camera_candidate_reject)
    app.router.add_get('/api/bank/transfers/{id}', transfer_get)
    app.router.add_put('/api/bank/transfers/{id}', preview)
    app.router.add_post('/api/bank/transfers/{id}/intervention', intervention)
    app.router.add_get('/api/bank/transfers/{id}/challenge', transaction_challenge)
    app.router.add_post('/api/bank/transfers/{id}/challenge', transaction_challenge)
    app.router.add_post('/api/bank/transfers/{id}/submit', submit)
    app.router.add_post('/api/bank/transfers/{id}/cancel', cancel)
    app.router.add_post('/api/telemetry/events', telemetry)
    app.router.add_get('/api/webrtc/ice-servers', ice_servers)
    app.router.add_post('/api/webrtc/offer', camera)
    app.router.add_get('/api/sessions/{camera_id}/output', camera)
    app.router.add_delete('/api/sessions/{camera_id}', camera)
    app.router.add_post('/api/frames/sessions', camera)
    app.router.add_post('/api/frames/sessions/{camera_id}/frame', camera)
    app.router.add_delete('/api/frames/sessions/{camera_id}', camera)
    # The gateway deliberately polls snapshots instead of exposing worker WS unauthenticated.
    app.router.add_get('/{path:.*}', frontend)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/bank24.sqlite')
    parser.add_argument('--origin', default='http://localhost:5173', help='Allowed browser origin(s), comma-separated')
    parser.add_argument('--camera-url', default='http://127.0.0.1:8080')
    parser.add_argument('--secure-cookie', action='store_true', help='Required behind HTTPS in deployment')
    parser.add_argument('--demo', action='store_true', help='Seed fictional account; enable demo OTP 1234 (no SMS delivery)')
    parser.add_argument('--admin-token', default=os.environ.get('BANK24_ADMIN_TOKEN'), help='Enable operator API with a secret bearer token; prefer BANK24_ADMIN_TOKEN')
    parser.add_argument('--turn-url', action='append', default=[], help='TURN URL handed to browsers, e.g. turn:203.0.113.5:3478?transport=tcp (repeatable)')
    parser.add_argument('--fusion-repo', type=Path, default=Path(os.environ.get('BANK24_FUSION_REPO', REPO_ROOT / 'research')),
                        help='Repo with training/inference_xgb_suspicious.py used to score transfers from camera data')
    parser.add_argument('--risk-logout', type=float, default=float(os.environ.get('BANK24_RISK_LOGOUT', 70)),
                        help='Threshold for validated automatic lockout or the forced demo alarm; unvalidated camera-only scores do not log out')
    parser.add_argument('--alarm-code', default=os.environ.get('BANK24_ALARM_CODE', '4321'),
                        help='Demo only: SMS code accepted as valid that forces a high profile mismatch (empty disables)')
    parser.add_argument('--camera-profiles', type=Path, default=None, help='Legacy option, ignored; profiles now live in the database')
    parser.add_argument('--turn-secret', default=os.environ.get('BANK24_TURN_SECRET'), help='coturn static-auth-secret; prefer BANK24_TURN_SECRET')
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    web.run_app(create_app(args.database, args.demo, args.camera_url, args.origin, args.secure_cookie, admin_token=args.admin_token,
                           turn_urls=args.turn_url, turn_secret=args.turn_secret,
                           fusion_repo=args.fusion_repo if (args.fusion_repo / 'training/inference_xgb_suspicious.py').exists() else None,
                           camera_profiles=args.camera_profiles,
                           risk_logout=args.risk_logout if args.risk_logout >= 0 else None, alarm_code=args.alarm_code or None), host=args.host, port=args.port)
