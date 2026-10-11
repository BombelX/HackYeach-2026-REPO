# Ekstrakcja danych sesji

Pipeline przetwarza zapisane nagrania czterech warunków `calm`, `dictation`,
`scam`, `intruder`. Nie trenuje nowego modelu. Wyniki to Parquet i JSON,
bez klatek obrazu ani kopii filmów. Źródła pozostają dostępne do sprawdzenia.
Plan i ustalenia z repo: [PREPROCESSING_PLAN.md](PREPROCESSING_PLAN.md).

## Uruchomienie

Z dowolnego katalogu:

```bash
/venv/main/bin/python /workspace/hackaton/HackYeach-2026-REPO/scripts/preprocess_sessions.py --inventory-only
/venv/main/bin/python /workspace/hackaton/HackYeach-2026-REPO/scripts/preprocess_sessions.py
```

Pełny przebieg na tej instancji z dużym zapasem CPU i pamięci:

```bash
/venv/main/bin/python scripts/preprocess_sessions.py --include-incomplete --workers-per-gpu 8
```

Taki przebieg uruchamia 32 workery na czterech kartach. Pomiar produkcyjny
pokazał około 43 wykorzystywane rdzenie CPU, 62 GiB RSS i 15–17 GiB VRAM
na kartę, bez OOM. Dobieraj tę liczbę do sprzętu; domyślna wartość 2
workery na GPU ma mniejsze wymagania pamięciowe.

Domyślnie pipeline korzysta z GPU 0, 1, 2, 3, po dwóch workerach CPU/GPU
na kartę, i zapisuje `data/processed`. Cztery karty nie są przypisane do
warunków: współdzielona kolejka daje każdemu wolnemu workerowi następną sesję.
`--workers-per-gpu 1` ogranicza współbieżność; `--gpu-ids 0 1` ogranicza karty.
`--cpu` uruchamia pojedynczy worker bez CUDA.

Domyślnie przetwarzane są zakończone sesje. `--include-incomplete` umożliwia
ekstrakcję bieżącego, stabilnego stanu niezamkniętych sesji; ich źródłowy
status pozostaje w wynikach. Kalibracje, usunięci uczestnicy i niepoprawne
zestawy fragmentów mają jawny powód pominięcia w inventory/run_report.
Sesja bez filmu otrzymuje pozostałe modality i puste tabele wideo.

Krótka próba powinna używać osobnego outputu:

```bash
/venv/main/bin/python scripts/preprocess_sessions.py \
  --session SESSION_ID --max-seconds 30 --output /tmp/preprocessing-check
```

`--max-seconds` ogranicza wyłącznie ekstrakcję wideo; logi i embeddingi obejmują
całą sesję. Summary ma `truncated_run` i `video.truncated`. Pełny przebieg
pomija argument `--max-seconds`.

Ponowne uruchomienie pomija kompletne wyniki z tym samym fingerpritem
źródeł, kodu, konfiguracji i wag. `--force` przelicza wynik. Niekompletny output,
zmiana źródeł albo zmiana modelu wymagają ponownego przetworzenia.
Wynik sesji publikowany jest dopiero po ukończeniu wszystkich tabel.
Błąd jednej sesji nie zatrzymuje pozostałych; niezerowy exit code sygnalizuje
błędy. Jeden katalog wynikowy ma blokadę chroniącą przed dwoma writerami.

## Format wyników

Każda sesja ma katalog `data/processed/sessions/<grupa>/<session_id>/`:

| Plik | Zawartość |
|---|---|
| `frames.parquet` | PTS, 478 punktów twarzy, blendshapes, 33 punkty postawy i world landmarks, geometryczne cechy postawy, maski detekcji; docelowo 5 Hz |
| `pulse.parquet` | Sygnał różnicowy i całkowany PhysNet, BPM, opis jakości, segmenty, interpolacja źródłowa; 30 Hz |
| `pulse_windows.parquet` | Granice okien neural modelu, coverage i padding, oddzielny status ekstrakcji/synchronizacji |
| `timeline.parquet` | Wspólna siatka 5 Hz: skalarne cechy twarzy/postawy/pulsu, maski oraz liczby zdarzeń klawiatury/myszy |
| `keyboard.parquet` | Naciśnięcia, czasy press/release, 8 cech treningowych, identyfikatory liczbowe i maski |
| `keyboard_events.parquet` | Wszystkie keydown/keyup, także repeat, bez zapisanych znaków tekstu |
| `keyboard_windows.parquet` | Okna maks. 96 naciśnięć, maska wejścia i embeddingi 128D |
| `mouse.parquet` | Pointer samples, kliknięcia, wheel i scroll; czas każdego coalesced sample, współrzędne i atrybuty urządzenia |
| `network.parquet` | Clock sync, ping, server requests, środowisko i pozostałe zebrane dane sieciowe w `payload_json` |
| `markers.parquet` | Etapy i pozostałe zdarzenia; treść wpisywanych pól pominięta |
| `browser_face.parquet` | Oryginalne numeryczne pomiary twarzy/postawy z przeglądarki, z ujednoliconym czasem |
| `context.json` | Metadane, DB, ankieta, definicje cech, field maps, profil klawiatury, synchronizacja |
| `summary.json` | Manifest artefaktów, konfiguracja, fingerprint, liczby wierszy i statystyki |

Dodatkowe lokalne pliki kontekstu, w tym HAR w podkatalogach, są zachowane
w `extra_context`. W obecnym zbiorze nie ma plików HAR: są logi żądań i pingi
oraz metadane środowiska. Pipeline nie wymyśla brakujących HAR.

`inventory.json`, `run_report.json` i `run_summary.json` w głównym katalogu
zawierają wynik przeglądu i przebiegu. `sessions.parquet` spina profile,
etykiety, maski modality i odnośniki do tabel sesji do przyszłego treningu.
Uczestnik jest zachowany jako identyfikator do podziału danych po osobach.
Etykieta scenariusza i ankieta pozostają etykietami/kontekstem, nie wejściem
embeddingu klawiatury.

## Czas i brakujące dane

`t_session_ms` to milisekundy od serwerowego rozpoczęcia sesji.
`t_server_epoch_ms` to Unix milliseconds po synchronizacji; zachowany jest
również oryginalny zegar klienta i PTS filmu. Zegar monotoniczny klienta
mapowany jest przez próbki clock_sync o niskim RTT; stałe przesunięcie
nie zmienia rytmu klawiatury pod wpływem jitteru sieci.

Starszy recorder nie zapisywał momentu rozpoczęcia MediaRecorder.
`face.video_ts` było `performance.now()`, a upload chunku wskazuje czas
odbioru na serwerze. Nie wyznaczają one dokładnego PTS pierwszej klatki.
Dlatego stare sesje otrzymują `approx_session_start` i oszacowany przedział
niepewności; synchronizacja jest przybliżona. Dodany `camera.recording_clock`
dla nowych sesji daje `recording_start_requested`; nieznana latencja do
pierwszej zakodowanej klatki nadal pozostaje jawna. Nie przypisujemy
fragmentom arbitralnych 5 sekund — składamy kontener bajtowo i czytamy PTS.

Siatka interpoluje tylko liczbowe sygnały pomiędzy poprawnymi obserwacjami,
domyślnie przez przerwy maks. 500 ms. Jawnie brakujące detekcje i większe
luki pozostają null. `--max-extrapolation-ms` włącza ograniczoną
ekstrapolację krańcową, oznaczoną osobną maską; domyślnie to 0.
Każdy skalar ma maski `valid`, `observed`, `interpolated`, `extrapolated`.
Klawiatura i mysz zachowują zdarzenia; żadne naciśnięcie ani ruch nie jest
wygenerowany przez interpolację. Pełne punkty pozostają w `frames.parquet`
z własnymi timestampami, a siatka zawiera ich skalarne cechy.

## Modele i wydajność

PhysNet wykorzystuje istniejące wagi
`UBFC-rPPG_PhysNet_DiffNormalized.pth`, RGB crop 72×72, 30 Hz,
okna 128 klatek ze stride 96, batch 8. Model działa na GPU,
Face/Pose MediaPipe i dekodowanie na CPU. RGB dekodowane jest raz,
a pamięć bufora obrazu ograniczona rozmiarem batchu i okna.

BPM jest spektralną estymatą po minimum 5 sekundach poprawnego sygnału,
w paśmie 45–150 BPM. Spectral concentration opisuje rozkład energii,
nie stanowi skalibrowanego confidence. Wyjście jest offline i korzysta
z pełnego okna: nie należy traktować go jako inferencji przyczynowej online.
Amplituda pulsu jest względna; segmentów rozdzielonych brakiem detekcji
nie wolno sklejać do HRV ani traktować jako timestampów rzeczywistych
uderzeń serca. Dokładność wymaga osobnego testu z pomiarem referencyjnym.

Model klawiatury `/workspace/keystroke_long_epoch_59.pt` zwraca **128D**.
**96 jest długością sekwencji, nie wymiarem profilu**. Nie zmieniono wymiaru
wyuczonych wag. Szczegółowy preprocessing i maski są w
[KEYBOARD_MOUSE.md](../preprocessing/KEYBOARD_MOUSE.md). Model myszy
nie jest uruchamiany ani trenowany.

Benchmark czterech workerów na czterech RTX 5090: 120 sekund rzeczywistego
filmu w 20,83 s wraz ze spawn, czyli 5,76× realtime; model zużywał około
0,916 GB pamięci na kartę. CPU (MediaPipe i dekodowanie) jest głównym
ograniczeniem, więc dodatkowe workery na GPU zwiększają współbieżność
tych etapów. Wypełnianie całego VRAM lub 100% GPU nie jest celem tego
małego modelu. Parametry można dobrać na podstawie `video_summary.json`.

Długie pojedyncze nagranie można przetworzyć przez
`scripts/parallel_long_video.py`. Pomocnik remuxuje VP8/VP9 do indeksowanego
MKV bez re-encodingu i sprawdza zgodność PTS oraz keyframe flags ze źródłem.
Rozdziela czas na części 307,2 s, z 16 s rozgrzewki i 12,8 s lookahead,
a następnie zapisuje rozłączne części na jednej globalnej siatce.
Punkty wyjściowe mają rzeczywiste PTS; kotwica techniczna rozgrzewki
nie trafia do wyników. Kontrola pokrycia odrzuca brakujące lub podwójne
próbki i niepełne okna wewnętrznych granic.

```bash
/venv/main/bin/python scripts/parallel_long_video.py \
  --video /path/to/joined.webm --output /tmp/long-video-cache --workers 16
```

Po sprawdzeniu cache można użyć `scripts/finish_cached_session.py` do
normalnego, atomowego zapisu tabel i synchronizacji. Argument
`--template-summary` wskazuje `summary.json` sesji przetworzonej z tymi
samymi ustawieniami i wagami. Pomocnik weryfikuje zgodność źródłowego
filmu, zapisanych hashów modeli, kodu, konfiguracji i wszystkich plików
cache z raportem pokrycia. Następnie zwykły przebieg pipeline'u
odtwarza raport oraz wspólny indeks bez przeliczania gotowych tabel.

```bash
/venv/main/bin/python scripts/finish_cached_session.py \
  --session SESSION_ID --cache /tmp/long-video-cache \
  --template-summary data/processed/sessions/calm/OTHER_SESSION/summary.json
```

Tracker twarzy/postawy i historia modelu są niezależne między częściami.
Rozgrzewka zachowuje kontekst do estymacji BPM, lecz współrzędne mogą się
różnić od pojedynczego przebiegu. `model_history_segment_id` i globalnie
unikalne `pulse_segment_id` zapisują te granice. Pierwsze `pulse_value`
nowej części jest null: blokuje interpolację między niezależnymi
bazami całki. `pulse_valid` nadal może być true dla poprawnego sygnału
różnicowego i BPM; osobna maska `pulse_value_valid` pozostaje false.
Pełny opis metody oraz hash pomocnika są w `parallel_provenance` i summary.

Test na całym nagraniu 5 066,628 s: 16 procesów na czterech GPU,
210,29 s ekstrakcji wraz z remuxem i scalaniem, czyli 24,09× realtime.
Kontrola potwierdziła 84 217 unikalnych klatek, 25 334 pomiary 5 Hz
i 151 999 próbek 30 Hz bez luk w indeksach. Końcowa konwersja,
synchronizacja i zapis Parquet zajęły dodatkowe 106,46 s.

## Sprawdzenie

```bash
cd /workspace/hackaton/HackYeach-2026-REPO
/venv/main/bin/python -m unittest discover -s tests -v
/venv/main/bin/python scripts/validate_processed.py
```

Testy obejmują zegary, PTS/anchor, brak detekcji, bounded resampling,
fragmenty WebM/MP4, maski, Aalto features, missing keyup, auto-repeat,
coalesced mouse samples, przetrwanie opcjonalnych kolumn i atomowość
wyników. Build TypeScript/Vite sprawdzono po zmianie znacznika recordera.
Integrację sprawdzono na prawdziwym nagraniu każdego z czterech warunków.
Wynik pełnego przebiegu, liczby rekordów i ograniczenia opisuje
[PREPROCESSING_VALIDATION.md](PREPROCESSING_VALIDATION.md).

Tabele różnych sesji mogą mieć null typy, jeśli modality było całkowicie
nieobecne. Do zbiorczego odczytu należy zjednoczyć/castować schematy lub
odczytywać poszczególne sesje przez odnośniki w `sessions.parquet`.

Na tej instancji `/workspace` nie jest host volume. Wyniki są lokalne i
trzeba je skopiować off-box przed recycle/destroy.
