# Wynik przetwarzania — 2026-10-03

Gotowe dane: `data/processed/`. Zapis zawiera wyłącznie Parquet/JSON
i dodatkowy kontekst, bez filmów lub klatek obrazu. Źródłowe nagrania
pozostały nienaruszone. Rozmiar wyników w chwili walidacji: około 955 MB.

## Pokrycie zbioru

Przejrzano 201 sesji. Przetworzono 108: calm 39, dictation 27,
intruder 21, scam 21. Zawierają 84 filmy o łącznej długości
13 937,028 s; 24 sesje bez filmu zachowują klawiaturę, mysz i kontekst.
Uwzględniono stabilny stan dziewięciu niezamkniętych sesji.
Pozostały jawnie pominięte: 62 kalibracje, 25 usuniętych sesji
i sześć zestawów nagrań z brakującymi chunkami.
Identyfikatory i brakujące indeksy: [INPUT_ISSUES.md](INPUT_ISSUES.md).
Brakujących danych nie uzupełniono fragmentami innych sesji.

| Tabela | Wiersze |
|---|---:|
| keyboard | 7 963 |
| keyboard_events | 16 351 |
| keyboard_windows | 1 039 |
| mouse | 360 286 |
| network | 49 542 |
| markers | 22 000 |
| frames | 69 652 |
| pulse | 418 155 |
| pulse_windows | 4 388 |
| timeline | 69 730 |
| browser_face | 212 399 |

`sessions.parquet` zawiera wszystkie 201 sesji, także pominięte, z powodami,
etykietami, identyfikatorami uczestników i maskami dostępności.
Mysz jest dostępna w 108 sesjach; wideo w 84; HR, twarz i postawa w 83.
Jedno nagranie nie zawiera poprawnej detekcji twarzy/postawy.

Model klawiatury otrzymał oryginalne cechy Aalto, okna maks. 96 naciśnięć
i maski. Prawdziwy model zwraca 128D, a nie 96D. Profile są dostępne
w 68 sesjach. W 40 brak klawiszy lub poprawnych segmentów długości
co najmniej 16; zachowano krótkie segmenty i maskę false zamiast
wymyślać embedding. Spośród 1 039 zapisanych segmentów 143 mają
poprawny embedding okna. Modelu myszy nie trenowano i nie uruchamiano.

## Synchronizacja i estymaty

Wszystkie 84 istniejące filmy mają `approx_session_start`. Recorder
nie zapisywał dokładnej kotwicy początku nagrania, więc wyrównanie
do czasu serwera ma jawnie opisany przedział niepewności.
Żaden upload chunku nie został uznany za dokładny czas jego klatek.
Nowy recorder zapisuje kotwicę żądania startu dla przyszłych nagrań.

Puls/BPM to estymata kamery z pretrained PhysNet. Nie ma pomiaru
referencyjnego ECG. Luki detekcji pozostają null; interpolacja liczb
jest ograniczona i oznaczona maskami. Równoległe części długiego filmu
mają jawne granice historii modelu; amplitud nie należy scalać do HRV.

## Testy i przegląd

- 61 testów jednostkowych/regresyjnych PASS, w tym 14 testów
  równoległej ekstrakcji i pięć testów odrzucania nieaktualnego cache.
- Architektura modelu klawiatury daje ten sam wynik co kod treningowy;
  preprocessing pierwszych 512 przykładów Aalto jest bitowo zgodny.
- TypeScript `tsc --noEmit` i build Vite PASS po dodaniu kotwicy recordera.
- Walidator danych: 108 sesji i 201 wierszy indeksu, brak błędów.
  Sprawdza źródła, rozmiary artefaktów, liczby rekordów, monotoniczność,
  maski brakujących sygnałów, wymiary i normy profili.
- Wznowienie CLI: 108 resumed, 0 queued. Żadne gotowe dane nie zostały
  ponownie liczone. Ten przebieg trwający mniej niż sekundę tworzył
  tylko końcowy raport i indeks; nie jest czasem całej ekstrakcji.
- Niezależny code review objął zegary, cechy Aalto, zdarzenia myszy,
  rPPG, modelowe maski, pokrycie segmentów i atomowe publikowanie.
  Poprawiono m.in. gubienie opcjonalnych kolumn przez Arrow,
  granice okien pulsu, kontrolę nowych chunków i zamykanie kolejki
  po przerwaniu procesu.

Raport maszynowy: `data/processed/validation.json`.
Przebieg i pominięcia: `run_report.json`, `run_summary.json`, `inventory.json`.
Raport pokrycia długiego filmu znajduje się także w katalogu jego sesji
jako `parallel_validation.json`.

## Zasoby

Właściwy przebieg używał 32 workerów i wszystkich czterech RTX 5090.
Pomiar: około 43 rdzeni CPU, 62 GiB RSS, 15–17 GiB VRAM na GPU,
bez OOM. MediaPipe i dekodowanie są głównym ograniczeniem;
sam PhysNet ma około 0,916 GB peak allocated memory na worker.
Długi film kończący kolejkę przetworzono dodatkowo w 16 częściach
równoległych na czterech GPU: 24,09× realtime, z kontrolą pokrycia.
Szczegóły i polecenia są w [PREPROCESSING.md](PREPROCESSING.md).

Ta instancja nie ma host volume. Wyniki znajdują się lokalnie;
przed recycle/destroy trzeba skopiować je poza instancję.
