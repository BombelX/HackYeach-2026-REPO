# Niekompletne źródła wideo

Weryfikacja lokalnych danych: 3 października 2026. Sprawdzenie było wyłącznie odczytem; źródłowe nagrania, metadane i pakiet `preprocessing` nie zostały zmienione. Pipeline oznacza poniższe sześć sesji jako `invalid_video_chunks` i pomija je w przetwarzaniu wideo.

| Session ID | Warunek | Dostępne indeksy fragmentów | Brakujące indeksy przed ostatnim dostępnym | Nagłówek pierwszego kontenera |
| --- | --- | --- | --- | --- |
| `0e47571f-aaa2-4120-99f2-802f400a0748` | `calm_1` | 3–15 | 0–2 | Brak fragmentu 0 i nagłówka |
| `31ca610f-f121-4c0e-bbd6-60e75d7b81cd` | `scam` | 0–30, 35–40 | 31–34 | Obecny |
| `3a01e1f2-4de0-4fe6-a09d-de4f6e04f7ac` | `scam` | 0–14, 72 | 15–71 | Obecny |
| `897b0a26-f4a9-43e3-8894-1010644e67b2` | `calm_1` | 0–5, 23–27 | 6–22 | Obecny |
| `ec95568b-c709-4da8-afab-282ae1565c70` | `scam` | 0, 15–30 | 1–14 | Obecny |
| `f19c1ee1-2b7e-4336-b91a-8afc17dfd165` | `dictation` | 0–5, 32–34 | 6–31 | Obecny |

Łącznie znaleziono 103 dostępne fragmenty i co najmniej 121 brakujących indeksów. Nie da się wywnioskować, czy zabrakło także fragmentów po ostatnim dostępnym indeksie. Indeks fragmentu nie określa dokładnego czasu ani pięciosekundowego zakresu nagrania.

Sprawdzono obie lokalne kopie sesji:

- `/workspace/hackaton/HackYeach-2026-REPO/data/sessions/`
- `/workspace/HackYeach-2026-REPO_backup/data/sessions/`

Kopia zapasowa zawiera te same zestawy dostępnych indeksów; nie zawiera żadnego z brakujących fragmentów. Przeszukano również katalogi projektów i danych w `/workspace`, w tym `/workspace/hackyeah/`. Nie znaleziono trzeciej kopii żadnej z sześciu sesji. W dwóch znalezionych archiwach danych myszy (`mouse_events.zip`, `mouse_events.1.zip`) sprawdzono spisy plików: nie zawierają wideo ani tych sesji.

W dostępnych `net.jsonl` nie ma wpisów `video_chunk` potwierdzających odbiór któregokolwiek brakującego indeksu. To jest zgodne z niepełnym uploadem, ale same lokalne logi nie ustalają przyczyny utraty.

Pełna naprawa wymaga odzyskania brakujących oryginalnych fragmentów z urządzenia nagrywającego, oryginalnego serwera zbierającego dane lub dodatkowego backupu. Dla pierwszej sesji potrzebny jest także oryginalny fragment z nagłówkiem. Nie należy podmieniać nagłówka z obcego nagrania ani nadawać fragmentom nowych indeksów.

Częściowe odzyskiwanie pozostałych pięciu nagrań wymaga odrębnego trybu z kontrolą błędów dekodera, rzeczywistymi PTS oraz jawnymi maskami utraconych zakresów i zerowaniem stanu rPPG na granicach luk. Samo sklejenie dostępnych bajtów może zawierać urwane elementy WebM i zależności kodeka przez brakujące fragmenty; nie stanowi zweryfikowanego pełnego nagrania. Obecny pipeline celowo nie wykonuje takiego odzyskiwania.

Metadane, zdarzenia klawiatury/myszy i zapisane w przeglądarce punkty twarzy/postawy pozostają w źródłach. Powód pominięcia każdej sesji znajduje się także w `data/processed/inventory.json`, `run_report.json` i `sessions.parquet`.
