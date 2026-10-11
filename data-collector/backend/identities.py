from __future__ import annotations

import random
import string
from typing import Any

FIRST_NAMES = [
    "Anna", "Maria", "Katarzyna", "Małgorzata", "Agnieszka", "Barbara",
    "Ewa", "Magdalena", "Joanna", "Piotr", "Krzysztof", "Andrzej",
    "Tomasz", "Paweł", "Jan", "Michał", "Marcin", "Jakub", "Adam", "Łukasz",
]
LAST_NAMES = [
    "Nowak", "Kowalska", "Kowalski", "Wiśniewska", "Wiśniewski",
    "Wójcik", "Kowalczyk", "Kamińska", "Kamiński", "Lewandowska",
    "Lewandowski", "Zielińska", "Zieliński", "Szymańska", "Szymański",
    "Dąbrowska", "Dąbrowski", "Woźniak", "Mazur", "Krawczyk",
]
STREETS = [
    "Długa", "Floriańska", "Grodzka", "Karmelicka", "Dietla",
    "Starowiślna", "Rakowicka", "Lubicz", "Mogilska", "Grzegórzecka",
]
CITIES = ["Kraków", "Warszawa", "Wrocław", "Gdańsk", "Poznań", "Łódź"]
PAYEE_NAMES = [
    "Tauron Sprzedaż sp. z o.o.", "Netia S.A.", "ZUS",
    "Wspólnota Mieszkaniowa Rynek 12", "Play / P4 sp. z o.o.",
    "Lecznica Weterynaryjna Vega", "Szkoła językowa Lingua",
]


def _digits(n: int, rng: random.Random) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def _iban_pl(rng: random.Random) -> str:
    """Generate a 26-digit Polish NRB with a plausible checksum prefix."""
    bank = rng.choice(["1020", "1050", "1140", "1240", "2490", "1750"])
    branch = _digits(4, rng)
    account = _digits(16, rng)
    bban = f"{bank}{branch}{account}"
    # IBAN check: PL + bban, letters P=25 L=21
    rearranged = bban + "2521" + "00"
    check = 98 - (int(rearranged) % 97)
    return f"{check:02d}{bban}"


def _format_nrb(nrb: str) -> str:
    parts = [nrb[0:2], nrb[2:6], nrb[6:10], nrb[10:14], nrb[14:18], nrb[18:22], nrb[22:26]]
    return " ".join(parts)


IDENTITY_VERSION = 2

PASSWORD_WORDS = [
    "lato", "kot", "rower", "morze", "las", "wisla", "smok", "kawa",
    "pies", "slonce", "gory", "zamek", "rynek", "obwarzanek",
]

_ASCII = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _ascii(s: str) -> str:
    return s.translate(_ASCII)


def make_identity(seed: str | None = None) -> dict[str, Any]:
    rng = random.Random(f"v{IDENTITY_VERSION}:{seed}")
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    client_id = f"{_ascii(first).lower()}{rng.randint(10, 99)}"
    password = f"{rng.choice(PASSWORD_WORDS)}{rng.randint(10, 99)}"
    sms_code = _digits(4, rng)
    year = rng.randint(1965, 2001)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    nrb = _iban_pl(rng)
    balance = round(rng.uniform(4200, 87400), 2)
    own_payees = []
    for _ in range(rng.randint(2, 4)):
        pnrb = _iban_pl(rng)
        own_payees.append(
            {
                "name": rng.choice(PAYEE_NAMES),
                "nrb": pnrb,
                "nrb_display": _format_nrb(pnrb),
            }
        )
    invoice_nrb = _iban_pl(rng)
    tech_nrb = _iban_pl(rng)
    return {
        "v": IDENTITY_VERSION,
        "full_name": f"{first} {last}",
        "first_name": first,
        "last_name": last,
        "client_id": client_id,
        "password": password,
        "sms_code": sms_code,
        "birth_date": f"{year:04d}-{month:02d}-{day:02d}",
        "address": f"ul. {rng.choice(STREETS).strip()} {rng.randint(2, 88)}, {rng.choice(CITIES)}",
        "nrb": nrb,
        "nrb_display": _format_nrb(nrb),
        "balance": balance,
        "payees": own_payees,
        "invoice": {
            "issuer": "Faktura VAT 2026/" + _digits(4, rng),
            "name": rng.choice(["Studio Graficzne Pixel", "Hydraulika Nowak", "Księgowość Plus"]),
            "nrb": invoice_nrb,
            "nrb_display": _format_nrb(invoice_nrb),
            "amount": round(rng.uniform(180, 2400), 2),
            "title": "FV " + _digits(4, rng) + "/10/2026",
        },
        "tech_account": {
            "name": "Rachunek techniczny Bank24 — Odzysk środków",
            "nrb": tech_nrb,
            "nrb_display": _format_nrb(tech_nrb),
        },
    }


def participant_code(n: int) -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    raw = f"{n:04d}"
    suffix = "".join(alphabet[(n * 17 + i * 13) % len(alphabet)] for i in range(3))
    return f"P-{raw}{suffix}"
