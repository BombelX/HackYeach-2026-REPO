# Bank24 API v1 — wdrożony kontrakt lokalny

Serwer `bank24_server.py` działa domyślnie na loopback 8081; worker WebRTC
`webrtc_server.py` na loopback 8080. W trybie deweloperskim Vite proxy
zachowuje origin przeglądarki.

## Sesja i logowanie

`POST /api/bootstrap` tworzy lub zwraca sesję w cookie HttpOnly,
SameSite Strict. Odpowiedź zawiera `csrf`, `session_id`, `telemetry`, `camera`,
`authenticated`, `demo_mode`, `camera_transmission`, `study_participant` i
`study_session_id`. TTL sesji to 2 godziny. Mutacje uczestnika wymagają cookie,
nagłówka `X-CSRF-Token` i dozwolonego Origin. Po poprawnym kodzie logowania
serwer rotuje cookie i CSRF.

| Metoda i ścieżka | Dane / rezultat |
| --- | --- |
| POST `/api/session/permissions` | Częściowa zmiana `{telemetry?:boolean,camera?:boolean}` i bieżący stan sesji |
| POST `/api/session/withdraw` | Wymaga logowania; przy sesji badania usuwa dane uczestnika, w pozostałych przypadkach dane bieżącej sesji; fikcyjny rachunek zostaje |
| POST `/api/bank/login` | `{username,password,remember}` → challenge; konto wybierane po prawidłowym loginie i haśle |
| GET / POST `/api/bank/login-challenge` | Odczyt / ponowne zamówienie kodu logowania |
| POST `/api/bank/verify` | `{challenge_id,code}` → `{ok,csrf}`, pełna autoryzacja i rotacja tokenu |
| POST `/api/bank/logout` | Kończy sesję i kamery |
| DELETE `/api/bank/device` | Cofa zapamiętanie bieżącego urządzenia |
| GET `/api/bank/account` | Wymaga pełnego logowania; saldo w groszach, NRB, sumy miesiąca, stan urządzenia, fikcyjna faktura |
| GET `/api/bank/transactions?offset=0&limit=30&q=&direction=all` | Wymaga logowania; przeszukana i przefiltrowana lista oraz dokładny `total` przed paginacją |
| POST `/api/study/survey` | Wymaga logowania; `{rating:1..5,comment:string<=500}` |

Udział w badaniu jest opcjonalny dla zwykłego demo Bank24. Gdy jest aktywny,
kod uczestnika i zgody wiążą sesję z badaniem przed logowaniem. Telemetria i
kamera mają oddzielne zgody. `direction` to `all`, `incoming` lub `outgoing`.
Wyszukiwanie historii ignoruje wielkość liter i polskie znaki diakrytyczne;
filtr działa po stronie API przed offsetem i limitem. Sortowanie jest
deterministyczne.

Błąd JSON: `{code,message,fields}`. 401 kończy dostęp do banku, 403 dotyczy
CSRF/origin lub wyłączonego uprawnienia, 409 stanu/wariantu, 422 walidacji,
429 limitu/cooldown, a 503 niedostępnej usługi. Nie ma cichego mocka.

Challenge zawiera `challenge_id`, `expires_at`, `resend_at`, `demo_mode` i
`code_length`; czasy są w sekundach Unix. Ważność wynosi 300 sekund, cooldown
30 sekund, limit to 5 prób. `--demo` jawnie włącza OTP `1234` i długość 4.
Poza demo wymagany jest adapter `otp_provider` przekazany do `create_app`;
bez niego serwer zwraca 503, zamiast udawać wysłanie SMS.

## Przelew

| Metoda i ścieżka | Dane / rezultat |
| --- | --- |
| POST `/api/bank/transfers` | `{recipient,number,title,amount_grosz}` → zapisany podgląd, 201 |
| PUT `/api/bank/transfers/{id}` | Te same pola + `{version}` → nowa wersja, unieważnienie wcześniejszych kodów i decyzji |
| GET `/api/bank/transfers/{id}` | Trwały stan przypisany do zalogowanego konta |
| POST `/api/bank/transfers/{id}/intervention` | `{version,independent:boolean,compared:true,risk_acknowledged?:boolean}` → `ready` albo nieodwracalne `held`; przy wskaźniku presji ≥70 kontynuowanie wymaga niezależnego sprawdzenia odbiorcy |
| GET / POST `/api/bank/transfers/{id}/challenge` | Odczyt / zamówienie kodu dla identyfikatora i wersji |
| POST `/api/bank/transfers/{id}/submit` | `{version,challenge_id,code}` + `Idempotency-Key` → zapisany wynik |
| POST `/api/bank/transfers/{id}/cancel` | Anulowanie niezrealizowanego przelewu |

Frontend łączy podsumowanie, sprawdzenie danych i pytanie o samodzielność w
jednym ekranie. API nadal egzekwuje przejście stanu, więc klient nie może
pominąć porównania danych ani cofnąć blokady. Status: `review → ready →
completed`, alternatywnie `held` lub `cancelled`. Kwota musi być dodatnią
liczbą całkowitą groszy; rachunek NRB przechodzi kontrolę sumy. Submit sprawdza
saldo i aktualizuje rachunek oraz historię atomowo. Ponowienie completed nie
powoduje drugiego obciążenia.

Pole `risk` zwraca dwa odrębne heurystyczne wskaźniki 0–100, jeśli istnieje
profil właściciela i wystarczająca telemetria. Wartości nie są skalibrowanym
prawdopodobieństwem ani zwalidowanym detektorem. Poza sesją badania, przy
niegotowym profilu lub skąpych danych wynik jest `null`, a odpowiedź zawiera
`assessment_status`, `available_signals`, `missing_reasons`, wyjaśnienia i
`available_modalities` i wersję mechanizmu. Scenariusz nie jest wejściem silnika oceny. Istniejący krok
sprawdzenia danych, deklaracja samodzielności i kod OTP nadal są egzekwowane
przez serwer. Przy wzroście wskaźnika presji przed `submit` serwer odsyła
operację do sprawdzenia i unieważnia wcześniejszy kod.

## Badanie i operator

Mutacje uczestnika wymagają bieżącej sesji Bank24 z CSRF i dozwolonym Origin.
Operator API wymaga nagłówka `Authorization: Bearer <BANK24_ADMIN_TOKEN>`;
mutacje operatora wymagają też Origin. Token ustaw przez zmienną środowiskową
`BANK24_ADMIN_TOKEN` albo `--admin-token`. Bez tokenu API operatora jest
wyłączone.

| Metoda i ścieżka | Dane / rezultat |
| --- | --- |
| POST `/api/admin/participants` (alias POST `/api/study/participants`) | `{label,role,bank_username}` dla istniejącego konta albo `{label,role,username,password,starting_balance_grosz?}` dla nowego; odpowiedź jednorazowo zawiera `study_code` |
| GET `/api/admin/participants` | Lista bez kodów i haseł uczestników |
| GET `/api/admin/scenarios` | Dozwolone scenariusze |
| GET `/api/admin/profiles?bank_username=` | Wersja, gotowość, liczba obserwacji i mediany/MAD profilu per etap |
| POST `/api/admin/participants/{id}/assignments` | `{scenario}`; operator przypisuje scenariusz przed sesją |
| POST `/api/study/resolve-code` | `{code}`; uczestnik wiąże pre-login sesję z wydanym kodem |
| POST `/api/study/consent` | `{telemetry:boolean,camera:boolean,recording:false?}`; zapisuje wersjonowany wybór zgód |
| POST `/api/study/sessions` | `{}`; tworzy sesję z następnym przydzielonym scenariuszem |
| POST `/api/study/sessions/{id}/start` | Uruchamia sesję i etap `login` |
| POST `/api/study/sessions/{id}/stage` | `{stage:'transfer'|'result'}`; dozwolone są kolejne etapy |
| POST `/api/study/sessions/{id}/complete` | Kończy sesję i odświeża profil właściciela, jeśli to kwalifikowana spokojna sesja |
| POST `/api/study/sessions/{id}/abort` | `{reason?}`; kończy aktywną sesję jako przerwaną |
| POST `/api/study/participants/{id}/withdraw` | Uczestnik usuwa własne dane po podaniu kodu; operator ma analogiczny endpoint `/api/admin/participants/{id}/withdraw` |
| GET `/api/risk/study-sessions/{id}/latest` | Najnowsza ocena dostępna właścicielowi sesji |
| GET `/api/risk/study-sessions/{id}/timeline` | Oceny i cechy z kolejnych etapów |
| GET `/api/admin/sessions?participant_id=&offset=0&limit=30` | Paginowana lista sesji badania |
| GET `/api/admin/sessions/{id}` | Szczegóły, zagregowane cechy, dozwolone metadane zdarzeń i oceny |
| POST `/api/admin/sessions/{id}/abort` | `{reason?}`; operator kończy porzuconą sesję |
| POST `/api/admin/exports` | `{participant_id?}` lub `{session_id?}`; pobiera JSON z sesjami, metadanymi, cechami i ocenami |

Scenariusze: `calm_owner`, `calm_dictation`, `pressure`, `intruder`. Wyłącznie
operator może przypisać scenariusz; uczestnik nie wybiera go w żądaniu tworzenia
sesji. `calm_owner` można przypisać tylko osobie oznaczonej przez operatora jako
`role='owner'`. Do profilu trafiają ukończone sesje `calm_owner` z udzieloną
zgodą i wystarczającą telemetrią; potrzeba co najmniej trzech obserwacji dla
każdego etapu. Profil zapisuje wersję, mediany, MAD i zakres danych.

Ekstrakcja nie przechowuje treści pól. Zdarzenia zawierają typ interakcji,
identyfikator pola, czas, długość wejścia, znormalizowany ruch wskaźnika i
lokalnie obliczony czas przytrzymania klawisza. Kody i wartości wpisane przez
uczestnika nie są częścią telemetrii. Odmowa lub cofnięcie zgody blokuje dalsze
zbieranie i usuwa powiązane dane; cofnięcie udziału usuwa zdarzenia, oceny,
przydziały i przelicza profile z pozostałych kwalifikowanych sesji.

Ocena porównuje mediany z profilu właściciela przy użyciu MAD z dolnym progiem
skali. Minimalna liczba zdarzeń i rozrzut cech są wymagane; brak profilu lub
danych daje `null`, nigdy zerowy wynik. `account_takeover_risk` pochodzi z
etapu logowania, a `coercion_risk` z etapu przelewu. Każda odpowiedź deklaruje
`validated:false`, `model_version` i stan `limited` albo `insufficient_data`.
To wskaźniki demonstracyjne, nie podstawa do deklarowania wykrycia oszustwa.

## Kamera i telemetria

`POST /api/webrtc/offer`, `GET /api/sessions/{id}/output` i
`DELETE /api/sessions/{id}` wymagają pełnego logowania i osobnego `camera=true`.
Gateway zapisuje właściciela ID i nie udostępnia cudzych wyników. Obraz bez
dźwięku jest przesyłany do lokalnego serwera analizy; nagrania nie są zapisywane.
WebSocket workera nie jest wystawiony do przeglądarki; frontend pobiera
autoryzowane migawki co sekundę. Wyłączenie zgody zamyka kamerę.

`POST /api/telemetry/events` wymaga `telemetry=true` i przyjmuje
`{page,page_anchor_ms,events:[...]}`, maksymalnie 100 zdarzeń. Dozwolone pola
to `sequence`, `time_ms`, `type`, `stage`, `field` oraz opcjonalnie `length`,
`duration_ms`, `x`, `y`; żadne wartości wpisanych pól nie są przyjmowane. Typy:
input, correction, focus, pointer, key_press i key_dwell; etapy: login i
transfer; pola podlegają allowliście. Współrzędne są znormalizowane 0–1.
Duplikaty `(session,page,sequence)` są pomijane. Serwer dodaje kotwicę i czas
odbioru oraz wiąże zdarzenia z aktywną sesją badania.
