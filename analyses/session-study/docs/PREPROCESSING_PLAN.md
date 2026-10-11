# Pipeline multimodalny — plan roboczy

Cel: przetworzyć pełne nagrania czterech warunków (calm, dictation, scam, intruder) do liczbowych danych sesji z jedną osią czasu. Źródłowe filmy pozostają do weryfikacji; po potwierdzeniu kompletności wyników można je archiwizować poza serwerem.

## Ustalenia z repo

- Główne repo i zbiór: `/workspace/hackaton/HackYeach-2026-REPO`, `data/sessions`. Dane mogą przybywać przez synchronizację. Przetwarzamy domyślnie tylko zakończone sesje i ciągłe numerowane fragmenty kontenera.
- Browser zapisuje performance.now() w milisekundach, Date.now() oraz clock_sync offset/RTT; serwer używa Unix seconds. FaceFrame.video_ts to zegar performance, nie PTS filmu.
- Stare nagrania nie mają precyzyjnego punktu powiązania pierwszej klatki z zegarem browsera. Wynik musi zawierać status i niepewność synchronizacji; nie wolno udawać dokładności. Nowym nagraniom dodamy marker startu MediaRecorder.
- Fragmenty MediaRecorder składają się na jeden kontener. Łączyć bajty w kolejności numerów, nie dekodować każdego fragmentu osobno ani przypisywać mu arbitralnie 5 sekund.
- Serwer ma cztery RTX 5090, torch 2.11 + CUDA 12.8. Każdy worker dostaje osobną kartę; wspólna kolejka sesji zapobiega nierównemu obciążeniu scenariuszy.
- Lokalne PhysNet UBFC-rPPG, MediaPipe Face/Pose dostępne. Twarz i postawa działają na CPU; neural rPPG i klawiatura na GPU.
- Model klawiatury przyjmuje 16–96 naciśnięć i 8 dokładnie zdefiniowanych cech; istniejące wagi zwracają 128 wymiarów. 96 nie jest wymiarem embeddingu tego checkpointu. Nie zmieniamy arbitralnie gotowych wag.

## Implementacja

1. Manifest wszystkich sesji z warunkiem, statusem, źródłami, rozmiarem i fingerprintem. Nowe pliki pakietu preprocessing; nie nadpisujemy istniejących zmian platformy ani starego ekstraktora.
2. Osobne moduły clock/ograniczony resampling, events/keyboard/mouse, reusable VisionExtractor.
3. Jedno dekodowanie RGB, stabilne PTS, rzadsza detekcja twarzy/postawy i krojenie do modelu rPPG, bufory ograniczone rozmiarem okna. Zapis punktów, blendshapes, geometrii postawy, przebiegu pulsu, HR i jakości.
4. Per-session Parquet + kontekst JSON (metadane, survey, net/HAR). Klawiatura: oryginalne kolejności zdarzeń i 128D embeddingi z masek. Mysz: ekstrakcja liczb i timestampów bez treningu.
5. Wspólna siatka czasu z maskami obserwacji/interpolacji/ekstrapolacji i maksymalną dozwoloną przerwą; braków nie zastępujemy zerami. Zdarzenia myszy/klawiatury zachowujemy niezależnie od siatki.
6. Dynamiczna kolejka na 4 GPU, spawn bez dziedziczenia CUDA, limit CPU threads. Atomowa publikacja kompletnej sesji, wznowienie po zgodnym fingerprincie, blokada równoległych writerów, izolacja błędu jednej sesji.

## Weryfikacja

Testy jednostek konwersji czasu, przerw i ekstrapolacji, key pairing i preprocessingu Aalto, load checkpoint. Test integracyjny na prawdziwych nagraniach wszystkich warunków, benchmark GPU/CPU, później pełna ekstrakcja zbioru i kontrola manifestu/outputów. Code review obejmie błędy synchronizacji, memory growth, resume/atomowość, brakujące modality i zgodność wag.
