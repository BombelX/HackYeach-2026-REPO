# Bank24 — aplikacja React

Docelowy frontend na branchu `backend`, rozwinięty z zatwierdzonych mockupów.
React + TypeScript + Vite, data router React Router i TanStack Query. Serwer
`bank24_server.py` zapisuje fikcyjny rachunek i operacje w SQLite. Aplikacja
nie przełącza się na mock API po awarii serwera.

## Uruchomienie na Windows

Z katalogu repozytorium, jednorazowo:

```powershell
python -m venv .venv-bank
./.venv-bank/Scripts/python.exe -m pip install -r requirements-bank.txt
cd frontend
npm ci
```

W pierwszym terminalu, w katalogu repozytorium:

```powershell
./.venv-bank/Scripts/python.exe bank24_server.py --demo
```

W drugim terminalu:

```powershell
cd frontend
npm run dev
```

Otwórz **http://localhost:5173/**. Strona główna prowadzi do logowania.
Login: `anna.demo`, hasło: `bank24`, testowe kody logowania i przelewu:
`1234`.
`--demo` włącza te dane i jawny testowy OTP; SMS nie jest wysyłany.
SQLite: `data/bank24.sqlite`. Zmiany salda przeżywają odświeżenie i restart.
Mockupy na 5174 są osobną referencją, nie uruchomioną aplikacją React.

Kamera jest opcjonalna. Do rzeczywistego transportu i analizy postawy/mimiki:

```powershell
./.venv-bank/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
./.venv-bank/Scripts/python.exe -m pip install -r requirements-server.txt
./.venv-bank/Scripts/python.exe webrtc_server.py --host 127.0.0.1 --preview-only --device cpu
```

`--preview-only` wyłącza PhysNet, nie MediaPipe. Dodaj `--no-analysis`, aby
sprawdzić sam transport. PhysNet wymaga brakujących w tym checkoutcie źródeł
i wag. Frontend pokazuje `null` jako brak pomiaru. Nie uruchamia kamery bez
osobnej zgody na transmisję obrazu. Nie pobiera mikrofonu i nie zapisuje nagrań.
Transport wysyła kompletne SDP po ICE gathering. Wyniki pobiera przez
autoryzowany snapshot co sekundę; stare pomiary po 5 s są ukrywane.

## Przepływ i stan

Landing → login i hasło → kod logowania → konto → ręczny przelew →
podsumowanie i sprawdzenie → kod transakcji → wynik. Historia, pomoc, ankieta
i usuwanie opcjonalnych danych są działającymi ekranami. Nie ma strony ani
bramki z kodem uczestnika.

- Sesja w cookie HttpOnly/SameSite Strict; token rotuje po pełnej weryfikacji.
- CSRF i dozwolony origin są egzekwowane na serwerze. Localhost i 127.0.0.1
  na tym samym skonfigurowanym porcie działają w dev.
- Zapamiętane urządzenie ma odrębny hashowany token na 30 dni, z możliwością
  cofnięcia. Nie pomija kodów logowania ani przelewu.
- Kwoty są całkowitymi groszami. NRB sprawdzany sumą kontrolną po obu stronach.
- Edycja zwiększa wersję i unieważnia wcześniejszy kod oraz decyzję.
- Serwer zapisuje wynik atomowo wraz z saldem i historią. Ponowienie potwierdzenia
  lub wejście przez Back nie powoduje drugiego obciążenia.
- Po utracie odpowiedzi frontend odczytuje status tej samej operacji.
- Zgłoszenie presji wstrzymuje przelew na serwerze; nie można odblokować go
  ponowną deklaracją samodzielności.
- Hasła, OTP i tokeny nie trafiają do localStorage ani telemetrii. Szkic przed
  podsumowaniem pozostaje w pamięci; opuszczenie go wymaga wyboru.
- Kamera ma osobną zgodę i widoczną kontrolę Wyłącz. Zmiana trasy nie tworzy
  nowego strumienia. Wylogowanie i wycofanie zamykają zasoby.
- Telemetria jest dobrowolna: tylko czas, liczba korekt, długość wejścia,
  focus i próbkowany ruch wskaźnika. Ograniczona kolejka, paczki co 750 ms,
  deduplikacja według strony i sekwencji, monotoniczny czas z kotwicą strony.
  Serwer odrzuca dodatkowe klucze, w tym treści wpisywanych pól.

## Testy

Z katalogu repozytorium:

```powershell
./.venv-bank/Scripts/python.exe -m unittest discover -s tests -v
cd frontend
npm run build
npm test
npm run test:e2e
npm audit
```

E2E korzysta z Chrome, własnego API na 8082, Vite na 5180 i oddzielnego
`data/e2e-bank24.sqlite`. Nie zmienia salda działającej demonstracji na 8081.
Kamera testowa jest kontrolowanym strumieniem canvas przekazanym przez prawdziwe
WebRTC do istniejącego serwera. Nie uruchamia fizycznej kamery użytkownika.
Playwright w razie potrzeby uruchamia worker na 8080 z wyłączoną analizą.
Brakujące źródła/wagi PhysNet powodują jawny skip jednego testu inferencji;
testy transportu nadal działają. Axe wspiera kontrolę dostępności; pełny test
czytnikiem ekranu i badanie z uczestnikami pozostają osobnymi bramkami.

## Build bez Vite

```powershell
cd frontend
npm run build
cd ..
./.venv-bank/Scripts/python.exe bank24_server.py --demo --origin http://localhost:8081
```

Otwórz http://localhost:8081. Serwer obsługuje zbudowane pliki i bezpośrednie
linki do tras. Przy HTTPS użyj `--secure-cookie` i poprawnego `--origin`;
usługę WebRTC utrzymuj za gatewayem, na loopback. Konfiguracja sieciowa poza
localhost wymaga STUN/TURN i HTTPS opisanych w głównym README.

## Zakres dalszych etapów planu

To działająca demonstracja bankowości i integracji, nie zwalidowany detektor
przejęcia konta ani presji. API celowo zwraca oddzielne wyniki ryzyka `null`.
Sprawdzenie danych i deklaracja presji są rzeczywistymi regułami serwera,
nie wynikami wytrenowanego modelu. Do kolejnego etapu pozostają: dostawca SMS,
konfiguracja uczestników/scenariuszy operatora, kalibracja profili właściciela,
walidacja modeli i progów, eksport badań/retencja oraz ręczny odbiór dostępności.
Nie wpisano tych funkcji jako ukończonych w planie.
