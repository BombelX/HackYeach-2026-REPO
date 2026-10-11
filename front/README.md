# Bank24 — aplikacja React

Docelowy frontend na branchu `backend`, rozwinięty z zatwierdzonych mockupów.
React + TypeScript + Vite, data router React Router i TanStack Query. Serwer
`bank24_server.py` zapisuje fikcyjny rachunek i operacje w SQLite. Aplikacja
nie przełącza się na mock API po awarii serwera.

## Uruchomienie na Windows

Z katalogu repozytorium, jednorazowo:

```powershell
python -m venv .venv-bank
./.venv-bank/Scripts/python.exe -m pip install -r backend/requirements-bank.txt
cd front
npm ci
```

W pierwszym terminalu, w katalogu repozytorium:

```powershell
./.venv-bank/Scripts/python.exe backend/bank24_server.py --demo
```

API operatora jest domyślnie wyłączone. Aby je włączyć, ustaw losowy token
co najmniej 32 znaków w `BANK24_ADMIN_TOKEN` przed startem serwera; token
przekazuj wyłącznie w nagłówku `Authorization: Bearer ...`. Nie commituj go.
Kontrakt i kolejność wywołań są w [BANK24_API.md](../backend/BANK24_API.md). Aplikacja
React nie ma jeszcze ekranów operatora ani onboardingu badania.

W drugim terminalu:

```powershell
cd front
npm run dev
```

Otwórz **http://localhost:5173/**. Strona główna prowadzi do logowania.
Login: `anna.demo`, hasło: `bank24`, testowe kody logowania i przelewu:
`1234`.
`--demo` włącza te dane i jawny testowy OTP; SMS nie jest wysyłany.
SQLite: `backend/data/bank24.sqlite`. Zmiany salda przeżywają odświeżenie i restart.
Mockupy na 5174 są osobną referencją, nie uruchomioną aplikacją React.

Bank uruchamia kamerę od logowania, po zgodzie użytkownika i przeglądarki. Brak obrazu nie blokuje podstawowych operacji bankowych. Do rzeczywistej analizy postawy/mimiki:

```powershell
./.venv-bank/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
./.venv-bank/Scripts/python.exe -m pip install -r backend/requirements-server.txt
./.venv-bank/Scripts/python.exe backend/webrtc_server.py --host 127.0.0.1 --preview-only --device cpu
```

`--preview-only` wyłącza PhysNet, nie MediaPipe. Domyślne modele są w
`models/`, a toolbox w `third-party/rPPG-Toolbox`. Dodaj `--no-analysis`, aby
sprawdzić sam transport. Jeśli źródła i wagi PhysNet są w osobnym katalogu,
zamiast `--preview-only` podaj `--toolbox /ścieżka/do/rPPG-Toolbox` oraz
`--device cuda` (o ile GPU jest dostępne). Frontend pokazuje `null`, dopóki
nie ma rzeczywistego pomiaru pulsu. Nie uruchamia kamery bez osobnej zgody,
nie pobiera mikrofonu i nie zapisuje nagrań. Wysyła klatki JPEG (do 640 ×
480 px) przez autoryzowane API HTTPS, najwyżej cztery równolegle; zwrócony
obraz z punktami i pomiary pochodzą z serwera. Nie wymaga STUN/TURN ani
publicznego portu UDP. Worker zachowuje osobne endpointy WebRTC dla klientów
używających tego transportu. Estymacja pulsu wymaga co najmniej pięciu sekund
sygnału o dostatecznej częstości próbkowania; wolne połączenie może nie
wygenerować wyniku.

## Przepływ i stan

Landing → login i hasło → kod logowania → konto → ręczny przelew →
podsumowanie i sprawdzenie → kod transakcji → wynik. Historia, pomoc, ankieta
i usuwanie opcjonalnych danych są działającymi ekranami. Ekran kodu uczestnika
nie jest jeszcze częścią UI; badanie można obecnie obsłużyć przez opisane API.

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
cd front
npm run build
npm test
npm run test:e2e
npm audit
```

E2E korzysta z Chrome, własnego API na 8082, Vite na 5180 i oddzielnego
`data/e2e-bank24.sqlite`. Nie zmienia salda działającej demonstracji na 8081.
Kamera testowa jest kontrolowanym strumieniem canvas przekazanym przez
autoryzowane API HTTPS do istniejącego serwera. Nie uruchamia fizycznej kamery użytkownika.
Playwright w razie potrzeby uruchamia worker na 8080 z wyłączoną analizą.
Brakujące źródła/wagi PhysNet powodują jawny skip jednego testu inferencji;
testy przesyłania klatek nadal działają. Axe wspiera kontrolę dostępności; pełny test
czytnikiem ekranu i badanie z uczestnikami pozostają osobnymi bramkami.

## Build bez Vite

```powershell
cd front
npm run build
cd ..
./.venv-bank/Scripts/python.exe bank24_server.py --demo --origin http://localhost:8081
```

Otwórz http://localhost:8081. Serwer obsługuje zbudowane pliki i bezpośrednie
linki do tras. Przy HTTPS użyj `--secure-cookie` i poprawnego `--origin`;
usługę kamery utrzymuj za gatewayem, na loopback. Poza localhost przeglądarka
wymaga HTTPS; STUN/TURN jest potrzebny tylko osobnym klientom WebRTC.

Jeśli aplikacja jest publikowana pod ścieżką portalu `/variolog/`, zbuduj ją
poleceniem `npm run build -- --base /variolog/`. Autoryzowana bramka powinna
przekazywać `/variolog/*` do Bank24 po usunięciu prefiksu, pozostawiając
pozostałe ścieżki portalu bez zmian. Uruchom Bank24 z `--origin` ustawionym na
publiczny origin HTTPS (bez `/variolog/`) oraz `--secure-cookie`. Frontend
wysyła wtedy żądania do `/variolog/api/*` z tego samego originu; adres workera
kamery powinien pozostać lokalny. Po ponownej kompilacji bez `--base /variolog/`
należy wykonać build dla tej ścieżki jeszcze raz przed udostępnieniem strony.

## Zakres dalszych etapów planu

Backend udostępnia API badania opisane w [BANK24_API.md](../BANK24_API.md):
operator tworzy uczestników i przydziela scenariusze, uczestnik wiąże kod,
wybiera osobne zgody i prowadzi sesję, a serwer wyciąga cechy z metadanych,
buduje profile z co najmniej trzech spokojnych sesji właściciela na etap i
zapisuje dwa wyjaśniane wskaźniki porównawcze. Telemetria nigdy nie zawiera
treści wpisanych pól. Cofnięcie zgody usuwa powiązane dane i przelicza profile.

W zwykłym koncie bankowym panel „Profil kamery” pozwala jawnie rozpocząć pomiar
i zapisać próbkę po co najmniej 40 sekundach spokojnego nagrania z aktywnej kamery. Trzy osobne logowania potwierdzone kodem
tworzą pierwszą wersję profilu w trybie demo. Po utworzeniu profilu nowe próbki
czekają na niezależne zatwierdzenie operatora; dopiero ono tworzy nową wersję.
Poza trybem demo również pierwsze trzy próbki wymagają zatwierdzenia. Panel pokazuje
postęp i umożliwia usunięcie profilu. Sama ocena ryzyka
nie zapisuje próbek. Szczegóły endpointów są w [BANK24_API.md](../BANK24_API.md).

Wskaźniki `robust-baseline-v1` są heurystyczne, niezwalidowane i nie są
prawdopodobieństwem oszustwa. Bez powiązanej sesji badania, profilu lub
wystarczającej telemetrii API zwraca `null`. Ekran przelewu pokazuje skalę
0–100 wyłącznie z wyraźnym oznaczeniem eksperymentalnego charakteru. Te
endpointy są już po stronie backendu; aplikacja nie ma jeszcze ekranów
onboardingu badania ani panelu operatora.

Nadal brakuje skonfigurowanego dostawcy SMS, walidacji progów na danych
uczestników, eksportu Parquet, polityki retencji i odbioru dostępności z
czytnikiem ekranu. To demonstracja reguł, a nie zwalidowany detektor przejęcia
konta lub presji.
