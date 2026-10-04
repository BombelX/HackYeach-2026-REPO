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
          CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,id TEXT UNIQUE,participant TEXT REFERENCES participants(id),csrf TEXT,consent INTEGER DEFAULT 0,telemetry INTEGER DEFAULT 0,authenticated INTEGER DEFAULT 0,expires REAL,login_failures INTEGER DEFAULT 0,locked_until REAL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,session TEXT REFERENCES sessions(id),kind TEXT,transfer_id TEXT,version INTEGER,code_hash TEXT,expires REAL,attempts INTEGER DEFAULT 0,used INTEGER DEFAULT 0,created REAL,remember INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY,participant TEXT REFERENCES participants(id),version INTEGER,recipient TEXT,number TEXT,title TEXT,amount_grosz INTEGER,status TEXT,risk TEXT,created TEXT,confirmed TEXT,idempotency TEXT);
          CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,participant TEXT REFERENCES participants(id),recipient TEXT,title TEXT,amount_grosz INTEGER,created TEXT,status TEXT);
          CREATE TABLE IF NOT EXISTS devices(token_hash TEXT PRIMARY KEY,participant TEXT REFERENCES participants(id),expires REAL);
          CREATE TABLE IF NOT EXISTS telemetry(session TEXT REFERENCES sessions(id),page TEXT,sequence INTEGER,event TEXT,PRIMARY KEY(session,page,sequence));
          CREATE TABLE IF NOT EXISTS surveys(session TEXT PRIMARY KEY REFERENCES sessions(id),rating INTEGER,comment TEXT);
          CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY,session TEXT REFERENCES sessions(id));
        ''')
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(sessions)')}
        if 'camera_consent' not in columns:
            self.db.execute('ALTER TABLE sessions ADD COLUMN camera_consent INTEGER NOT NULL DEFAULT 0')
        # Participant-code entry was removed; do not retain or seed its credential hash.
        self.db.execute('UPDATE participants SET code_hash=NULL WHERE code_hash IS NOT NULL')
        if demo and not self.db.execute('SELECT 1 FROM participants').fetchone():
            salt = secrets.token_hex(16)
            self.db.execute('INSERT INTO participants VALUES(?,?,?,?,?,?)', ('demo-owner', None, 'anna.demo', salt, password_hash('bank24', salt), 1842050))
            for who, title, amount, date in [('Pracodawca', 'Wynagrodzenie', 720000, '2026-10-01T08:00:00Z'), ('Administracja', 'Czynsz · październik', -245000, '2026-10-02T09:00:00Z'), ('Sklep internetowy', 'Zakup akcesoriów', -8990, '2026-09-28T12:00:00Z')]:
                self.db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, 'demo-owner', who, title, amount, date, 'completed'))

    def one(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()


def create_app(db_path, demo=False, camera_url='http://127.0.0.1:8080', origin='http://localhost:5173', secure=False, otp_provider=None):
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
            if request.path.startswith('/api/') and (request.method not in ('GET', 'HEAD') or request.headers.get('Upgrade', '').lower() == 'websocket'):
                if request.headers.get('Origin') not in allowed_origins:
                    raise ApiError(403, 'origin', 'Niedozwolone źródło żądania.')
                if request.method not in ('GET', 'HEAD') and request.path != '/api/bootstrap':
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

    async def body(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ApiError(400, 'json', 'Oczekiwano obiektu JSON.')
        return data

    def cookie(response, name, value, age):
        response.set_cookie(name, value, httponly=True, samesite='Strict', secure=secure, max_age=age, path='/')

    def session_data(session):
        return dict(csrf=session['csrf'], session_id=session['id'], telemetry=bool(session['telemetry']), camera=bool(session['camera_consent']), authenticated=bool(session['authenticated']), demo_mode=demo, camera_transmission=bool(session['camera_consent']))

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
        db.execute('UPDATE sessions SET consent=?,telemetry=?,camera_consent=? WHERE id=?',
                   (telemetry, telemetry, camera, session['id']))
        if not telemetry:
            db.execute('DELETE FROM telemetry WHERE session=?', (session['id'],))
        if not camera:
            await close_cameras(session)
        return web.json_response(session_data(store.one('SELECT * FROM sessions WHERE id=?', (session['id'],))))

    async def withdraw(request):
        session = need_session(request, auth=True)
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
        data.pop('idempotency')
        data['risk'] = json.loads(data['risk'])
        return data

    def assess():
        # Deliberately no trained classifier / biometric identity inference.
        return dict(account_takeover_risk=None, coercion_risk=None, quality='insufficient', action='review_required', reasons=['Brak zwalidowanego profilu właściciela i modelu oceny presji.'], assessed_at=time.time())

    async def preview(request):
        session = need_session(request, auth=True)
        data = await body(request)
        balance = store.one('SELECT balance FROM participants WHERE id=?', (session['participant'],))['balance']
        recipient, number, title, amount = validate_transfer(data, balance)
        transfer_id = uuid.uuid4().hex
        version = 1
        if request.match_info.get('id'):
            _, previous = get_transfer(request)
            if previous['status'] in ('completed', 'cancelled', 'held'):
                raise ApiError(409, 'terminal', 'Tej operacji nie można zmienić. Przygotuj nowy przelew.')
            if data.get('version') != previous['version']:
                raise ApiError(409, 'version', 'Otwórz aktualną wersję przelewu i porównaj dane.')
            transfer_id, version = previous['id'], previous['version'] + 1
            db.execute('UPDATE challenges SET used=1 WHERE transfer_id=?', (transfer_id,))
            db.execute('UPDATE transfers SET version=?,recipient=?,number=?,title=?,amount_grosz=?,status="review",risk=? WHERE id=?', (version, recipient, number, title, amount, json.dumps(assess()), transfer_id))
        else:
            db.execute('INSERT INTO transfers(id,participant,version,recipient,number,title,amount_grosz,status,risk,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (transfer_id, session['participant'], version, recipient, number, title, amount, 'review', json.dumps(assess()), datetime.now(timezone.utc).isoformat()))
        return web.json_response(transfer_data(store.one('SELECT * FROM transfers WHERE id=?', (transfer_id,))), status=201)

    async def transfer_get(request):
        _, transfer = get_transfer(request)
        return web.json_response(transfer_data(transfer))

    async def intervention(request):
        session, transfer = get_transfer(request)
        data = await body(request)
        if transfer['status'] != 'review' or data.get('version') != transfer['version']:
            raise ApiError(409, 'state', 'Odczytaj aktualny stan przelewu.')
        if type(data.get('independent')) is not bool or data.get('compared') is not True:
            raise ApiError(422, 'review', 'Porównaj dane i odpowiedz na pytanie o samodzielność decyzji.')
        # A declaration of pressure is a server-enforced hold. "No" cannot undo it.
        next_status = 'ready' if data['independent'] else 'held'
        db.execute('UPDATE transfers SET status=? WHERE id=?', (next_status, transfer['id']))
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
        data = await body(request)
        page = str(data.get('page', ''))
        events = data.get('events')
        anchor = data.get('page_anchor_ms', 0)
        if type(anchor) not in (int, float) or not math.isfinite(anchor) or not 0 <= anchor <= 1e15:
            raise ApiError(422, 'telemetry', 'Niepoprawna kotwica czasu strony.')
        if not 1 <= len(page) <= 64 or not isinstance(events, list) or len(events) > 100:
            raise ApiError(422, 'telemetry', 'Niepoprawna paczka metadanych.')
        allowed = {'sequence', 'time_ms', 'type', 'stage', 'field', 'length', 'x', 'y'}
        stages = {'login', 'transfer'}
        fields = {'username', 'password', 'recipient', 'number', 'title', 'amount', 'none'}
        for event in events:
            if not isinstance(event, dict) or set(event) - allowed or type(event.get('sequence')) is not int or event['sequence'] < 0 or event.get('stage') not in stages or event.get('type') not in ('input', 'correction', 'pointer', 'focus') or event.get('field') not in fields:
                raise ApiError(422, 'telemetry', 'Paczka zawiera niedozwolone dane.')
            for name in ('time_ms', 'length', 'x', 'y'):
                value = event.get(name, 0)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e10:
                    raise ApiError(422, 'telemetry', 'Niepoprawna wartość metadanych.')
        for event in events:
            db.execute('INSERT OR IGNORE INTO telemetry VALUES(?,?,?,?)', (session['id'], page, event['sequence'], json.dumps({**event, 'page_anchor_ms': anchor, 'received_at': time.time()})))
        return web.json_response(dict(accepted=len(events)))

    async def survey(request):
        session = need_session(request, auth=True)
        data = await body(request)
        if type(data.get('rating')) is not int or not 1 <= data['rating'] <= 5 or len(str(data.get('comment', ''))) > 500:
            raise ApiError(422, 'survey', 'Wybierz ocenę od 1 do 5. Komentarz może mieć do 500 znaków.')
        db.execute('INSERT OR REPLACE INTO surveys VALUES(?,?,?)', (session['id'], data['rating'], str(data.get('comment', ''))))
        return web.json_response(dict(ok=True))

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
        db.execute('UPDATE sessions SET authenticated=0,expires=0 WHERE id=?', (session['id'],))
        response = web.json_response(dict(ok=True))
        response.del_cookie('bank24_session')
        return response

    async def camera(request):
        session = need_session(request, auth=True)
        if not session['camera_consent']:
            raise ApiError(403, 'camera_permission', 'Włącz osobną zgodę na kamerę przed transmisją.')
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
                    db.execute('INSERT INTO cameras VALUES(?,?)', (answer['session_id'], session['id']))
                if request.method == 'DELETE':
                    db.execute('DELETE FROM cameras WHERE id=?', (camera_id,))
                return web.Response(body=raw, status=upstream.status, content_type='application/json' if raw else None)
        except (OSError, asyncio.TimeoutError):
            raise ApiError(503, 'camera_unavailable', 'Usługa analizy kamery jest niedostępna. Możesz kontynuować bez kamery.')

    async def health(request):
        return web.json_response(dict(status='ok', demo_mode=demo, risk_model='not_validated', storage='sqlite'))

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
    app.router.add_post('/api/study/survey', survey)
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
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    web.run_app(create_app(args.database, args.demo, args.camera_url, args.origin, args.secure_cookie), host=args.host, port=args.port)
