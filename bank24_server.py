"""Bank24 local demonstration API. SQLite state; authenticated camera gateway.

The demo moves fictional money only. No SMS provider or validated biometric risk
model is shipped. --demo explicitly enables documented credentials and OTP 1234.
Run the existing WebRTC worker on loopback separately; its protocol is unchanged.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time
import unicodedata
import uuid
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from bank24_risk import MODEL_VERSION, extract_features, rebuild_owner_profile, compare_with_profile

ROOT = Path(__file__).resolve().parent


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
    'calm_owner': 'Spokojny przelew właściciela',
    'calm_dictation': 'Spokojne dyktowanie danych',
    'pressure': 'Presja podczas przelewu',
    'intruder': 'Operator niebędący właścicielem',
}


def validate_transfer(data, balance):
    errors = {}
    recipient = str(data.get('recipient', '')).strip()
    number = ''.join(str(data.get('number', '')).split())
    title = str(data.get('title', '')).strip()
    amount = data.get('amount_grosz')
    if not 2 <= len(recipient) <= 100:
        errors['recipient'] = 'Podaj nazwę odbiorcy (od 2 do 100 znaków).'
    if len(number) != 26 or not number.isascii() or not number.isdigit() or int(number[2:] + '2521' + number[:2]) % 97 != 1:
        errors['number'] = 'Podaj 26 cyfr poprawnego numeru rachunku NRB.'
    elif number == ACCOUNT:
        errors['number'] = 'Wybierz rachunek inny niż rachunek źródłowy.'
    if not 1 <= len(title) <= 140:
        errors['title'] = 'Podaj tytuł przelewu (do 140 znaków).'
    if type(amount) is not int or amount <= 0:
        errors['amount'] = 'Podaj dodatnią kwotę z najwyżej dwoma miejscami po przecinku.'
    elif amount > balance:
        errors['amount'] = 'Kwota przekracza dostępne środki.'
    if errors:
        raise ApiError(422, 'fields', 'Popraw zaznaczone dane przelewu.', errors)
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
            for who, title, amount, date in [('Pracodawca', 'Wynagrodzenie', 720000, '2026-10-01T08:00:00Z'), ('Administracja', 'Czynsz · październik', -245000, '2026-10-02T09:00:00Z'), ('Sklep internetowy', 'Zakup akcesoriów', -8990, '2026-09-28T12:00:00Z')]:
                self.db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, 'demo-owner', who, title, amount, date, 'completed'))

    def one(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()


def create_app(db_path, demo=False, camera_url='http://127.0.0.1:8080', origin='http://localhost:5173', secure=False, otp_provider=None, admin_token=None):
    store = Store(db_path, demo)
    db = store.db
    allowed_origins = {origin}
    origin_parts = urlsplit(origin)
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
                    raise ApiError(503, 'admin_disabled', 'Panel operatora wymaga skonfigurowanego tokenu BANK24_ADMIN_TOKEN.')
                if not hmac.compare_digest(request.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + admin_token).encode('utf-8')):
                    raise ApiError(401, 'admin_authentication', 'Brak poprawnego tokenu operatora.')
            if request.path.startswith('/api/') and (request.method not in ('GET', 'HEAD') or request.headers.get('Upgrade', '').lower() == 'websocket'):
                if request.headers.get('Origin') not in allowed_origins:
                    raise ApiError(403, 'origin', 'Niedozwolone źródło żądania.')
                if request.method not in ('GET', 'HEAD') and request.path != '/api/bootstrap' and not operator_request:
                    session = need_session(request)
                    if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session['csrf']):
                        raise ApiError(403, 'csrf', 'Odśwież stronę, aby odnowić sesję.')
            response = await handler(request)
        except ApiError as exc:
            response = web.json_response(dict(code=exc.code, message=exc.message, fields=exc.fields), status=exc.status)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = web.json_response(dict(code='json', message='Niepoprawny format żądania.'), status=400)
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    app = web.Application(middlewares=[security], client_max_size=256 * 1024)
    app['store'] = store

    def need_session(request, auth=False, telemetry=False):
        session = request.get('session')
        if session is None:
            raise ApiError(401, 'session', 'Sesja wygasła. Zaloguj się ponownie.')
        if auth and not session['authenticated']:
            raise ApiError(401, 'authentication', 'Zaloguj się, aby przejść do konta.')
        if telemetry and not session['telemetry']:
            raise ApiError(403, 'telemetry_consent', 'Opcjonalny pomiar jest wyłączony.')
        return session

    def need_admin(request):
        if not admin_token:
            raise ApiError(503, 'admin_disabled', 'Panel operatora wymaga skonfigurowanego tokenu BANK24_ADMIN_TOKEN.')
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode('utf-8'), ('Bearer ' + admin_token).encode('utf-8')):
            raise ApiError(401, 'admin_authentication', 'Brak poprawnego tokenu operatora.')

    def get_study_session(request, study_session_id):
        session = need_session(request)
        study = store.one('SELECT * FROM study_sessions WHERE id=?', (study_session_id,))
        if not study or session['study_participant'] != study['study_participant'] or session['study_session'] != study_session_id:
            raise ApiError(404, 'study_session', 'Nie znaleziono sesji badania.')
        if session['authenticated'] and session['participant'] != study['bank_participant']:
            raise ApiError(404, 'study_session', 'Nie znaleziono sesji badania.')
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
            missing.append('Brak gotowego profilu właściciela lub wystarczających danych logowania.')
        if current_stage != 'login':
            if coercion_score is not None:
                available.append('transfer_behavior')
            elif coercion_status == 'insufficient_data':
                missing.append('Brak gotowego profilu właściciela lub wystarczających danych przelewu.')
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
        reasons.append('Wskaźniki są heurystyczne i niezwalidowane; nie są prawdopodobieństwem oszustwa.')
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
            raise ApiError(400, 'json', 'Oczekiwano obiektu JSON.')
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
            raise ApiError(422, 'permissions', 'Ustaw zgodę osobno dla każdego pomiaru.')
        telemetry = int(data.get('telemetry', bool(session['telemetry'])))
        camera = int(data.get('camera', bool(session['camera_consent'])))
        study = store.one('SELECT * FROM study_sessions WHERE id=?', (session['study_session'],)) if session['study_session'] else None
        if study:
            if telemetry and not study['telemetry_allowed']:
                raise ApiError(403, 'telemetry_consent', 'Włącz telemetrię przez osobny formularz zgody badawczej.')
            if camera and not study['camera_allowed']:
                raise ApiError(403, 'camera_consent', 'Włącz kamerę przez osobny formularz zgody badawczej.')
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
        db.execute('DELETE FROM surveys WHERE session=?', (session['id'],))
        db.execute('DELETE FROM challenges WHERE session=? AND kind="login"', (session['id'],))
        db.execute('UPDATE sessions SET consent=0,telemetry=0,camera_consent=0 WHERE id=?', (session['id'],))
        response = web.json_response(dict(ok=True, authenticated=True))
        return response

    async def make_challenge(session, kind, transfer=None, remember=False):
        recent = store.one('SELECT created FROM challenges WHERE session=? AND kind=? ORDER BY created DESC LIMIT 1', (session['id'], kind))
        if recent and time.time() - recent['created'] < 30:
            raise ApiError(429, 'cooldown', 'Poczekaj 30 sekund przed zamówieniem kolejnego kodu.')
        code = '1234' if demo else f'{secrets.randbelow(1000000):06d}'
        if not demo and otp_provider is None:
            raise ApiError(503, 'sms_unavailable', 'Wysyłka SMS nie jest skonfigurowana. Skontaktuj się z prowadzącym.')
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
            raise ApiError(429, 'locked', 'Zbyt wiele prób. Spróbuj ponownie za pięć minut.')
        if session['authenticated']:
            raise ApiError(409, 'already_authenticated', 'Zalogowane konto można zmienić po wylogowaniu.')
        owner = store.one('SELECT * FROM participants WHERE username=?', (str(data.get('username', '')).strip()[:100],))
        salt = owner['salt'] if owner else 'bank24-unknown-login-salt'
        candidate = password_hash(str(data.get('password', ''))[:256], salt)
        expected = owner['password'] if owner else password_hash('invalid-password', salt)
        correct = bool(owner) and hmac.compare_digest(candidate, expected)
        if not correct:
            attempts = session['login_failures'] + 1
            db.execute('UPDATE sessions SET login_failures=?,locked_until=? WHERE id=?', (attempts, time.time() + 300 if attempts >= 5 else 0, session['id']))
            raise ApiError(422, 'credentials', 'Login lub hasło jest niepoprawne. Sprawdź oba pola.')
        if session['study_participant']:
            study_person = store.one('SELECT bank_participant,withdrawn FROM study_participants WHERE id=?', (session['study_participant'],))
            if not study_person or study_person['withdrawn'] or study_person['bank_participant'] != owner['id']:
                raise ApiError(403, 'study_account', 'To konto nie jest przypisane do kodu uczestnika. Skontaktuj się z prowadzącym.')
        db.execute('UPDATE challenges SET used=1 WHERE session=? AND kind="login" AND used=0', (session['id'],))
        db.execute('UPDATE sessions SET participant=?,login_failures=0,locked_until=0 WHERE id=?', (owner['id'], session['id']))
        session = store.one('SELECT * FROM sessions WHERE id=?', (session['id'],))
        challenge = await make_challenge(session, 'login', remember=data.get('remember') is True)
        return web.json_response(challenge)

    def check_challenge(session, data, kind, transfer=None):
        challenge = store.one('SELECT * FROM challenges WHERE id=? AND session=? AND kind=?', (str(data.get('challenge_id', '')), session['id'], kind))
        if not challenge or challenge['used'] or challenge['expires'] < time.time() or challenge['attempts'] >= 5:
            raise ApiError(409, 'challenge_expired', 'Kod wygasł lub wykorzystano limit prób. Zamów nowy kod.')
        if transfer and (challenge['transfer_id'] != transfer['id'] or challenge['version'] != transfer['version']):
            raise ApiError(409, 'version', 'Dane przelewu uległy zmianie. Zamów kod dla aktualnych danych.')
        db.execute('UPDATE challenges SET attempts=attempts+1 WHERE id=?', (challenge['id'],))
        if not hmac.compare_digest(digest(challenge['id'] + str(data.get('code', ''))), challenge['code_hash']):
            raise ApiError(422, 'fields', 'Kod jest niepoprawny.', {'code': 'Sprawdź kod i spróbuj ponownie.'})
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
            raise ApiError(409, 'no_challenge', 'Najpierw wpisz login i hasło.')
        if request.method == 'POST':
            return web.json_response(await make_challenge(session, 'login', remember=bool(challenge['remember'])))
        return web.json_response(dict(challenge_id=challenge['id'], expires_at=challenge['expires'], resend_at=challenge['created'] + 30, demo_mode=demo, code_length=4 if demo else 6))

    async def account(request):
        session = need_session(request, auth=True)
        owner = store.one('SELECT * FROM participants WHERE id=?', (session['participant'],))
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        totals = store.one('SELECT COALESCE(SUM(CASE WHEN amount_grosz>0 THEN amount_grosz ELSE 0 END),0) incoming,COALESCE(-SUM(CASE WHEN amount_grosz<0 THEN amount_grosz ELSE 0 END),0) outgoing FROM ledger WHERE participant=? AND substr(created,1,7)=?', (owner['id'], month))
        trusted = bool(store.one('SELECT 1 FROM devices WHERE token_hash=? AND participant=? AND expires>?', (digest(request.cookies.get('bank24_device', '')), owner['id'], time.time())))
        return web.json_response(dict(name='Anna Kowalska', number=ACCOUNT, balance_grosz=owner['balance'], currency='PLN', month=month, incoming_grosz=totals['incoming'], outgoing_grosz=totals['outgoing'], trusted_device=trusted, invoice=dict(recipient='North Studio sp. z o.o.', number=RECIPIENT, amount_grosz=125000, title='Faktura FV/2026/104', reference='FV/2026/104')))

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
            raise ApiError(400, 'direction', 'Wybierz prawidłowy filtr historii.')
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
            raise ApiError(404, 'transfer', 'Nie znaleziono tego przelewu na Twoim koncie.')
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
        reason = 'Brak powiązanej sesji badania, profilu właściciela lub wystarczającej telemetrii.'
        empty_modalities = {name: False for name in ('keyboard', 'pointer', 'form')}
        return dict(account_takeover_risk=None, coercion_risk=None, assessment_status='insufficient_data', quality='insufficient', available_signals=[], available_modalities={'login': empty_modalities, 'transfer': dict(empty_modalities)}, missing_reasons=[reason], action='review_required', recommended_interventions=['do_not_treat_as_low_risk'], reasons=[reason], explanations=[], model_version=MODEL_VERSION, validated=False, assessed_at=time.time())

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
            risk = assess()
        if request.match_info.get('id'):
            _, previous = get_transfer(request)
            if previous['status'] in ('completed', 'cancelled', 'held'):
                raise ApiError(409, 'terminal', 'Tej operacji nie można zmienić. Przygotuj nowy przelew.')
            if data.get('version') != previous['version']:
                raise ApiError(409, 'version', 'Otwórz aktualną wersję przelewu i porównaj dane.')
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
            raise ApiError(422, 'review', 'Żądanie zawiera nieobsługiwane pola.')
        if transfer['status'] != 'review' or data.get('version') != transfer['version']:
            raise ApiError(409, 'state', 'Odczytaj aktualny stan przelewu.')
        if type(data.get('independent')) is not bool or data.get('compared') is not True:
            raise ApiError(422, 'review', 'Porównaj dane i odpowiedz na pytanie o samodzielność decyzji.')
        acknowledged = data.get('risk_acknowledged', False)
        if type(acknowledged) is not bool:
            raise ApiError(422, 'review', 'Niepoprawna odpowiedź na dodatkowe sprawdzenie.')
        risk = json.loads(transfer['risk'])
        if data['independent'] and (risk.get('coercion_risk') or 0) >= 70 and not acknowledged:
            raise ApiError(422, 'risk_acknowledgement', 'Przed kontynuacją niezależnie sprawdź odbiorcę oficjalnym kanałem.')
        # A declaration of pressure is a server-enforced hold. "No" cannot undo it.
        next_status = 'ready' if data['independent'] else 'held'
        db.execute('UPDATE transfers SET status=?,risk_acknowledged=? WHERE id=?', (next_status, int(acknowledged), transfer['id']))
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer['id'],))))

    async def transaction_challenge(request):
        session, transfer = get_transfer(request)
        if transfer['status'] != 'ready':
            raise ApiError(409, 'state', 'Najpierw przejdź przez sprawdzenie danych przelewu.')
        if request.method == 'GET':
            challenge = store.one('SELECT * FROM challenges WHERE transfer_id=? AND session=? AND version=? AND used=0 ORDER BY created DESC LIMIT 1', (transfer['id'], session['id'], transfer['version']))
            if challenge:
                return web.json_response(dict(challenge_id=challenge['id'], expires_at=challenge['expires'], resend_at=challenge['created'] + 30, demo_mode=demo, code_length=4 if demo else 6))
            raise ApiError(404, 'no_challenge', 'Zamów kod potwierdzenia dla tego przelewu.')
        return web.json_response(await make_challenge(session, 'transfer', transfer))

    async def submit(request):
        session, transfer = get_transfer(request)
        data = await body(request)
        key = request.headers.get('Idempotency-Key', '')
        if len(key) < 16 or len(key) > 128:
            raise ApiError(400, 'idempotency', 'Brakuje identyfikatora potwierdzenia.')
        if transfer['status'] == 'completed':
            return web.json_response(transfer_data(transfer))
        if transfer['status'] != 'ready' or data.get('version') != transfer['version']:
            raise ApiError(409, 'state', 'Przelew nie jest gotowy do wysłania. Sprawdź jego status.')
        if transfer['study_session']:
            study = store.one('SELECT status FROM study_sessions WHERE id=?', (transfer['study_session'],))
            if study and study['status'] == 'running':
                fresh_risk, fresh_features = assess_study_session(transfer['study_session'], 'transfer')
                save_assessment(transfer['study_session'], 'submit', fresh_risk, fresh_features)
                db.execute('UPDATE transfers SET risk=? WHERE id=?', (json.dumps(fresh_risk), transfer['id']))
                if (fresh_risk.get('coercion_risk') or 0) >= 70 and not transfer['risk_acknowledged']:
                    db.execute('UPDATE transfers SET status="review",risk_acknowledged=0 WHERE id=?', (transfer['id'],))
                    db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer['id'],))
                    raise ApiError(409, 'risk_review', 'Nowe dane wymagają ponownego sprawdzenia odbiorcy przed wysłaniem.')
        challenge = check_challenge(session, data, 'transfer', transfer)
        now = datetime.now(timezone.utc).isoformat()
        db.execute('BEGIN IMMEDIATE')
        try:
            changed = db.execute('UPDATE participants SET balance=balance-? WHERE id=? AND balance>=?', (transfer['amount_grosz'], session['participant'], transfer['amount_grosz'])).rowcount
            if not changed:
                raise ApiError(422, 'balance', 'Brakuje środków. Wróć do edycji kwoty.')
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
            raise ApiError(409, 'terminal', 'Zakończonego przelewu nie można anulować.')
        db.execute('UPDATE transfers SET status="cancelled" WHERE id=?', (transfer['id'],))
        db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer['id'],))
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer['id'],))))

    async def telemetry(request):
        session = need_session(request, telemetry=True)
        if not session['telemetry']:
            raise ApiError(403, 'telemetry_consent', 'Pomiar zachowania jest wyłączony.')
        study_session_id = session['study_session']
        if study_session_id:
            study = store.one('SELECT status,telemetry_allowed FROM study_sessions WHERE id=? AND study_participant=?', (study_session_id, session['study_participant']))
            if not study or study['status'] != 'running':
                raise ApiError(409, 'study_session', 'Sesja badania nie przyjmuje już telemetrii.')
            if not study['telemetry_allowed']:
                raise ApiError(403, 'telemetry_consent', 'Uczestnik nie wyraził zgody na telemetrię w tej sesji.')
        data = await body(request)
        page = str(data.get('page', ''))
        events = data.get('events')
        anchor = data.get('page_anchor_ms', 0)
        if type(anchor) not in (int, float) or not math.isfinite(anchor) or not 0 <= anchor <= 1e15:
            raise ApiError(422, 'telemetry', 'Niepoprawna kotwica czasu strony.')
        if not 1 <= len(page) <= 64 or not isinstance(events, list) or len(events) > 100:
            raise ApiError(422, 'telemetry', 'Niepoprawna paczka metadanych.')
        allowed = {'sequence', 'time_ms', 'type', 'stage', 'field', 'length', 'duration_ms', 'x', 'y'}
        stages = {'login', 'transfer'}
        fields = {'username', 'password', 'recipient', 'number', 'title', 'amount', 'none'}
        for event in events:
            if not isinstance(event, dict) or set(event) - allowed or type(event.get('sequence')) is not int or event['sequence'] < 0 or event.get('stage') not in stages or event.get('type') not in ('input', 'correction', 'pointer', 'focus', 'key_press', 'key_dwell') or event.get('field') not in fields:
                raise ApiError(422, 'telemetry', 'Paczka zawiera niedozwolone dane.')
            for name in ('time_ms', 'length', 'duration_ms', 'x', 'y'):
                value = event.get(name, 0)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e10:
                    raise ApiError(422, 'telemetry', 'Niepoprawna wartość metadanych.')
            if event.get('type') == 'key_dwell' and ('duration_ms' not in event or event['duration_ms'] > 5000):
                raise ApiError(422, 'telemetry', 'Niepoprawny czas naciśnięcia klawisza.')
            if event.get('type') == 'pointer' and not (0 <= event.get('x', -1) <= 1 and 0 <= event.get('y', -1) <= 1):
                raise ApiError(422, 'telemetry', 'Współrzędne wskaźnika muszą być znormalizowane do zakresu 0–1.')
            if event.get('type') == 'input' and event.get('length', 0) > 4096:
                raise ApiError(422, 'telemetry', 'Metadane długości pola przekraczają dozwolony zakres.')
        inserted = 0
        for event in events:
            inserted += db.execute('INSERT OR IGNORE INTO telemetry(session,study_session,page,sequence,event) VALUES(?,?,?,?,?)',
                                   (session['id'], study_session_id, page, event['sequence'], json.dumps({**event, 'page_anchor_ms': anchor, 'received_at': time.time()}))).rowcount
        return web.json_response(dict(accepted=inserted, duplicates=len(events) - inserted))

    async def survey(request):
        session = need_session(request, auth=True)
        data = await body(request)
        if type(data.get('rating')) is not int or not 1 <= data['rating'] <= 5 or len(str(data.get('comment', ''))) > 500:
            raise ApiError(422, 'survey', 'Wybierz ocenę od 1 do 5. Komentarz może mieć do 500 znaków.')
        db.execute('INSERT OR REPLACE INTO surveys VALUES(?,?,?)', (session['id'], data['rating'], str(data.get('comment', ''))))
        return web.json_response(dict(ok=True))

    async def resolve_study_code(request):
        session = need_session(request)
        if session['authenticated']:
            raise ApiError(409, 'study_login', 'Kod badania należy powiązać przed logowaniem do Bank24.')
        if session['study_session']:
            active = store.one('SELECT 1 FROM study_sessions WHERE id=? AND status IN ("created","running")', (session['study_session'],))
            if active:
                raise ApiError(409, 'study_session_active', 'Zakończ lub przerwij bieżącą sesję przed zmianą kodu uczestnika.')
        data = await body(request)
        code = str(data.get('code', '')).strip()
        if not 8 <= len(code) <= 128:
            raise ApiError(422, 'study_code', 'Wpisz kod uczestnika otrzymany od prowadzącego.')
        participant = store.one('SELECT id,label FROM study_participants WHERE code_hash=? AND withdrawn=0', (digest(code),))
        if not participant:
            raise ApiError(404, 'study_code', 'Nie znaleziono aktywnego uczestnictwa dla tego kodu.')
        db.execute('UPDATE sessions SET study_participant=? WHERE id=?', (participant['id'], session['id']))
        return web.json_response(dict(ok=True, participant_label=participant['label']))

    async def study_consent(request):
        session = need_session(request)
        if not session['study_participant']:
            raise ApiError(409, 'study_code', 'Najpierw potwierdź kod uczestnika.')
        active_study = store.one('SELECT 1 FROM study_sessions WHERE id=? AND status IN ("created","running")', (session['study_session'],)) if session['study_session'] else None
        if active_study:
            raise ApiError(409, 'study_consent_locked', 'W aktywnej sesji zgodę można tylko cofnąć przez ustawienia uprawnień.')
        participant = store.one('SELECT id,withdrawn FROM study_participants WHERE id=?', (session['study_participant'],))
        if not participant or participant['withdrawn']:
            raise ApiError(410, 'withdrawn', 'Udział w badaniu został wycofany.')
        data = await body(request)
        if set(data) - {'telemetry', 'camera', 'recording'} or type(data.get('telemetry')) is not bool or type(data.get('camera')) is not bool:
            raise ApiError(422, 'consent', 'Wybierz osobno zgodę na telemetrię i transmisję kamery.')
        if data.get('recording', False) is not False:
            raise ApiError(422, 'consent', 'Zapisywanie nagrań nie jest dostępne w tej wersji.')
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
            raise ApiError(409, 'study_code', 'Najpierw potwierdź kod uczestnika.')
        participant = store.one('SELECT * FROM study_participants WHERE id=? AND withdrawn=0', (session['study_participant'],))
        if not participant:
            raise ApiError(410, 'withdrawn', 'Udział w badaniu został wycofany.')
        consent = store.one('SELECT * FROM study_consents WHERE study_participant=? AND bank_session=? ORDER BY created_at DESC LIMIT 1', (participant['id'], session['id']))
        if not consent:
            raise ApiError(409, 'consent_required', 'Zapisz zgodę lub odmowę przed rozpoczęciem sesji.')
        if store.one('SELECT 1 FROM study_sessions WHERE study_participant=? AND status IN ("created","running")', (participant['id'],)):
            raise ApiError(409, 'study_session_active', 'Uczestnik ma już rozpoczętą sesję badania.')
        assignment = store.one('SELECT * FROM study_assignments WHERE study_participant=? AND status="assigned" ORDER BY created_at,id LIMIT 1', (participant['id'],))
        if not assignment:
            raise ApiError(409, 'scenario_unassigned', 'Prowadzący nie przypisał jeszcze scenariusza.')
        data = await body(request)
        if data:
            raise ApiError(422, 'study_session', 'Scenariusz wybiera prowadzący; żądanie nie przyjmuje pól.')
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
            raise ApiError(409, 'study_state', 'Sesję można uruchomić tylko raz po utworzeniu.')
        now = time.time()
        db.execute('UPDATE study_sessions SET status="running",started_at=? WHERE id=?', (now, study['id']))
        db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], 'login', now))
        return web.json_response(dict(id=study['id'], status='running', stage='login'))

    async def set_study_stage(request):
        session, study = get_study_session(request, request.match_info['id'])
        if study['status'] != 'running':
            raise ApiError(409, 'study_state', 'Etap można zmienić tylko w aktywnej sesji.')
        data = await body(request)
        stage = data.get('stage')
        order = {'login': 0, 'transfer': 1, 'result': 2}
        if set(data) != {'stage'} or not isinstance(stage, str) or stage not in order:
            raise ApiError(422, 'study_stage', 'Dostępne etapy to login, transfer i result.')
        current = order.get(study['stage'], -1)
        if order[stage] < current or order[stage] > current + 1:
            raise ApiError(409, 'study_stage', 'Etapy badania można przechodzić tylko w kolejności.')
        if stage != study['stage']:
            now = time.time()
            db.execute('UPDATE study_sessions SET stage=? WHERE id=?', (stage, study['id']))
            db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, study['id'], stage, now))
        return web.json_response(dict(id=study['id'], status=study['status'], stage=stage))

    async def complete_study_session(request):
        session, study = get_study_session(request, request.match_info['id'])
        if study['status'] != 'running':
            raise ApiError(409, 'study_state', 'Tylko aktywną sesję można zakończyć.')
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
            raise ApiError(409, 'study_state', 'Zakończonej sesji nie można przerwać.')
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
                raise ApiError(422, 'participant', 'Żądanie zawiera nieobsługiwane pola.')
            label = str(data.get('label', '')).strip()
            if not 1 <= len(label) <= 100:
                raise ApiError(422, 'participant', 'Etykieta uczestnika musi mieć od 1 do 100 znaków.')
            role = data.get('role', 'operator')
            if role not in ('owner', 'operator'):
                raise ApiError(422, 'participant', 'Rola uczestnika to owner albo operator.')
            bank_username = str(data.get('bank_username', '')).strip()[:100]
            if bank_username:
                bank = store.one('SELECT id,username FROM participants WHERE username=?', (bank_username,))
                if not bank:
                    raise ApiError(404, 'bank_account', 'Nie znaleziono wskazanego fikcyjnego konta Bank24.')
                if data.get('username') is not None or data.get('password') is not None:
                    raise ApiError(422, 'participant', 'Dla istniejącego konta nie podawaj ponownie loginu ani hasła.')
                bank_id, bank_username = bank['id'], bank['username']
            else:
                username = str(data.get('username', '')).strip()[:100]
                password = str(data.get('password', ''))
                balance = data.get('starting_balance_grosz', 0)
                if not 3 <= len(username) <= 100 or len(password) < 8 or len(password) > 256:
                    raise ApiError(422, 'participant', 'Nowe konto wymaga loginu (3–100 znaków) i hasła (8–256 znaków).')
                if type(balance) is not int or not 0 <= balance <= 100_000_000_000:
                    raise ApiError(422, 'participant', 'Saldo początkowe musi być nieujemną liczbą całkowitą groszy.')
                bank_id = uuid.uuid4().hex
                salt = secrets.token_hex(16)
                try:
                    db.execute('INSERT INTO participants(id,code_hash,username,salt,password,balance) VALUES(?,?,?,?,?,?)',
                               (bank_id, None, username, salt, password_hash(password, salt), balance))
                except sqlite3.IntegrityError:
                    raise ApiError(409, 'username', 'Ten login Bank24 jest już zajęty.')
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
            raise ApiError(404, 'participant', 'Nie znaleziono uczestnika.')
        if participant['withdrawn']:
            raise ApiError(410, 'withdrawn', 'Uczestnik wycofał udział.')
        data = await body(request)
        scenario = data.get('scenario')
        if set(data) != {'scenario'} or not isinstance(scenario, str) or scenario not in STUDY_SCENARIOS:
            raise ApiError(422, 'scenario', 'Wybierz jeden z dostępnych scenariuszy.')
        if scenario == 'calm_owner' and participant['role'] != 'owner':
            raise ApiError(422, 'scenario', 'Profil bazowy można zbierać wyłącznie od uczestnika oznaczonego przez operatora jako właściciel.')
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
            raise ApiError(400, 'pagination', 'Niepoprawny zakres sesji.')
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
            raise ApiError(404, 'study_session', 'Nie znaleziono sesji badania.')
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
            raise ApiError(422, 'export', 'Dostępny jest eksport JSON z opcjonalnym filtrem uczestnika lub sesji.')
        participant_id = data.get('participant_id')
        session_id = data.get('session_id')
        if participant_id and session_id:
            raise ApiError(422, 'export', 'Wybierz filtr uczestnika albo sesji.')
        if participant_id is not None and (not isinstance(participant_id, str) or len(participant_id) > 64):
            raise ApiError(422, 'export', 'Niepoprawny identyfikator uczestnika.')
        if session_id is not None and (not isinstance(session_id, str) or len(session_id) > 64):
            raise ApiError(422, 'export', 'Niepoprawny identyfikator sesji.')
        if session_id:
            session_ids = [str(session_id)]
        elif participant_id:
            session_ids = [row['id'] for row in db.execute('SELECT id FROM study_sessions WHERE study_participant=? ORDER BY created_at,id', (participant_id,))]
        else:
            session_ids = [row['id'] for row in db.execute('SELECT id FROM study_sessions ORDER BY created_at,id')]
        if len(session_ids) > 5000:
            raise ApiError(413, 'export_limit', 'Eksport może zawierać maksymalnie 5000 sesji; użyj filtra uczestnika.')
        event_count = sum(store.one('SELECT COUNT(*) count FROM telemetry WHERE study_session=?', (study_id,))['count'] for study_id in session_ids)
        if event_count > 250000:
            raise ApiError(413, 'export_limit', 'Eksport może zawierać maksymalnie 250 000 zdarzeń; zastosuj filtr.')
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
            raise ApiError(404, 'participant', 'Nie znaleziono uczestnika badania.')
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
            raise ApiError(404, 'participant', 'Nie znaleziono aktywnego uczestnictwa.')
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
            raise ApiError(404, 'study_session', 'Nie znaleziono sesji badania.')
        if study['status'] not in ('created', 'running'):
            raise ApiError(409, 'study_state', 'Sesja nie jest aktywna.')
        data = await body(request)
        reason = str(data.get('reason', 'przerwana przez operatora')).strip()[:300]
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
                async with app['http'].delete(camera_url + '/api/sessions/' + camera_id):
                    pass
            except (OSError, asyncio.TimeoutError):
                pass
        db.execute('DELETE FROM cameras WHERE session=?', (session['id'],))

    async def logout(request):
        session = need_session(request)
        await close_cameras(session)
        if session['study_session']:
            study = store.one('SELECT status FROM study_sessions WHERE id=?', (session['study_session'],))
            if study and study['status'] in ('created', 'running'):
                now = time.time()
                db.execute('UPDATE study_sessions SET status="aborted",ended_at=?,abort_reason="logout" WHERE id=?', (now, session['study_session']))
                db.execute('INSERT INTO study_stage_events VALUES(?,?,?,?)', (uuid.uuid4().hex, session['study_session'], 'abort', now))
        db.execute('UPDATE sessions SET authenticated=0,consent=0,telemetry=0,camera_consent=0,expires=0 WHERE id=?', (session['id'],))
        response = web.json_response(dict(ok=True))
        response.del_cookie('bank24_session')
        return response

    async def camera(request):
        session = need_session(request, auth=True)
        if not session['camera_consent']:
            raise ApiError(403, 'camera_permission', 'Włącz osobną zgodę na kamerę przed transmisją.')
        if session['study_session']:
            study = store.one('SELECT status,camera_allowed FROM study_sessions WHERE id=? AND study_participant=?', (session['study_session'], session['study_participant']))
            if not study or study['status'] != 'running' or not study['camera_allowed']:
                raise ApiError(403, 'camera_permission', 'Transmisja kamery nie jest włączona w aktywnej sesji badania.')
        camera_id = request.match_info.get('camera_id')
        if camera_id and not store.one('SELECT 1 FROM cameras WHERE id=? AND session=?', (camera_id, session['id'])):
            raise ApiError(404, 'camera', 'Nie znaleziono aktywnej kamery w tej sesji.')
        target = '/api/webrtc/offer' if not camera_id else '/api/sessions/' + camera_id + ('/output' if request.method == 'GET' else '')
        try:
            async with app['http'].request(request.method, camera_url + target, json=await body(request) if request.method == 'POST' else None) as upstream:
                raw = await upstream.read()
                if upstream.status >= 400:
                    raise ApiError(upstream.status, 'camera_worker', 'Usługa kamery odrzuciła połączenie. Wyłącz podgląd i spróbuj ponownie.')
                if request.method == 'POST':
                    answer = json.loads(raw)
                    db.execute('INSERT INTO cameras(id,session,study_session) VALUES(?,?,?)', (answer['session_id'], session['id'], session['study_session']))
                if request.method == 'DELETE':
                    db.execute('DELETE FROM cameras WHERE id=?', (camera_id,))
                return web.Response(body=raw, status=upstream.status, content_type='application/json' if raw else None)
        except (OSError, asyncio.TimeoutError):
            raise ApiError(503, 'camera_unavailable', 'Usługa analizy kamery jest niedostępna. Możesz kontynuować bez kamery.')

    async def health(request):
        return web.json_response(dict(status='ok', demo_mode=demo, risk_model=MODEL_VERSION, risk_validated=False, operator_api=bool(admin_token), storage='sqlite'))

    async def frontend(request):
        if request.path.startswith('/api/'):
            raise web.HTTPNotFound()
        dist = ROOT / 'frontend/dist'
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
    app.router.add_get('/api/bank/transfers/{id}', transfer_get)
    app.router.add_put('/api/bank/transfers/{id}', preview)
    app.router.add_post('/api/bank/transfers/{id}/intervention', intervention)
    app.router.add_get('/api/bank/transfers/{id}/challenge', transaction_challenge)
    app.router.add_post('/api/bank/transfers/{id}/challenge', transaction_challenge)
    app.router.add_post('/api/bank/transfers/{id}/submit', submit)
    app.router.add_post('/api/bank/transfers/{id}/cancel', cancel)
    app.router.add_post('/api/telemetry/events', telemetry)
    app.router.add_post('/api/webrtc/offer', camera)
    app.router.add_get('/api/sessions/{camera_id}/output', camera)
    app.router.add_delete('/api/sessions/{camera_id}', camera)
    # The gateway deliberately polls snapshots instead of exposing worker WS unauthenticated.
    app.router.add_get('/{path:.*}', frontend)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/bank24.sqlite')
    parser.add_argument('--origin', default='http://localhost:5173')
    parser.add_argument('--camera-url', default='http://127.0.0.1:8080')
    parser.add_argument('--secure-cookie', action='store_true', help='Required behind HTTPS in deployment')
    parser.add_argument('--demo', action='store_true', help='Seed fictional account; enable demo OTP 1234 (no SMS delivery)')
    parser.add_argument('--admin-token', default=os.environ.get('BANK24_ADMIN_TOKEN'), help='Enable operator API with a secret bearer token; prefer BANK24_ADMIN_TOKEN')
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    web.run_app(create_app(args.database, args.demo, args.camera_url, args.origin, args.secure_cookie, admin_token=args.admin_token), host=args.host, port=args.port)
