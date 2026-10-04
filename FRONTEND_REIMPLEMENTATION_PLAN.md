# Bank24 — plan reimplementacji frontendu

Data: 4 października 2026. Status: **zrealizowany; testy odbioru przechodzą**.

Podstawa: [audyt UI/UX](docs/frontend-audit-2026-10-04/AUDIT.md), załączona plansza dziewięciu mockupów Bank24 i aktualna decyzja użytkownika: **najpierw landing page, następnie logowanie i dashboard; usunąć stronę z kodem uczestnika**.

Ten dokument zastępuje wcześniejsze założenia `FRONTEND_IMPLEMENTATION_PLAN.md` w zakresie nawigacji, wejścia do aplikacji, kompozycji i harmonogramu przebudowy. Historyczny audyt pozostaje zapisem stanu sprzed zmian. Aktualny kontrakt działającego API nadal opisuje `BANK24_API.md`; docelowe zmiany kontraktu zapisano poniżej.

## 1. Ustalony zakres

Wybrany wariant: przebudowa obecnej aplikacji React według mockupów oraz landing jako obowiązkowa strona wejściowa pod `/`.

```text
Landing / → Zaloguj się /login → Kod logowania /verify-login → Dashboard /app
                                                                    ↓
                           Dane przelewu → Sprawdzenie → Kod → Wynik
                                                                    ↓
                                                        Historia / nowy przelew
```

- Usuwamy `StudyPage`, pole „Kod uczestnika” i wymaganie wywołania `/study/join` przed logowaniem. Nie zastępujemy ich niewidocznym wysyłaniem `DEMO-24` z przeglądarki.
- Usuwamy osobny ekran zasad udziału jako bramkę do bankowości. Opcjonalne pomiary mają własne zgody i nie blokują logowania ani przelewów.
- Zachowujemy weryfikację kodem logowania. Użytkownik usunął kod uczestnika, nie drugi etap uwierzytelnienia. W demo kod pozostaje jawnie testowy; SMS nie jest wysyłany.
- Landing ma działać dla użytkownika anonimowego i zalogowanego. Dla zalogowanego główna akcja może zmieniać się na „Przejdź do konta”, ale samo otwarcie `/` nadal pokazuje landing.
- Dashboard dostępny dopiero po poprawnym loginie, haśle i kodzie. Nie ma automatycznego logowania konta demo.
- API, SQLite i integracja kamery pozostają rzeczywiste. Zachowujemy walidację, wersjonowanie i idempotencję przelewu.

## 2. Kierunek wizualny i ekran wejściowy

**Autorytet wizualny:** plansza użytkownika. Stosujemy jej układ i hierarchię: biel, chłodne tło, granat, ograniczony teal, uporządkowane panele oraz stałą nawigację boczną po zalogowaniu. Obecne gradienty, stockowe zdjęcie w kamerze i kapsułki nie są bazą nowej implementacji.

### Landing — `/`

Pierwszy ekran ma od razu pokazać produkt, jego charakter i drogę do logowania.

1. Header: logo Bank24, działające kotwice „Bankowość”, „SafeTransfer”, „Jak działa”, „Pomoc”; po prawej główny przycisk „Zaloguj się”.
2. Hero nawiązujący do pierwszego mockupu: jasny kadr górskiego krajobrazu, po lewej nagłówek i krótki opis, po prawej wizual aplikacji z przykładowym rachunkiem. Teksty i CTA jako HTML, nie część bitmapy.
3. Proponowany nagłówek: „Bankowość z dodatkowym krokiem bezpieczeństwa”. Opis przedstawia sprawdzenie danych i możliwość wstrzymania przelewu, bez gwarancji skuteczności modelu.
4. Główne CTA „Zaloguj się” prowadzi bezpośrednio na `/login`. Drugie „Poznaj SafeTransfer” przewija do sekcji wyjaśniającej działanie.
5. Niżej krótka demonstracja sekwencji: dane → sprawdzenie → potwierdzenie. Każde pokazane twierdzenie odpowiada działającej funkcji.
6. Dyskretne, czytelne oznaczenie „Demonstracja · fikcyjne środki”. W stopce prawdziwe informacje o prototypie i link Pomoc. Bez fikcyjnego otwierania konta, infolinii i logowania przez nieistniejącą aplikację mobilną.

**Materiały:** jedna dobrana fotografia i jeden wizual produktu, hostowane lokalnie z informacją o pochodzeniu i licencji. Nie wycinać całego hero z planszy i nie używać go jako gotowej strony. Krajobraz może zostać wykadrowany na mobile; formularze oraz tekst pozostają natywne. Wybór lub wygenerowanie zasobów jest zadaniem etapu wdrożenia.

**Odporność:** landing i podstawowa pomoc nie zależą od sukcesu bootstrap API. Awaria serwera bankowego nie może zastąpić strony wejściowej ekranem błędu. CTA do logowania nadal działa i pokazuje odpowiedni stan w formularzu.

### Logowanie i kod

- Desktop: dwie części jak w mockupie — obraz z krótkim komunikatem i formularz około 400–440 px. Jedno zadanie, jeden główny nagłówek, jedna główna akcja.
- Pola Login i Hasło, pokaż/ukryj hasło, zapamiętaj urządzenie, pomoc, powrót na landing. Dane demo w rozwinięciu, nie w dużej reklamowej karcie.
- Opcjonalna telemetria w niewielkiej, rozwijanej sekcji „Opcjonalny pomiar zachowania”, domyślnie wyłączona. Nie ma wymaganego checkboxa uczestnictwa do samego logowania.
- Kamera dostępna po zalogowaniu; nie zabiera trzeciej kolumny loginu ani ekranu kodu.
- OTP: kompaktowy panel, jedno pole z obsługą wklejania i autofill, odliczanie, ponowienie i powrót. Segmenty wizualne oraz `maxLength` zgodne z długością zwróconą przez API: cztery znaki demo, sześć poza demo.

### Dashboard i bankowe ekrany

- Sidebar około 200–224 px: Konto, Przelewy, Historia, Pomoc. Dodajemy wyłącznie działające sekcje.
- Topbar około 64 px: kontekst widoku, użytkownik, osobna akcja Wyloguj oraz status aktywnej kamery z akcją Wyłącz. Dzwonek dopiero z prawdziwymi powiadomieniami; na tym etapie usuwamy go.
- Dashboard: jasna karta salda i numeru rachunku z działającym kopiowaniem, główny „Nowy przelew”, ostatnie operacje obok; podsumowanie miesiąca jako rzeczywiste liczby.
- Przelew: formularz główny, kompaktowa faktura jako kontekst zadania, kamera jako moduł pomocniczy. Parametry eksperymentalne domyślnie ukryte.
- Historia: tabela na desktopie, czytelne bloki transakcji na telefonie; działające filtry i wyszukiwanie całej historii.
- Wynik: widoczny stan, kwota, odbiorca, szczegóły i dwie główne akcje. Wersje danych i diagnostyka w rozwinięciu.

### Wspólne zasady

Białe powierzchnie na jednolitym chłodnym tle; granatowe akcje; teal użyty oszczędnie. Radius kontrolek 6–8 px, paneli 10–12 px. Tekst bazowy 15–16 px, nagłówki zadaniowe 24–28 px, saldo 32–40 px. Lokalne IBM Plex Sans można zachować. Rytm odstępów 4/8/12/16/24/32/48 px. Bez sztucznych wykresów, zielonego „bezpieczeństwa” przy braku oceny i animowanego skanowania bez rzeczywistego procesu.

Poniżej 1024 px layout bankowy upraszcza się, a kamera nie rezerwuje bocznej kolumny. Na telefonie formularz zajmuje pełną szerokość; kontekst faktury jest dostępny przy zadaniu, a kamera zwijana. Cele dotykowe co najmniej 44 × 44 px jako standard projektu. Żaden element nie jest ukrywany przez `overflow: clip` w celu zamaskowania błędu układu.

## 3. Routing i zasady sesji

| Trasa | Docelowe zachowanie |
|---|---|
| `/` | Publiczny landing, bez przekierowania na `/study`. Działa również po zalogowaniu. |
| `/login` | Formularz bez wymogu uczestnika i zgód badania; zalogowany użytkownik przechodzi na `/app`. |
| `/verify-login` | Tylko z aktywnym wyzwaniem logowania; brak wyzwania → `/login`, pełna autoryzacja → `/app`. |
| `/app` | Dashboard po pełnym uwierzytelnieniu; brak sesji → `/login`. |
| `/app/transfers/new` | Formularz i edycja istniejącego szkicu. |
| `/app/transfers/:id/review` | Jedno sprawdzenie: podsumowanie, rzeczywisty stan oceny, wymagane decyzje i edycja/anulowanie. |
| `/app/transfers/:id/confirm` | Kod związany z ID i wersją operacji. |
| `/app/transfers/:id/status` | Zrealizowany / anulowany / wstrzymany / odzyskiwanie statusu. |
| `/app/history` | Filtry, zapytanie i paginacja zapisane w URL. |
| `/app/survey` | Opcjonalna opinia; poza główną ścieżką. |
| `/help` | Publiczna pomoc z bezpiecznym parametrem powrotu i wersją bankową dla zalogowanego. |
| `/study`, `/study/consent` | Stare linki przekierowane z `replace` na `/login`; nie renderują dawnych ekranów. |
| `/app/transfers/:id/intervention` | Stary link przekierowany do `/review`, chyba że operacja jest już końcowa — wtedy `/status`. |
| Nieznana trasa | Czytelne 404 i link do landing; zalogowanemu także link do konta. |

Wylogowanie kończy kamerę i telemetrię, usuwa prywatne cache i szkice, następnie prowadzi na `/`. Wygaśnięcie sesji podczas zadania prowadzi na `/login` z komunikatem. Parametr powrotu dopuszcza wyłącznie lokalne trasy bankowe; trasę konkretnego przelewu po zalogowaniu ponownie weryfikuje serwer. Zakończone przelewy zawsze prowadzą do trwałego wyniku.

Publiczne layouty nie dziedziczą loadera wymagającego bootstrap. Stan logowania może być odczytywany pomocniczo, ale jego niedostępność nie blokuje renderowania landing.

## 4. Konieczne zmiany backendu

Usunięcie `StudyPage` nie wystarcza. Obecnie `bank24_server.py` wybiera konto przez `/study/join`, a `login`, `verify` i `login_challenge` wymagają `consent=True`. Należy zmienić te zależności w tym samym etapie co routing.

### Logowanie bez kodu uczestnika

1. `/api/bootstrap` nadal tworzy anonimową sesję i CSRF. Nie wybiera konta oraz nie ustawia zgód automatycznie.
2. `/api/bank/login` wyszukuje właściciela po loginie, sprawdza hasło i limity prób; dopiero poprawne dane wiążą sesję z kontem oczekującym na OTP. Nie wymaga `/study/join` ani zgody na pomiary.
3. Nieistniejący login i błędne hasło zwracają ten sam komunikat; nie istnieje awaryjne logowanie na konto demo. Pośrednia sesja nie daje dostępu do rachunku, historii ani przelewów.
4. `/api/bank/verify` zatwierdza właściwe wyzwanie i rotuje cookie/CSRF tak jak obecnie. Dostęp bankowy wymaga `authenticated=True`.
5. Ponowny wybór konta przed zakończeniem OTP unieważnia wyzwania poprzedniego konta. Zmiana zalogowanego właściciela wymaga zakończenia sesji; jego kamera, telemetria i prywatny stan nie mogą przejść na kolejne konto.
6. `/api/bank/login-challenge` działa dla aktywnego wyzwania sesji bez zależności od `consent`. Zachowuje cooldown, czas ważności i limit prób.
7. Challenge otrzymuje pole `code_length`; źródłem długości kodu jest API, nie liczba wpisana w CSS.

Tabela `participants` i wewnętrzny klucz właściciela mogą pozostać dla zgodności istniejących danych. Termin „uczestnik” nie występuje w głównym UI. Przebudowa nie wymaga kasowania bazy ani zamiany jej na nową. Istniejące dane przenosi migracja zachowująca saldo i historię.

### Pomiary jako niezależne ustawienia

- Rozdzielić prawo do logowania od uprawnień do telemetrii, kamery i ankiety. Ogólne `consent` przestaje być warunkiem uwierzytelnienia.
- Docelowo dodać `POST /api/session/permissions` z niezależnym wyborem `telemetry` i `camera`; wartość początkowa obu to `false`. Zgoda może dotyczyć anonimowej sesji logowania, żeby pomiar loginu nadal był możliwy.
- Brak zgody na telemetrię oznacza brak listenerów i wysyłki metadanych; API także odrzuca takie dane. Rezygnacja usuwa kolejkę oczekujących zdarzeń.
- Kamerę można uruchomić po pełnym logowaniu, osobnym opt-in i zgodzie przeglądarki. Gateway sprawdza uprawnienie, autoryzację i własność sesji; wyłączenie zamyka zasoby.
- Informacja o danych i możliwość rezygnacji dostępne w pomocy oraz przy module pomiaru. Nie ma dodatkowej pełnoekranowej bramki przed dashboardem.
- Przenieść działające wycofanie danych pomiarowych do jasnej akcji w pomocy z potwierdzeniem skutku. Zachować spójność fikcyjnej historii finansowej i salda.
- Usunąć `/study/join` z nowego kontraktu logowania; stary endpoint można wyłączyć lub oznaczyć jako wycofany. Nie utrzymywać ukrytej zależności w testach.

### Historia

Rozszerzyć `/api/bank/transactions` o `q` oraz `direction=all|incoming|outgoing`. Wyszukiwanie i filtry działają na zbiorze operacji bieżącego właściciela **przed** paginacją; `total` opisuje wynik filtrowania. Ustalić stabilny porządek przy tych samych datach. Zmiana filtra lub zapytania zeruje offset. Zachować polskie znaki i aktualne formatowanie kwot oraz dat.

## 5. Architektura UI i porządkowanie kodu

Pozostajemy przy React, TypeScript, Vite, React Router i TanStack Query. Nie wprowadzamy nowego frameworka ani drugiej oddzielnej aplikacji demonstracyjnej.

| Moduł | Odpowiedzialność |
|---|---|
| PublicLayout | Landing, publiczna pomoc, logo, nawigacja, stopka; renderowanie niezależne od API. |
| AuthLayout | Formularz logowania i OTP, spokojna geometria, brak bankowego sidebara. |
| BankLayout | Sidebar, topbar, główna treść, status kamery i właściwy focus po nawigacji. |
| TransferLayout | Stabilne miejsce kroków, formularza/podsumowania i kontekstu; warianty mobile. |
| CameraProvider / store | Jeden właściciel strumienia ponad trasami; widoczna kontrola, brak ponownego startu przez zmianę ekranu. |
| Komponenty design systemu | Button, Field, PasswordField, CodeInput, StatusNotice, Stepper, TransactionTable, TransferSummary, CameraStatus. |
| Warstwa API | Kontrakty sesji i zgód, długość kodu, historia z filtrami; izolacja błędów publicznych i prywatnych. |

Obecny `RootLayout.tsx` rozdzielić, zamiast rozwijać kolejne warunki `location.pathname`. W `styles.css` zastąpić bazę i nadpisania jednym układem tokenów oraz stylami komponentów/layoutów. Usunąć zastąpione reguły; nie doklejać następnej warstwy na końcu pliku. Layout nie zależy od numerów wierszy `grid-row` i wykrywania potomków przez `:has`.

## 6. Przelew: jedna czytelna ścieżka

1. **Dane:** ręczne wpisanie odbiorcy, rachunku, tytułu i kwoty; faktura widoczna jako kontekst. Walidacja przy polach, preserve draft, ostrzeżenie przed utratą zmian.
2. **Sprawdzenie:** podsumowanie i wymagane pytanie na jednym ekranie. Brak oceny modelu jest komunikatem neutralnym, nie udawaną analizą. Użytkownik może edytować, anulować albo przejść do kodu po spełnieniu reguł serwera.
3. **Kod:** akcja „Przejdź do kodu” zapisuje wymaganą decyzję i zamawia challenge. Każde wywołanie pozostaje zgodne z API i związane z ID oraz wersją przelewu.
4. **Wynik:** czytelny, trwały stan konkretnej operacji, bez ponownego obciążenia przy Back, odświeżeniu i ponowieniu.

Jeśli decyzja daje `held`, przejście kończy się wynikiem wstrzymania. Przy utracie odpowiedzi po zamówieniu kodu odczytać istniejące wyzwanie i respektować cooldown. Przy błędzie zamówienia po zapisie decyzji zachować stan `ready`, pokazać możliwość ponowienia; nie powtarzać interwencji jako nowej operacji. Przy niepewnym wyniku submit najpierw odzyskać tę samą transakcję.

Nie zmieniać serwerowego warunku `compared=true` przy zgłoszeniu presji w ramach samego redesignu. UI wyraźnie tłumaczy obecną regułę i pozwala anulować bez jej spełnienia. Ewentualne uproszczenie ścieżki wstrzymania to osobna zmiana reguł, nie ukryty efekt łączenia ekranów.

## 7. Etapy wykonania

| Etap | Konkretne zadania | Warunek zakończenia |
|---|---|---|
| **R0 — nowy dostęp** | Login wybiera konto; rozdzielenie zgód; publiczny routing; usunięcie bramki uczestnika; aktualizacja sesji i testowych helperów | Nowa sesja otwiera `/`, przechodzi prosto na login, po OTP na konto. Żaden krok nie wymaga kodu uczestnika; prywatne API nadal chronione. |
| **R1 — fundament wizualny** | Tokeny, komponenty, Public/Auth/Bank/TransferLayout, responsive, focus i samodzielny logout | Stabilna geometria desktop/mobile; profil i akcje nie wylogowują przypadkiem. Naprawione F01–F03, F13–F14 audytu. |
| **R2 — landing i logowanie** | Hero według planszy, lokalne materiały, prawdziwe CTA, login, OTP, pomoc logowania, dyskretne oznaczenie demo | Pierwsze wrażenie zgodne z mockupem; landing działa przy niedostępnym API; brak obietnic bez pokrycia. |
| **R3 — dashboard i historia** | Jasny rachunek, rzeczywiste podsumowanie, copy, transakcje, filtry i wyszukiwanie po stronie serwera | Kwoty czytelne na 390 px; wszystkie kontrolki działają; brak 68% i bezwarunkowego wniosku. |
| **R4 — pełny przelew** | Połączenie review/intervention, uproszczone zamawianie OTP, spójne wyniki, zachowanie szkicu i obsługa awarii | Standardowa operacja, edycja, anulowanie, wstrzymanie i odzyskiwanie statusu działają w jednym modelu etapów. |
| **R5 — kamera i pomoc** | Uprawnienia, neutralny placeholder, stały status i Wyłącz, szczegóły na żądanie, pomoc, opcjonalna opinia | Kamera nie znika spod kontroli; odmowa zgody i awaria workera nie blokują bankowości. |
| **R6 — odbiór i dokumentacja** | Regresja, desktop/mobile, axe, klawiatura i zoom; aktualizacja README, API, PRODUCT i DESIGN | Przechodzą istotne testy, brak regresji audytu; instrukcje opisują nowy flow i rzeczywiście zaimplementowany system. |

R0–R2 należy dostarczyć jako pierwszą pionową część: działające landing → login → OTP → obecny dashboard. Następnie R3–R5 zastępują widoki bankowe. Nowe layouty i zmienione sesje wdrażać spójnie, bez okresowego powrotu użytkownika na usuniętą stronę uczestnika.

R5 jest etapem dopracowania; podstawowa kontrola aktywnej kamery i egzekwowanie opt-in muszą działać już wraz z R0/R1.

## 8. Testy i kryteria odbioru

### Dostęp i sesja

- Świeża przeglądarka: `/` → „Zaloguj się” → dane → kod → `/app`; bez `/study/join` i bez pola uczestnika.
- Nieprawidłowy login, hasło lub OTP nie dają dostępu; błąd jest czytelny. Zachowane limity prób, cooldown i rotacja tokenów.
- Wejście bezpośrednio na `/login` działa; nie ma obowiązku wcześniejszego odwiedzenia landing ani uczestnictwa.
- Wejście na `/app` bez pełnej autoryzacji wraca do loginu. Próba odczytu API prywatnego także odrzucona.
- `/` zawsze pokazuje landing; stare `/study` i `/study/consent` nie pokazują starych formularzy.
- Konto jest wybierane po poprawnych danych. Dane dwóch kont i pośrednie wyzwania nie mieszają się.
- Logout → landing, wygaśnięcie → login; bezpieczny powrót do zadania po ponownym logowaniu.
- Landing oraz publiczna pomoc działają przy niedostępnym API. Formularz pokazuje błąd i możliwość ponowienia.

### Dane i przelewy

- Kwoty/NRB, edycja wersji, unieważnienie starego kodu, double click, Back/reload, utrata odpowiedzi, anulowanie i nieodwracalność `held` zachowują obecne gwarancje.
- Zamówienie OTP po interwencji ma sprawdzoną ścieżkę częściowego sukcesu i retry.
- Podsumowanie miesiąca poprawne dla zera i wydatków większych od wpływów. Brak wpisanych na stałe wniosków.
- Wyszukiwanie znajduje operację spoza pierwszej strony; filtry działają klawiaturą i zachowują stan w URL.

### Kamera, dostępność i wygląd

- Brak opt-in = brak transmisji i telemetrii. Wyłączenie, logout i wycofanie zamykają zasoby oraz kasują kolejkę pomiarów.
- Testy kamery korzystają z kontrolowanego strumienia, nie z fizycznego urządzenia użytkownika.
- Sprawdzenie 390, 768, 1024 i 1440 px; 320 px jako dolna granica oraz powiększenie 200%. Kontrola granic dzieci i uciętej treści, nie tylko szerokości dokumentu.
- Główna ścieżka dostępna klawiaturą, jeden nagłówek zadania, właściwy focus, etykiety i komunikaty zmian. Cele ikonowe 44 × 44 px.
- Stany loading/empty/error/disabled/success; długie nazwiska, tytuły, numery i kwoty; brak sztucznej zielonej oceny.
- Jedna zbiorcza runda wizualna desktop/mobile, jedna paczka poprawek i jedna runda potwierdzająca. Istniejące testy uzupełniać o rzeczywiste zachowanie, nie o odwzorowanie CSS.

Komendy odbioru po implementacji: `npm run build`, `npm test`, `npm run test:e2e` w `frontend/`; testy API i WebRTC z `tests/`. Zaktualizować setup istniejących testów, które obecnie wywołują `/study/join`; samo pozostawienie starego helpera nie dowodzi działania nowego logowania.

## 9. Pliki i dokumentacja do zmiany

- `frontend/src/app/router.tsx`, `layouts/RootLayout.tsx` → nowy routing i rozdzielone layouty.
- `frontend/src/features/landing/` → nowy landing; `features/auth/pages.tsx` → login/OTP bez gate uczestnika.
- `frontend/src/features/study/pages.tsx` → usunąć StudyPage i ConsentPage; opcjonalną opinię przenieść poza onboarding.
- `frontend/src/services/api.ts`, `features/telemetry/collector.ts`, `features/camera/` → sesja, niezależne uprawnienia i kontrola zasobów.
- `features/accounts/pages.tsx`, `features/transfers/pages.tsx`, `features/help/HelpPage.tsx` → reimplementacja widoków i zachowania.
- `frontend/src/design/`, `frontend/public/brand/` i nowe lokalne obrazy → spójny system i zasoby.
- `bank24_server.py`, `tests/test_bank24.py`, `frontend/e2e/bank24.spec.ts` → nowe logowanie, permissions, historia, regresja.
- `README.md`, `frontend/README.md`, `BANK24_API.md`, `PRODUCT.md`, `DESIGN.md` → aktualizacja po wdrożeniu, z adresem wejściowym `/` i bez instrukcji wpisywania kodu uczestnika.
- Zrzuty audytu pozostają historyczne. Nowe zrzuty odbioru umieścić w osobnym katalogu, aby móc porównać efekt.

## 10. Definicja ukończenia

Przebudowa jest ukończona, gdy użytkownik trafia na landing, loguje się bez kodu uczestnika, przechodzi OTP do profesjonalnego dashboardu i wykonuje pełną operację w spójnym interfejsie inspirowanym planszą. Główne problemy audytu są usunięte i potwierdzone w przeglądarce, a dokumentacja odpowiada rzeczywistemu kodowi.

Poza zakresem: realna bankowość, rejestracja kont, BLIK, karty, nieistniejący czat/infolinia, walidacja modeli ryzyka i wdrożenie dostawcy SMS. Publiczny landing nie oznacza publikacji na hostingu; ten plan dotyczy aplikacji w repozytorium.

## 11. Wykonanie i odbiór

Etapy R0–R6 są zrealizowane. Użytkownik rozpoczyna pod `/`, może przejść do logowania, potwierdzić kod i wejść do chronionego `/app`. Formularz kodu uczestnika oraz wymóg wcześniejszego udziału usunięto z bieżącego przepływu; stare adresy kierują do logowania. Landing i Pomoc są publiczne i działają bez API. Historia, przelewy, szkic, idempotencja, odzyskiwanie wyniku, niezależne zgody telemetrii/kamery oraz zatrzymanie kamery działają w nowym układzie.

Odbiór UI sprawdzono w Playwright dla szerokości 320, 375, 720, 768, 900, 1024, 1440 i 1920 px na landing page, koncie, historii, formularzu przelewu i Pomocy. Szerokość 720 px sprawdza układ odpowiadający 200% powiększeniu z viewportu 1440 px. Axe nie wykrył naruszeń WCAG 2.1/2.2 A/AA w badanych trasach przy 375 i 1440 px. Sprawdzono klawiaturę, cele dotykowe, brak przewijania poziomego oraz kamerę z kontrolowanym strumieniem.

Wynik komend odbioru:

- `npm run build` — zaliczone.
- `npm test` — 3 testy zaliczone.
- `npm run test:e2e` — 10 testów zaliczonych; pełny przebieg po końcowych zmianach.
- `.venv-bank\Scripts\python.exe -m unittest tests.test_bank24` — 13 testów zaliczonych.
- `.venv-bank\Scripts\python.exe -m unittest tests.test_webrtc_server` — 6 testów zaliczonych.

Nowe zrzuty desktop/mobile są w `.impeccable/review/`. Lokalny obraz hero powstał na potrzeby tego interfejsu; jego opis i zasady użycia zapisano w `DESIGN.md`. OTP w środowisku demonstracyjnym nadal nie wysyła SMS — pokazuje kod testowy zgodnie z zakresem i dokumentacją.
