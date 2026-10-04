# SafeTransfer / Bank24: plan implementacji

Plan przygotowany 3 października 2026 na podstawie lokalnego brancha `backend`, commit `0261234` (`finished webrtc server`), dokumentu `PROJECT_CONTEXT.md` dostarczonego przez użytkownika i zadania HackYeah „Open Task: Defence”.

To plan rozwoju istniejącego kodu. Stan poniżej został ustalony przez odczyt plików; nie oznacza potwierdzenia działania aplikacji ani dokładności pomiarów na tym komputerze.

**Aktualizacja realizacji:** dodano działający pierwszy etap aplikacji React i serwerową bankowość demonstracyjną z trwałym SQLite, wyzwaniami, ochroną sesji, wersjonowaniem oraz idempotencją. Kamera jest zintegrowana przez autoryzowany gateway. Telemetria, zgody, ankieta i wycofanie działają. Nie jest to jeszcze ukończony MVP oceny behawioralnej: profile właściciela, klasyfikatory, walidacja i konfiguracja operatora pozostają otwarte. `null` opisuje brak oceny; deklaracja presji jest osobną regułą serwera. Wdrożony kontrakt: [BANK24_API.md](BANK24_API.md), uruchomienie i zakres: [frontend/README.md](frontend/README.md). Tabela stanu obecnego poniżej opisuje punkt startowy planu.

Szczegółowy plan docelowego frontendu React, identyfikacja fintech, przegląd obecnych mockupów i kryteria dziesięciu heurystyk Nielsena są w [FRONTEND_IMPLEMENTATION_PLAN.md](FRONTEND_IMPLEMENTATION_PLAN.md). Ta specyfikacja rozwija część UI niniejszego planu i rozdziela istniejące API kamery od proponowanych kontraktów bankowych.

## 1. Cel i zakres

Zbudować demonstracyjną aplikację bankową Bank24 z warstwą SafeTransfer. Użytkownik loguje się, wykonuje fikcyjny przelew i otrzymuje proporcjonalną interwencję, kiedy zachowanie lub kontekst wskazują na zwiększone ryzyko.

System zachowuje dwa niezależne wyniki:

- `account_takeover_risk`: odchylenie zachowania operatora od profilu właściciela konta;
- `coercion_risk`: nietypowe zachowanie właściciela podczas przelewu, które może uzasadniać pytania o manipulację lub presję.

Pierwsza wersja ma pokazać cały przepływ: sygnały -> ocena -> wyjaśnienie -> dodatkowa weryfikacja albo ostrzeżenie. Sam zapis telemetrii nie stanowi ukończonego MVP.

Bank24 używa wyłącznie fikcyjnych kont, danych i przelewów. Pomiar pulsu, wykrycie twarzy i etykiety mimiki nie potwierdzają tożsamości, nie diagnozują emocji i nie są samodzielnym dowodem oszustwa.

## 2. Stan obecnego brancha

| Element | Obecny stan | Decyzja |
| --- | --- | --- |
| Serwer | `webrtc_server.py`, `aiohttp`, `aiortc` | Zachować jako podstawę MVP |
| Kamera z przeglądarki | WebRTC, odbiór wideo, zwrot wideo z naniesionymi oznaczeniami | Wykorzystać istniejący transport |
| Parametry na żywo | REST snapshot i WebSocket | Zachować istniejące API kamery |
| Analiza | PhysNet oraz MediaPipe; regułowe etykiety postawy i mimiki | Podłączyć do interfejsu, dodać jakość i świeżość pomiarów |
| Sesje kamery | Oddzielny procesor i historia; limit sesji i timeout; stan w pamięci | Oddzielić od trwałych sesji badania i logowania |
| Frontend | `static/webrtc.html`, techniczne demo dwóch podglądów | Zachować jako narzędzie diagnostyczne; zbudować osobny frontend Bank24 |
| Testy | Testy wejścia API, transportu, aktualizacji, zamykania sesji i wywołania PhysNet | Zachować i rozszerzać przy implementacji |
| Bank24 | Brak logowania, drugiego kroku, kont i przelewów | Zaimplementować |
| Telemetria zachowania | Brak klawiatury, myszy i cech formularzy | Zaimplementować |
| Ryzyko i profil użytkownika | Brak | Zaimplementować w P0 |
| Zapis i operator | Brak trwałego badania, panelu operatora i eksportu | Dodać podstawowy zapis w P0, rozbudowę w P1 |

### Zależność wymagająca naprawy

`rPPG-Toolbox` jest zapisany w Git jako gitlink (`160000`), lecz lokalny katalog jest pusty, a repozytorium nie ma `.gitmodules`. Nie znaleziono:

- `rPPG-Toolbox/neural_methods/model/PhysNet.py`;
- `rPPG-Toolbox/final_model_release/UBFC-rPPG_PhysNet_DiffNormalized.pth`.

Modele MediaPipe `models/face_landmarker.task` i `models/pose_landmarker_lite.task` są obecne. Plik `emotion-ferplus-8.onnx` jest obecny, ale aktualny kod `PostureExpression` nie używa go: etykiety mimiki pochodzą z reguł na wynikach MediaPipe.

Przed integracją pomiaru pulsu ustalić źródło i wersję zależności, sposób pobierania wag oraz licencje. Udokumentować reprodukowalny setup. Nie wpisywać domyślnych BPM, jeśli model nie działa. Sprawdzić osobno uruchomienie w trybie podglądu oraz z pełną analizą.

## 3. Architektura docelowa MVP

### Backend

Rozbudować istniejący `aiohttp` o moduły domenowe. Nie przenosić transportu WebRTC do FastAPI w P0. Zmiana frameworka nie jest potrzebna do osiągnięcia celu demonstracji.

Proponowany podział:

```text
webrtc_server.py              # istniejący transport i diagnostyka kamery
camera_estimator.py           # istniejące funkcje analizy
server/
  app.py                     # składanie aplikacji i wspólnych usług
  api/
    study.py
    bank.py
    telemetry.py
    risk.py
    admin.py
  domain/
    participants.py
    sessions.py
    identities.py
    devices.py
    risk.py
  services/
    camera_link.py
    telemetry.py
    features.py
    baseline.py
    risk.py
    interventions.py
    exports.py
  storage/
    metadata.py
    events.py
web/                         # proponowany React + TypeScript + Vite
data/                        # pliki badania; poza Git
```

SQLite przechowuje metadane uczestników, sesji, profili, fikcyjnych kont i zaufanych urządzeń. Zdarzenia można zapisywać w JSONL z późniejszym eksportem do Parquet. W P0 kamera nie wymaga zapisu surowego nagrania.

Frontend React/TypeScript/Vite to propozycja z wcześniejszego kontekstu; obecny branch zawiera zwykły HTML. Mockupy powstaną dopiero po odpowiedziach dotyczących interfejsu. Na etapie implementacji jeden origin i proxy developerskie uproszczą cookies, REST i WebSocket.

### Trzy różne rodzaje sesji

1. Sesja badania istnieje również bez kamery i łączy zgodę, scenariusz i telemetrię.
2. Sesja uwierzytelnienia identyfikuje zalogowane fikcyjne konto.
3. Sesja WebRTC istnieje tylko, kiedy działa analiza kamery.

Powiązanie `study_session_id` z `camera_session_id` zapisuje backend. Ponowne połączenie WebRTC nie tworzy nowego uczestnika, nowego profilu ani nowego badania. Operator sesji intruza i właściciel konta mogą być różnymi osobami.

## 4. Wymagania ekranów

### Ekran logowania: ustalone wymagania użytkownika

Na desktopie dwie kolumny:

- po prawej kamera, stan jej działania i wysuwany panel parametrów;
- po prawej login, hasło, checkbox „Zapamiętaj urządzenie” i przycisk logowania.

Kamera uruchamia się po zgodzie i świadomym działaniu użytkownika. Przed uruchomieniem jej miejsce zajmuje czytelny stan z przyciskiem aktywacji. Odmowa uprawnienia nie uniemożliwia logowania.

Podgląd lokalny zapewnia natychmiastowy obraz. Opcjonalny widok z oznaczeniami pochodzi z istniejącego zdalnego tracku. Dwa obrazy nie muszą być stale widoczne; wariant zwykły/z oznaczeniami może mieć przełącznik.

Panel parametrów rozróżnia aktualnie dostępne dane i planowane rozszerzenia:

| Parametr | Źródło i prezentacja |
| --- | --- |
| Estymowany puls | `heart_rate_bpm`; „zbieranie próbek” lub „niedostępny”, gdy brak wyniku |
| Wykrycie twarzy | `face_detected`; informacja o obrazie, bez deklaracji potwierdzenia tożsamości |
| Postawa | `posture`; zrozumiałe polskie etykiety |
| Mimika | `expression`; opis obserwacji, bez etykiety „stres” |
| Stan analizy | `status`; oczekiwanie, rozgrzewanie, pomiar, podgląd, błąd |
| Częstotliwość próbkowania i długość okna | `sampling_fps`, `window_seconds`; szczegóły techniczne |
| Jakość i świeżość | Nowe pola, wymagają implementacji; nie przedstawiać FPS jako jakości pomiaru |
| Wyniki ryzyka | Nowa usługa SafeTransfer; pojawiają się tylko, gdy jest wystarczająca ilość danych |

Użytkownik potwierdził jasny interfejs w bieli i granacie z dyskretnym akcentem. Parametry rozwijają się spod kamery i są początkowo zwinięte. Kamera pozostaje w bocznym panelu po zalogowaniu i podczas przelewu. Na wąskim ekranie formularz i kamera układają się w jednej kolumnie; formularz pozostaje łatwo dostępny.

### „Zapamiętaj urządzenie”

Checkbox jest domyślnie odznaczony. Nie zapisuje loginu ani hasła w `localStorage`.

Po udanym pełnym uwierzytelnieniu backend może utworzyć losowy token urządzenia w cookie `HttpOnly`, `SameSite` i `Secure` dla HTTPS. Serwer przechowuje skrót tokenu, właściciela, termin ważności i możliwość unieważnienia. Dla lokalnego HTTP potrzebna jest jawna konfiguracja developerska.

Znane urządzenie jest sygnałem kontekstowym. Nie jest dowodem, że operatorem jest właściciel, i w P0 nie omija symulowanego drugiego kroku logowania. Token urządzenia nie daje samodzielnego dostępu do konta.

### Proponowany przepływ klienta

```text
kod uczestnika i zgoda
  -> logowanie z kamerą
  -> symulowany kod SMS
  -> pulpit konta
  -> formularz przelewu
  -> podsumowanie
  -> ewentualna interwencja
  -> wynik fikcyjnego przelewu
```

Formularz ma odbiorcę, 26-cyfrowy numer rachunku, kwotę i tytuł. Dane pochodzą z faktury, instrukcji lub nagrania scenariusza. W badaniu uczestnik wpisuje je samodzielnie; aplikacja rejestruje wklejenie bez zapisywania treści schowka.

Użytkownik wybrał klikalny prototyp w przeglądarce: logowanie, kod SMS, pulpit, przelew i ostrzeżenie. Mockupy używają jawnie przykładowych danych i nie są dowodem działania modeli. Prototyp w `mockups/` jest samodzielnym HTML/CSS/JS, zgodnie z obecnym statycznym sposobem prezentacji; aplikacja docelowa może używać proponowanego React/Vite.

## 5. Kontrakty API

### Zachować istniejące API kamery

```text
POST   /api/webrtc/offer
GET    /api/sessions/{camera_session_id}/output
WS     /api/sessions/{camera_session_id}/events
DELETE /api/sessions/{camera_session_id}
GET    /health
```

Zachować odpowiedź SDP wraz z `session_id`, `output_url` i `events_url`. Browser czeka na zakończenie ICE gathering przed wysłaniem oferty. Obecne demo używa host candidates; STUN/TURN należy skonfigurować przed demonstracją między różnymi sieciami.

Rozszerzenia powinny być addytywne: wersja schematu, identyfikator badania, czas ostatnich danych, stan gotowości modeli i jakość sygnału. Utrata aktualizacji ma wygasić poprzednie liczby w UI po określonym czasie, zamiast zostawiać je jako aktualne.

Obecne API nie uwierzytelnia dostępu. Nowa aplikacja musi sprawdzać uprawnienia do powiązanej sesji kamery również przy pobieraniu wyniku, otwieraniu WebSocket i zamykaniu połączenia. Przed logowaniem dostęp zapewnia ograniczony token sesji badania wydany po onboardingu; po logowaniu powiązanie zatwierdza backend.

### Dodać API aplikacji

```text
POST   /api/study/participants                    # operator
POST   /api/study/resolve-code
POST   /api/study/consent
POST   /api/study/sessions
POST   /api/study/sessions/{id}/start
POST   /api/study/sessions/{id}/stage
POST   /api/study/sessions/{id}/complete
POST   /api/study/sessions/{id}/abort
POST   /api/study/participants/{id}/withdraw

POST   /api/bank/login
POST   /api/bank/verify
POST   /api/bank/logout
GET    /api/bank/account
POST   /api/bank/transfers/preview
POST   /api/bank/transfers/submit

POST   /api/telemetry/batch
GET    /api/risk/study-sessions/{id}/latest
GET    /api/risk/study-sessions/{id}/timeline

GET    /api/admin/participants
GET    /api/admin/sessions
GET    /api/admin/sessions/{id}
POST   /api/admin/exports
```

Przestrzeń `/api/study/` zapobiega kolizji z istniejącymi `/api/sessions/` dla WebRTC. Powiązania uczestnika, konta i uprawnień ustala serwer, nie wartości dostarczone w telemetrycznym payloadzie.

Zachować WebSocket kamery. Wynik ryzyka w pierwszej integracji może być pobierany okresowo i przed potwierdzeniem przelewu. SSE lub wspólny kanał aktualizacji ryzyka można dodać później, kiedy będzie potrzebny.

## 6. Telemetria, profil i ocena ryzyka

### Telemetria

- Klawiatura: kategoria klawisza, czasy naciśnięcia i zwolnienia, powtórzenia, korekty, zmiany pól. Bez wartości znaków hasła, numeru rachunku czy innych wpisanych treści.
- Parowanie zdarzeń do dwell time: lokalny identyfikator naciśnięcia albo lokalnie policzona cecha; sama kategoria „litera” nie rozróżnia jednocześnie wciśniętych klawiszy.
- Mysz/pointer: znormalizowane współrzędne, typ urządzenia, kliknięcia i postoje; ograniczyć częstotliwość próbkowania.
- Formularz: pole, focus/blur, metadane zmiany, wklejenie, etap i potwierdzenie. Dane fikcyjnego przelewu należą do API przelewu, nie surowej telemetrii zachowania.
- Kontekst: znane urządzenie, rodzaj przeglądarki, viewport i czas sesji; dodatkowe dane tylko z jasno określonym zastosowaniem.
- Zdarzenia wysyłać partiami co około 250-1000 ms. Każde ma identyfikator, numer sekwencji, czas klienta i czas odbioru na serwerze. Ponowienie partii nie duplikuje zdarzeń.
- Zegar `performance.now()` utrzymywać w jednym kontekście sesji; przy pełnym przeładowaniu zapisać nową kotwicę czasu. Powiązać okna kamery z badaniem z jawną informacją o opóźnieniu i przybliżeniu synchronizacji. Obecny `timestamp` kamery nie jest czasem naciśnięcia klawisza ani gwarantowanym czasem ekspozycji klatki.

### Profil bazowy

Zarejestrować spokojne sesje właściciela konta, osobno dla etapów logowania i przelewu. Zapisać wersję profilu, liczbę obserwacji i zakres dostępnych modalności. Porównywać cechy przez medianę i MAD z dolnym ograniczeniem skali.

Brak profilu lub niewystarczające dane oznaczają „profil jeszcze niegotowy”, a nie ryzyko równe zero. Sesje intruza porównywać z profilem właściciela konta. Sam czas kalibracji kamery nie tworzy profilu zachowania przy przelewie.

### Silnik MVP

Pierwsza wersja: jawne reguły odchyleń i kontekstu, z oddzielnymi wynikami przejęcia konta i presji. Nazywać je wskaźnikami ryzyka; bez walidacji i kalibracji nie deklarować, że wynik jest prawdopodobieństwem oszustwa.

Odpowiedź obejmuje:

- oba wyniki lub `null`, jeśli nie można ich obliczyć;
- `assessment_status`: gotowy, niewystarczające dane, ograniczona ocena albo niedostępny;
- maskę dostępnych sygnałów oraz powody braków;
- wyjaśnienia odchyleń;
- wersję mechanizmu i proponowaną interwencję.

Nazwa scenariusza, odtwarzanie nagrania oszusta i etykieta `intruder` służą do organizacji badania. Nie wolno nimi ustawiać odpowiedzi modelu. Oddzielić scenariuszowe metadane od cech używanych do inferencji.

Puls i mimika są opcjonalnymi informacjami pomocniczymi. Najpierw uruchomić ocenę na klawiaturze, pointerze i kontekście; dołączenie kamery wymaga kontroli jakości i osobnego porównania wyników.

### Interwencje

- Niskie ryzyko i wystarczające dane: zwykły przebieg.
- Podwyższone ryzyko: krótkie wyjaśnienie i dodatkowe potwierdzenie.
- Wysokie ryzyko przejęcia: dodatkowa symulowana weryfikacja tożsamości.
- Wysokie ryzyko manipulacji: ostrzeżenie, pytania o rozmowę i „bezpieczne konto”, możliwość przerwania przelewu i kontaktu oficjalnym kanałem.
- Niedostępna ocena: jawny komunikat i wcześniej ustalony dodatkowy krok bezpieczeństwa, bez zielonej deklaracji ochrony.

Politykę zaimplementować osobno od wyliczania wskaźników. Backend ponownie sprawdza warunki przy `submit`; samo zamknięcie ostrzeżenia w UI nie zatwierdza przelewu. Powtórzenie żądania nie tworzy drugiego fikcyjnego przelewu.

## 7. Etapy realizacji

### Etap 0: odtwarzalna baza

1. Odtworzyć brakującą zależność PhysNet i udokumentować źródła, wersje, licencje oraz setup.
2. Uruchomić dotychczasowe testy i próbę z kamerą; oddzielić potwierdzenie transportu od walidacji dokładności pulsu.
3. Ustalić konfigurację hosta, HTTPS i WebRTC dla środowiska demo.
4. Rozszerzyć `.gitignore` o dane, nagrania, eksporty, sekrety i zależności frontendu.

Rezultat: istniejące API kamery uruchamia się powtarzalnie albo jawnie działa w ograniczonym trybie.

### Etap 1: decyzje frontendowe i mockupy

1. Zebrać odpowiedzi o stylu, zestawie ekranów, panelu parametrów, kamerze po logowaniu i formie mockupów.
2. Przygotować logowanie zgodnie z ustalonym podziałem lewo/prawo, wraz ze stanami odmowy kamery i oczekiwania na pomiar.
3. Opracować pozostałe wybrane ekrany i spójne zasady typografii, kolorów, odstępów oraz interakcji.
4. Rozróżnić przykładowe dane prototypu od faktycznych pomiarów backendu.

Rezultat: uzgodniony kierunek ekranów przed implementacją aplikacji.

### Etap 2, P0: badanie i Bank24

1. Trwały uczestnik, zgoda, sesja badania i fikcyjna tożsamość bankowa.
2. Logowanie, symulowany kod SMS, logout i zapamiętanie urządzenia.
3. Pulpit, ręczne wprowadzanie przelewu, podsumowanie i wynik.
4. Ograniczone uprawnienia sesji przed logowaniem, ochrona sesji kamery i podstawowe logowanie operatora.

Rezultat: pełny przepływ Bank24 działa również bez kamery.

### Etap 3, P0: podłączenie kamery i telemetrii

1. Podgląd i połączenie WebRTC działają w nadrzędnym kontekście aplikacji, bez restartu przy każdym przejściu ekranu.
2. Panel korzysta z rzeczywistych odpowiedzi backendu; obsługuje `null`, rozgrzewanie, błędy i nieaktualny wynik.
3. Zbieranie klawiatury, myszy i etapów formularza; partie, ponawianie, ograniczony bufor i zapis.
4. Utrata kamery nie zatrzymuje logowania, przelewu ani pozostałej telemetrii. Zamknięcie badania zwalnia tracki, WebSocket i sesję serwera.

Rezultat: zsynchronizowane na potrzeby prototypu dane dostępne dla ekstrakcji cech.

### Etap 4, P0: wykrywanie i reakcja

1. Ekstrakcja cech logowania i przelewu.
2. Profil bazowy właściciela i jawny stan jego gotowości.
3. Dwa wskaźniki ryzyka, wyjaśnienia i obsługa brakujących modalności.
4. Interwencje egzekwowane również przez backend.
5. Scenariusze spokojnego przelewu, spokojnego dyktowania, presji i intruza. Nagrania dyktowania i oszusta ruszają dopiero po zalogowaniu.
6. Podstawowy widok operatora do utworzenia uczestnika, wyboru scenariusza i sprawdzenia przebiegu.

Rezultat: demonstracja ochrony użytkownika od początku do końca, bez ustawiania wyniku przez scenariusz.

### Etap 5, P1: dane i walidacja

1. Rozbudować panel operatora, sekwencje scenariuszy, losowanie kolejności i końcową spokojną sesję.
2. Eksport zdarzeń, cech i etykiet do Parquet z udokumentowanym schematem.
3. Nagrywanie tylko w badaniu, za oddzielną zgodą; retencja i usuwanie danych uczestnika.
4. Ocenić działanie na zebranych sesjach. Dzielić dane według uczestników; referencyjny profil nowej osoby budować wyłącznie z wyznaczonych spokojnych sesji, bez dopasowywania na sesjach testowych.
5. Osobno porównać spokojne dyktowanie z presją oraz warianty bez kamery/z kamerą. Raportować również fałszywe alarmy i ograniczenia próby.

Rezultat: materiał do poprawy mechanizmu i uczciwej prezentacji jego ograniczeń.

### Etap 6, P2: rozwój

Trenowany model tabularny, modele tożsamości behawioralnej, dodatkowe cechy kamery, porównanie metod rPPG, zaawansowana fuzja i analityka. Lokalna analiza kamery bez wysyłania klatek jest osobnym kierunkiem produkcyjnym, nie cechą obecnego serwera WebRTC.

## 8. Obsługa braków i awarii

| Sytuacja | Oczekiwane zachowanie |
| --- | --- |
| Brak zgody lub kamery | Logowanie i przelew dostępne; ryzyko wykorzystuje pozostałe sygnały |
| Twarz znika lub puls nie jest gotowy | Brak aktualnej wartości BPM; bez używania starego pomiaru jako nowego |
| WebRTC/WS zostaje zerwany | Lokalny podgląd może pozostać; analiza oznaczona jako niedostępna, ograniczone próby ponownego połączenia |
| Limit sesji kamery | Czytelny komunikat, możliwość kontynuowania bez analizy kamery |
| Brak profilu właściciela | Stan niegotowego profilu; dodatkowa weryfikacja, bez pewnej oceny tożsamości |
| Awaria silnika ryzyka | Jawnie niedostępna ocena i ustalony krok bezpieczeństwa |
| Awaria API Bank24 | Zachowanie formularza i możliwość ponowienia; brak fikcyjnego komunikatu sukcesu |
| Przepełnienie bufora zdarzeń | Jawna informacja o utracie części danych; luki zapisane w metadanych |
| Restart serwera kamery | Sesja badania i profil pozostają w trwałym storage; nowy transport ma nowe powiązanie |

## 9. Prywatność i bezpieczeństwo prototypu

- Zgoda na telemetrię, analiza kamery i zapis nagrania to odrębne decyzje.
- Obecny WebRTC wysyła obraz do serwera. Ekran zgody musi to jasno opisywać. Brak nagrywania nie oznacza braku transmisji wideo.
- Kamera nie zbiera audio. Dźwięk scenariusza to odtwarzany materiał, nie nagranie mikrofonu uczestnika.
- W P0 nie zapisywać surowego obrazu. W P1 zapis nagrania wymaga oddzielnej zgody, kontroli dostępu i retencji.
- Hasła fikcyjnych kont przechowywać jako skróty do uwierzytelnienia, nie w telemetrii, logach ani lokalnym storage przeglądarki.
- Chronić endpointy Bank24, operatora i kamery; zastosować ograniczenia prób logowania, walidację żądań i ochronę operacji przy uwierzytelnianiu cookie.
- Rejestrować utratę i jakość danych. Nie nazywać etykiet mimiki „wykrytym stresem” ani `face_detected` „weryfikacją twarzy”.
- Zachować możliwość wycofania uczestnika i usunięcia danych oraz ich eksportów zgodnie z przyjętym zakresem retencji.

## 10. Sprawdzenie implementacji i definicja ukończenia P0

Przy implementacji zachować obecne testy i dodać sprawdzenia istotnych zachowań:

1. Logowanie z drugim krokiem, błędne dane, znane/nowe urządzenie, wygaszenie tokenu i brak dostępu do cudzej sesji.
2. Partie telemetrii: kolejność, deduplikacja, ponowienie, brak sekretów i powiązanie sesji ustalone przez serwer.
3. Cechy i profil: brak danych, brak modalności i prawidłowy profil właściciela przy scenariuszu intruza.
4. Interwencje: oba rodzaje ryzyka, niewystarczająca ocena, dodatkowy krok przed `submit` i bezpieczne ponowienie żądania.
5. Interfejs: pełny przepływ w przeglądarce, panel parametrów, odmowa kamery, rozłączenie analizy, klawiatura, focus i brak poziomego przewijania.
6. Faktyczna kamera na sprzęcie demonstracyjnym: dostępność modeli, opóźnienia i stabilność. Test transportu nie potwierdza dokładności rPPG ani wykrywania manipulacji.

P0 jest ukończone, kiedy użytkownik może przejść cały przepływ Bank24, system faktycznie oblicza wskaźniki z dostępnych danych, pokazuje przyczynę interwencji i egzekwuje ją przed fikcyjnym przelewem. Kamera może być niedostępna. Ocena może być niepewna, ale ten stan musi być jawny.

## 11. Mockupy: brief do ustalenia z użytkownikiem

Ustalone w nowszym zestawie mockupów: formularz logowania po lewej, kamera po prawej, wysuwane parametry i checkbox zapamiętania urządzenia.

Potwierdzone odpowiedzi: jasny nowoczesny bank, biel i granat, dyskretny akcent; logowanie, kod SMS, pulpit, przelew i ostrzeżenie; parametry rozwijane spod kamery i początkowo zwinięte; klikalny prototyp w przeglądarce z przykładowymi danymi; kamera w bocznym panelu także podczas przelewu. Język roboczy interfejsu: polski. Brand roboczy: Bank24 / SafeTransfer, bez znaków prawdziwego banku.

Zainstalowane na życzenie użytkownika zestawy:

- [Taste Skill](https://github.com/leonxlnx/taste-skill), lokalny skill `design-taste-frontend`;
- [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), lokalny skill `ui-ux-pro-max` wraz z danymi i skryptami;
- [Impeccable](https://github.com/pbakaus/impeccable), lokalny skill `impeccable` wraz z referencjami i skryptami.

Aktualny Taste Skill kieruje głównie do stron marketingowych i wyłącza wieloetapowe UI produktu ze swojego zakresu. Ekrany bankowe projektować z użyciem UI/UX Pro Max i Impeccable, stosując wskazówki Taste tylko tam, gdzie pasują do konkretnej powierzchni.

Przygotować mockupy według tych odpowiedzi i zachować ten dokument jako plan dalszej implementacji. Zmiany interfejsu uzgodnione podczas przeglądu aktualizują ten sam plan.

## 12. Materiały konkursowe

Przygotować opis problemu, odbiorców, demonstrację interwencji, tytuł projektu, dane zespołu i prezentację PDF do 10 slajdów. Wykazać istotne użycie AI, bibliotek, modeli, danych i zasobów zewnętrznych. Oddzielić obecny kod z brancha `backend` od pracy wykonanej podczas wydarzenia.

Prezentacja pokazuje praktyczną wartość prototypu i jego ograniczenia. Nie przedstawia scenariuszowo ustawionych wyników ani pomiarów na przypadkowych danych jako dowodu skuteczności antyfraudowej.
