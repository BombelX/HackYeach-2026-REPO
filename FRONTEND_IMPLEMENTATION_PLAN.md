# Bank24 — docelowy frontend fintech

> **Plan historyczny.** Od 4 października 2026 bieżący kierunek reimplementacji opisuje [FRONTEND_REIMPLEMENTATION_PLAN.md](FRONTEND_REIMPLEMENTATION_PLAN.md): landing → logowanie → kod logowania → dashboard, bez strony z kodem uczestnika. Poniższy dokument zachowuje historię wcześniejszego wdrożenia; jego stary onboarding nie jest wymaganiem nowej wersji.

Plan i przegląd UI/UX z 3 października 2026. Punkt wyjścia: branch `backend`, commit `0261234`, bieżące mockupy w `mockups/` i istniejący serwer `aiohttp` / WebRTC. Dokument rozwija `IMPLEMENTATION_PLAN.md` o konkretny frontend. **Realizacja rozpoczęta: działająca aplikacja React w `frontend/` oraz nowe API demonstracyjnej bankowości w `bank24_server.py`. Zakres i uruchomienie: `frontend/README.md`; wdrożone kontrakty: `BANK24_API.md`.**

### Stan realizacji

- F0–F2: wdrożono kontrakty lokalne, fundament React/TS/Vite, data router, Query, identyfikację oraz pełny przepływ bankowy z trwałym SQLite i idempotencją. Nie ma cichego fallbacku do mocków.
- F3: właściciel kamery ponad trasami, osobna zgoda, kompletne SDP, autoryzowany gateway i polling snapshotów co sekundę, stale i cleanup. Brak źródeł/wag PhysNet: puls wyłączony, bez sztucznych wartości; MediaPipe pozostaje dostępne niezależnie.
- F4: wdrożono jawny stan niewystarczającej oceny, dodatkowe sprawdzenie oraz serwerową blokadę po zgłoszeniu presji. Klasyfikatory przejęcia konta i presji oraz kalibracja profilu nie są ukończone; wyniki ryzyka pozostają `null`.
- F5: zgody, dobrowolna telemetria metadanych, deduplikacja, ankieta i wycofanie udziału. Konfiguracja operatora, scenariusze, eksport i retencja pozostają do następnego etapu.
- F6: dodano build, testy walidacji, integracyjne API i Playwright dla flow, awarii, responsywności i kamery. Pełny test czytnikiem ekranu i odbiór z uczestnikami pozostają otwartymi bramkami.

Lokalny `--demo` jawnie korzysta z kodu `1234`, bez wysyłki SMS. Włączenie rzeczywistego SMS wymaga skonfigurowanego adaptera; serwer bez niego nie udaje dostarczenia kodu.

## 1. Cel produktu i kierunek wizualny

Bank24 jest demonstracyjnym bankiem z warstwą SafeTransfer. Użytkownik ma łatwo zalogować się, znaleźć saldo, przygotować przelew, zrozumieć ewentualną interwencję i zobaczyć jednoznaczny wynik. Kamera pozostaje opcjonalna. Interwencja jest warunkową gałęzią, a nie obowiązkowym ekranem każdego przelewu.

Styl: jasny fintech. Biel i chłodne neutralne powierzchnie, granat `#152b4b`, granatowe główne akcje z białym tekstem, mięta `#67e8c5` jako akcent na karcie rachunku oraz ciemny teal `#08786a` dla linków, zaznaczeń i obramowań. Mięta jest kolorem marki, nie dowodem bezpieczeństwa. Bursztyn oznacza ostrzeżenie, czerwień błąd, zieleń zakończoną czynność. Brak analizy jest stanem neutralnym.

Znak Bank24 to autorski znak „B” z dwóch otwartych obiegów i wspólnego pionu, z logotypem opartym na IBM Plex Sans. Warianty SVG: pełny, sam znak, monochromatyczny i jasny na granacie. Litery są krzywymi; znak nie wymaga pobrania fontu. Źródła: `mockups/assets/bank24-*.svg`, opis i podgląd: `mockups/brand.html`, zasady typografii i komponentów: `DESIGN.md`.

Zachować przestrzeń uzyskaną w nowszych mockupach finalnych: obszar do 1380 px, formularz logowania do 520 px, pola 56 px, przyciski co najmniej 52 px. Poniżej 1024 px zadanie jest pierwsze, kamera ma zwijany podgląd. Na desktopie zadanie lub formularz pozostaje po lewej, a kamera po prawej. Panel parametrów pod kamerą startuje zwinięty. Unikać ozdobnych wykresów, dekoracyjnych animacji i etykiet sugerujących nieistniejące zabezpieczenia.

## 2. Przegląd całego obecnego przepływu

Przegląd ekspercki obejmuje logowanie, SMS, pulpit, formularz, podsumowanie, ostrzeżenie, potwierdzenie, wynik, historię, pomoc oraz stany kamery. To przegląd prototypu; nie jest walidacją skuteczności modelu ani działania przyszłego backendu bankowego.

| Obserwacja w poprzednim prototypie | Zmiana w bieżących mockupach | Wymaganie docelowego frontendu |
| --- | --- | --- |
| Logo jako litera „b” w kwadracie | Znak B, logotyp Bank24 i warianty SVG | Jeden komponent `Bank24Logo`, właściwy wariant i opis dostępności |
| Jedna gałąź przelewu zawsze prowadziła do ostrzeżenia | Zwykły przelew i jawny scenariusz interwencji w menu demonstracji | Gałąź wybiera odpowiedź backendu, nie frontend ani lokalny przełącznik |
| Historia i pomoc kończyły się toastem | Oddzielna historia i pomoc z instrukcjami oraz powrotem | Prawdziwe dane API, stany pustej listy, niedostępności i błędu |
| Po potwierdzeniu saldo nie odzwierciedlało przelewu | Saldo i historia aktualizują się w pamięci demonstracji | Po sukcesie uzgodnić stan z serwerem i odświeżyć właściwe zapytania |
| Zielony komunikat sugerował niski poziom ryzyka bez analizy | Neutralna informacja „ocena ryzyka niedostępna” | `null` lub brak danych nigdy nie zamienia się w zero ryzyka |
| Wynik przy wejściu bez wcześniejszej operacji sugerował sukces | Stan początkowy prosi o przygotowanie przelewu | Wynik jest związany z konkretnym identyfikatorem operacji |
| Błąd hasła mógł wskazywać login | Rozdzielona walidacja i błąd przy właściwym polu | Błędy klienta i serwera mają konkretne pola oraz sposób naprawy |
| Brak feedbacku podczas potwierdzania | Jawny krótki stan sprawdzania danych demo, blokada ponownego submitu | Stan `pending` trwa tyle, ile rzeczywiste żądanie; bez sztucznego opóźnienia |
| Back pozwalał ponownie potwierdzić zakończoną symulację | Lokalny identyfikator operacji i zapis wyniku blokują ponowne obciążenie lub reaktywację anulowanego przelewu | Serwerowa idempotencja i odczyt trwałego statusu, także po odświeżeniu i z wielu kart |
| Pomoc gubiła częściowo wpisane logowanie oraz odpowiedź na ostrzeżenie | Wartości pozostają w pamięci; po powrocie odtwarza się zaznaczenie i właściwa odpowiedź | Powrót zachowuje kontekst bez zapisywania danych uwierzytelnienia poza pamięcią |

Iteracja profesjonalnego layoutu: ramy logowania i kamery, nagłówek bankowości, spokojne granatowe akcje, treść przygotowania kamery i instrukcja bezpiecznego korzystania. Pulpit pokazuje wyliczane z operacji demo wpływy i wydatki miesiąca oraz informacje rachunku. Historia zawiera tytuły, daty, statusy, wyszukiwanie bez rozróżniania polskich znaków i stan pustych wyników. Docelowe obliczenia i filtrowanie rozszerzyć na pełną historię udostępnioną przez API, zamiast traktować widoczną stronę paginacji jako sumę miesiąca.

Wpisywanie danych przelewu pozostaje ręczne. Przycisk wypełnienia danych demo dotyczy logowania i służy prezentacji; nie może być dostępny podczas właściwego pomiaru rytmu logowania. Mockupy nie przechowują tokenów i nie analizują kamery.

## 3. Heurystyki Nielsena jako wymagania i kryteria odbioru

Podstawa: [Jakob Nielsen, 10 Usability Heuristics — Nielsen Norman Group](https://www.nngroup.com/articles/ten-usability-heuristics/). Poniżej własne zastosowanie zasad do Bank24, a nie deklaracja certyfikacji.

| Zasada | Zastosowanie w Bank24 | Sprawdzalny warunek odbioru |
| --- | --- | --- |
| 1. Widoczność stanu systemu | Krok, stan żądania, kamera, świeżość pomiaru i status przelewu | Przy opóźnionym API widać `pending`; przeterminowane wyniki nie wyglądają na aktualne; wynik nie pojawia się przed odpowiedzią |
| 2. Zgodność ze światem użytkownika | „Odbiorca”, „Kwota”, „Rachunek”, polskie kwoty i daty | Brak SDP, nazw modeli i kodów HTTP w podstawowym zadaniu; techniczne szczegóły są zwijane |
| 3. Kontrola i swoboda | Powrót, edycja, anulowanie, wyłączenie kamery, wylogowanie | Cofnięcie zachowuje szkic; anulowanie nie wysyła operacji; wylogowanie zamyka kamerę i sesję |
| 4. Spójność i standardy | Wspólne pola, przyciski, nazwy kroków i statusy | Ten sam typ akcji wygląda i działa tak samo; aktywna nawigacja ma semantyczne oznaczenie |
| 5. Zapobieganie błędom | Walidacja, podsumowanie, potwierdzenie, blokada duplikatów | Błędny rachunek i zbyt duża kwota nie przechodzą; dwa kliknięcia tworzą najwyżej jedną operację |
| 6. Rozpoznawanie zamiast pamiętania | Faktura przy formularzu, pełne podsumowanie, jawny stan zaznaczenia | Użytkownik może porównać dane i kwotę przed kodem; nie musi pamiętać poprzedniego ekranu |
| 7. Elastyczność i sprawność | Enter, wklejanie kodu, menedżer haseł, logiczny Tab, powrót do szkicu | Pełen przepływ jest dostępny klawiaturą; wklejenie OTP działa; skróty demo nie zanieczyszczają badania |
| 8. Estetyka i minimalizm | Bankowe zadanie pierwsze, pomiary i narzędzia demo na żądanie | Formularz i główna akcja dominują; brak marketingowych etykiet między krokami zadania |
| 9. Rozpoznanie i naprawa błędów | Tekst przy polu, focus, zachowane wartości, bezpieczne ponowienie | Błąd wskazuje przyczynę i sposób poprawy; timeout potwierdzenia nie zachęca do wysłania duplikatu |
| 10. Pomoc i dokumentacja | Instrukcje logowania, przelewu, kamery, urządzenia i presji | Pomoc jest dostępna z każdego kroku, a powrót przywraca ten sam kontekst i szkic |

## 4. Docelowy user flow

```text
kod uczestnika → zgody → logowanie → weryfikacja SMS → pulpit
                                                        ↓
                    dane przelewu → podsumowanie → ocena backendu
                                             ┌──────────┴──────────┐
                                       zwykła ścieżka        interwencja
                                             │                    │
                                             │           pytanie / weryfikacja
                                             │          ┌─────────┴────────┐
                                             │       anuluj         dopuszczona kontynuacja
                                             └──────────────┬─────────────┘
                                                     kod transakcji
                                                           ↓
                                                status konkretnego przelewu
                                                           ↓
                                                 konto / historia / ankieta
```

Decyzja „robię to samodzielnie” nie może automatycznie uchylać serwerowej blokady. Przy ryzyku przejęcia konta wymagane dodatkowe uwierzytelnienie jest osobną ścieżką. Brak oceny ma własny komunikat i politykę ustaloną po stronie backendu; frontend nie traktuje go jako akceptacji.

Przy żądaniu potwierdzenia, którego wynik nie dotarł, pokaż „Sprawdzamy status przelewu”. Najpierw odzyskaj wynik tej samej operacji. Nie zamieniaj timeoutu w „przelew nieudany” i nie twórz nowej operacji przy ponowieniu. Edycja odbiorcy lub kwoty unieważnia poprzednią ocenę i kod transakcji.

## 5. Architektura frontendu

Proponowany osobny katalog `frontend/`: React + TypeScript + Vite, React Router w trybie data oraz TanStack Query do stanu serwera. Wybrać zgodne stabilne wersje przy inicjalizacji i zapisać lockfile. Backend `aiohttp` pozostaje podstawą integracji. Nie przełączać brancha na `data-collection` ani nie kopiować jego odmiennych kontraktów do tego MVP.

CSS: lokalne tokeny, style komponentów i współdzielone prymitywy. Przenieść sprawdzony wygląd z mockupów. Formularze jako kontrolowane komponenty z jednym schematem walidacji, zgodnym z serwerem; pieniądze przeliczać na całkowite grosze. Kontrolki natywne, semantyczne etykiety i listy kroków. ReactBits można adaptować dla pojedynczej informacji o zmianie stanu, dopiero po sprawdzeniu dostępności, licencji i `prefers-reduced-motion`; nie obejmuje logiki bankowej.

```text
frontend/
  public/brand/               # SVG, lokalne fonty i OFL
  src/
    app/                     # router, providery, konfiguracja środowiska
    design/                  # tokeny, typografia, prymitywy, Bank24Logo
    layouts/                 # AuthShell, BankShell, StudyShell
    features/
      auth/                  # login, challenge, verify, logout, trusted device
      accounts/              # saldo, konto, historia
      transfers/             # szkic, preview, intervention, confirm, status
      camera/                # właściciel streamu/RTC, panel, stan pomiarów
      risk/                  # status oceny i wyjaśnienia
      study/                 # zgody, warunki badania, ankieta
      help/                  # pomoc w kontekście
      telemetry/             # zbieranie metadanych, kolejka i wysyłka
    services/                # klient HTTP, adaptery, błędy, typy API
    mocks/                   # MSW i scenariusze testowe; wyłączone w integracji
    tests/                   # integracja komponentów, E2E i dostępność
```

CameraProvider i właściciel połączenia są nad layoutami i nie znikają przy przejściu z logowania do konta. Zmienia się prezentacja panelu, a nie strumień. Parametry korzystają z wydzielonego magazynu/subskrypcji; kolejne klatki nie powodują renderowania formularza i utraty focusu. Oddzielić stan serwera, szkic przelewu i stan sprzętu. Nie utrzymywać tego wszystkiego w jednym kontekście aktualizowanym 30 razy na sekundę.

Rozdzielić identyfikatory sesji badania, uwierzytelnienia i kamery. Ich powiązanie ustala serwer. Adapter ryzyka zachowuje osobno `account_takeover_risk` i `coercion_risk`, z jakością oraz świeżością danych; UI nie łączy ich w pozornie pewny jeden wynik. Interwencja dotycząca tożsamości ma inną treść i działania niż ostrzeżenie przed presją podczas przelewu.

Telemetria zbiera wyłącznie uzgodnione metadane zdarzeń i etapu: odstępy czasowe, liczbę korekt, długość wejścia i ruch wskaźnika. Nie wysyła znaków, schowka, hasła, kodów ani treści pól. Kolejka jest ograniczona, wysyłana partiami i nie blokuje wpisywania. Rozdzielić czas monotoniczny zdarzenia od czasu odbioru na serwerze. Tryb pomiaru wyłącza wypełnianie demo i publiczne skróty. Zakres i warunki badania wynikają z konfiguracji serwera opisanej w `IMPLEMENTATION_PLAN.md`.

## 6. Routing, stan i komponenty

| Trasa docelowa | Warunek wejścia / dane | Główne komponenty |
| --- | --- | --- |
| `/study` i `/study/consent` | Kod i zgody z API badania | CodeEntry, ConsentForm |
| `/login` | Ograniczona sesja badania | AuthShell, LoginForm, DeviceChoice, CameraPanel |
| `/verify-login` | Ważne wyzwanie logowania | OtpField, ChallengeStatus, ResendAction |
| `/app` | Uwierzytelnienie i rachunek | BankShell, AccountOverview, RecentTransactions |
| `/app/history` | Uwierzytelnienie | TransactionTable, EmptyState, RetryState |
| `/app/transfers/new` | Konto i szkic | TransferForm, SourceDocument, FieldError |
| `/app/transfers/:id/review` | Wersjonowany preview zapisany przez API | TransferSummary, EditAction |
| `/app/transfers/:id/intervention` | Wymagana decyzja z API ryzyka | InterventionPanel, ReasonsDisclosure |
| `/app/transfers/:id/confirm` | Aktualne wyzwanie dla tej wersji przelewu | OtpField, SubmitState |
| `/app/transfers/:id/status` | Dostęp do konkretnej operacji | TransferResult, StatusRecovery |
| `/help` | Publiczne instrukcje, powrót do uprawnionej trasy | HelpTopics, ContextBackAction |

Layout bankowy nie renderuje nowych egzemplarzy panelu kamery przy każdym routingu. Bez ważnego challenge nie można otworzyć weryfikacji; bez aktualnego preview nie można przejść do potwierdzenia. Odpowiedź 401 czyści cache danych konta i kieruje do logowania. Docelowa strona nie oferuje publicznych skrótów omijających uwierzytelnienie.

Szkic przed preview pozostaje w pamięci; nawigacja wewnątrz przepływu go zachowuje. Wyjście z niezapisanym szkicem wymaga wyraźnego wyboru zachowania lub odrzucenia. Po preview backend przechowuje wersjonowany szkic, który loader może odzyskać po odświeżeniu. Obsługa tego zapisu jest wymaganiem API, nie obecną funkcją serwera. Hasła, kody i tokeny nie trafiają do `localStorage`, logów ani telemetrii.

## 7. Integracja z obecnym backendem

### Działa jako kontrakt w branchu `backend`

| Endpoint | Wykorzystanie frontendu |
| --- | --- |
| `POST /api/webrtc/offer` | Wymiana kompletnego SDP po ICE gathering; odpowiedź zawiera identyfikator i URL wyników |
| `GET /api/sessions/{camera_session_id}/output` | Snapshot po połączeniu / odzyskaniu komunikacji |
| `WS /api/sessions/{camera_session_id}/events` | Aktualizacje analizy; dedykowany magazyn pomiarów |
| `DELETE /api/sessions/{camera_session_id}` | Zakończenie sesji i zwolnienie zasobów |
| `GET /health` | Dostępność usługi, odrębna od jakości pomiaru |

Aktualne wyniki obejmują m.in. `timestamp`, `heart_rate_bpm`, `face_detected`, `sampling_fps`, `window_seconds`, `posture`, `expression`, `status`. `heart_rate_bpm: null` daje komunikat zbierania próbek lub niedostępności. `face_detected` nie oznacza potwierdzenia tożsamości. Mapować `waiting`, `preview`, `warming_up`, `measuring`, `error`, `ended`, `closed` na polskie etykiety; nieznany status pokazać jako nieobsługiwany, nie jako gotowy pomiar.

Wprowadzić stan `stale` po braku aktualizacji, z proponowanym progiem 5000 ms w konfiguracji uzgadnianej z backendem. Stare liczby nie są prezentowane jako bieżące. Obecny `timestamp` nie jest gwarantowanym czasem ekspozycji klatki. Przy ponownym połączeniu użyć tej samej sesji badania i jawnie nowego połączenia kamery.

### Kontrakty bankowego flow i dalsze rozszerzenia

Kontrakty `/api/bank/*`, `/api/study/*` i `/api/telemetry/*` wdrożono w `bank24_server.py`; aktualny opis jest w `BANK24_API.md`. Odrębna usługa `/api/risk/*` i zwalidowane klasyfikatory pozostają do implementacji. Poniższa lista zachowuje wymagania docelowe: większość obsługuje lokalne API, natomiast rzeczywiste SMS, modele i produkcyjny odbiór pozostają otwarte.

- Login i verify: identyfikator challenge, termin ważności, cooldown, limit prób oraz odrębne błędy logowania. Uwierzytelnienie w cookie `HttpOnly`; pamiętanie urządzenia jest oddzielnym tokenem po pełnej weryfikacji.
- Zapamiętane urządzenie: czas ważności i zakres ustala API; przy checkboxie wyjaśnić skutek wyboru. Zapewnić możliwość cofnięcia zaufania. Zaufanie urządzeniu nie zastępuje wymaganego potwierdzenia przelewu.
- Preview przelewu: identyfikator, wersja szkicu, kwota w groszach, wynik walidacji oraz wymagana dalsza czynność. Numer NRB walidować również sumą kontrolną; fikcyjne konta generować jako poprawne numery testowe.
- Interwencja: jawny status, wyjaśnienia, dozwolone akcje, wersja oceny oraz związanie jej z wersją przelewu. Odpowiedź użytkownika rejestrowana serwerowo.
- Challenge transakcji: utworzenie/weryfikacja kodu dla konkretnego odbiorcy, kwoty i wersji. To odrębny kontrakt od `/api/bank/verify` dla logowania.
- Submit: obsługa klucza idempotencji i zwrot trwałego identyfikatora operacji. Do odzyskania wyniku proponować `GET /api/bank/transfers/{id}` lub równoważne uzgodnione API statusu.
- Historia rachunku: proponowane `GET /api/bank/transactions`, spójne z saldem i statusem przelewu; paginacja oraz pusta lista.
- Ochrona wyników i WebSocket kamery: serwer sprawdza dostęp do powiązanej sesji. Obecne techniczne API kamery nie jest gotowym mechanizmem autoryzacji klienta bankowego.

W dev Vite proxy kieruje API i WebSocket do `aiohttp`. W integracji UI i API mają jeden origin; konfigurację cookies i HTTPS sprawdzić w obu środowiskach. Mock API ma być jawnie oddzielone i nie może być cichym fallbackiem po błędzie prawdziwego serwera.

Dla żądań zmieniających stan uzgodnić ochronę CSRF z backendem oraz sprawdzanie originu, również podczas zestawiania WebSocket. Frontend wysyła wymagany token, a serwer egzekwuje ochronę; samo cookie nie zastępuje tej kontroli. Zgoda przed rzeczywistą integracją kamery musi wyjaśniać transmisję do serwera i cel analizy, zamiast kopiować obietnicę lokalnego podglądu z mockupu.

## 8. Stany obowiązkowe i dostępność

| Obszar | Stany wymagane poza happy path |
| --- | --- |
| Login / OTP | Błędne dane, wygaśnięcie, limit prób, cooldown, pending, offline, powrót |
| Konto / historia | Loading, dane, brak operacji, błąd pobrania, sesja wygasła |
| Przelew | Niepełne dane, zły rachunek, błędna kwota, brak środków, nieaktualny preview, zapis szkicu |
| Potwierdzenie | Pending, zły/wygaśnięty kod, odrzucona operacja, wynik nieznany, odzyskiwanie statusu |
| Kamera | Wyłączona, zgoda, uruchamianie, brak urządzenia, odmowa, aktywna, przerwana, stale, błąd |
| Ryzyko | Dostępne, ograniczone, niewystarczające dane, niedostępne, nieaktualne, interwencja |

Cel dostępności: WCAG 2.2 AA, z ręcznym sprawdzeniem klawiatury i czytnika ekranu. Kontrast tekstu co najmniej 4,5:1, widoczny focus, cele dotykowe co najmniej 44 px, zoom i reflow. Granatowe główne przyciski mają biały tekst. Miętowa akcja na granatowym rachunku ma granatowy tekst. Logo ma własny opis; dekoracyjne ikony są ukryte przed czytnikiem.

Pojedyncze pole OTP wspiera wklejanie i `autocomplete="one-time-code"`; brak automatycznego wysłania po ostatniej cyfrze. Kody i hasła nie są blokowane dla menedżerów haseł. Błędy mają `aria-invalid`, powiązany opis i focus na właściwym polu. `aria-busy` i komunikat statusu obejmują żądanie, a krok ma `aria-current="step"`. Żadna animacja nie opóźnia wejścia do formularza; reduced motion wyłącza efekty.

## 9. Kolejność implementacji i bramki odbioru

| Etap | Zakres | Bramka przed dalszą pracą |
| --- | --- | --- |
| F0 — kontrakty | Potwierdzić API, autoryzację, challenge, status i idempotencję; sprawdzić stan modeli | Typy i mock odpowiedzi obejmują stany błędów; odróżnione istniejące i nowe API |
| F1 — fundament | `frontend/`, React/TS/Vite, router, tokeny, logo, fonty, komponenty i MSW | Shell i formularze działają od 375 do 1920 px, klawiaturą i z reduced motion |
| F2 — bankowy flow | Login, SMS, konto, historia, szkic, preview, kod transakcji i wynik | Działają powroty, edycja, odświeżenie preview i zwykły przelew bez interwencji |
| F3 — kamera | Jeden właściciel streamu, consent, WebRTC, WS, panel, stale i cleanup | Zmiana trasy nie tworzy drugiego streamu; odmowa nie blokuje banku; logout zwalnia zasoby |
| F4 — SafeTransfer | Obsłużyć decyzję serwera i wymagane działania, zachować szkic | Nie da się ominąć blokady ani użyć starego kodu po zmianie danych |
| F5 — integracja badania | Zgody, etapowanie, telemetria, scenariusze i ankieta | Telemetria bez wpisanych treści; narzędzia demo niedostępne w pomiarze |
| F6 — odbiór | E2E, dostępność, awarie, zgodność heurystyk, build i demonstracja | Wszystkie scenariusze niżej przechodzą; prototyp i aplikacja są jasno rozróżnione |

Testy integracyjne: walidacja pól i groszy, mapowanie błędów API, wymagane gałęzie interwencji, przeterminowanie oceny i challenge. Playwright: oba user flow, nieprawidłowy OTP, edycja, anulowanie, podwójny submit, timeout z odzyskaniem statusu, offline, 401, bezpośrednie linki i powrót po pomocy. Test kontrolowanego streamu: brak drugiego `getUserMedia`, opóźniona zgoda po anulowaniu, zakończenie tracku, brak aktualizacji WS.

Odbiór wizualny: 375, 768, 900, 1024, 1440 i 1920 px; także viewport przy zoomie 200%, długi odbiorca i długi tytuł. Odbiór dostępności: axe jako wsparcie, ręczny Tab/Enter/Escape, focus po zmianie trasy oraz test czytnikiem. Testy z uczestnikami: znajdowanie przelewu, rozumienie ostrzeżenia i jego bezpiecznej ścieżki, powrót do edycji bez pomocy prowadzącego.

## 10. Źródła i artefakty

- [Nielsen Norman Group — 10 heurystyk](https://www.nngroup.com/articles/ten-usability-heuristics/): podstawa oceny użyteczności.
- [React — komponenty i stan](https://react.dev/learn), [React Router — routing](https://reactrouter.com/start/data/routing), [TanStack Query — dane serwera](https://tanstack.com/query/latest/docs/framework/react/overview), [Vite — uruchomienie projektu](https://vite.dev/guide/): dokumentacja do wdrożenia proponowanej architektury.
- `PRODUCT.md`, `DESIGN.md`, `IMPLEMENTATION_PLAN.md`: uzgodniony kontekst i rozwój backendu.
- `mockups/index.html`, `mockups/app.js`, `mockups/styles.css`: referencyjny interfejs i działający przepływ demonstracyjny.
- `mockups/brand.html`, `mockups/assets/bank24-*.svg`, `mockups/assets/OFL.txt`: identyfikacja Bank24 i licencja fontu.
