# Fuzja multimodalna (`training/fusion/`)

Mały transformer porównujący bieżącą sesję z profilem właściciela konta.
Zastępuje `fusion_session_model.py` + XGBoost (wyniki tamtych modeli były przeciekiem etykiet — niżej).

## Architektura

Okno 10 s, krok 5 s. Każde okno → 6 tokenów po 128D + CLS:

| token | wejście | uczone? |
|---|---|---|
| klawiatura | embedding 128D z `keyboard_windows.parquet` (Conformer `keystroke_long_epoch_59.pt`, zamrożony) | tylko `Linear(128,128)` adapter |
| mysz | 19 cech (prędkość, prostoliniowość, kliknięcia, pauzy, scroll) + różnica do profilu | MLP |
| tętno | BPM (średnia, std, nachylenie), koncentracja widma, jakość cropa z `pulse.parquet` | MLP |
| twarz/postawa | 52 blendshapes + 4 cechy postawy z `timeline.parquet` + ruch/rozmiar bboxa | MLP |
| kontekst | paste/copy/blur/hidden/focus, liczba wpisów w polach, sieć (RTT, jitter, latencja, błędy HTTP), zgodność urządzenia z profilem + wynik HGB sieci w slocie 64D | MLP (+ `Linear(64,128)` dla sieci) |
| profil | `adapter(profil klawiatury)` + MLP(średnie mysz/tętno/twarz z enrolmentu) | j.w. |

```
6 tokenów + CLS → TransformerEncoder (2 warstwy, 4 głowy, d=128, ff=256, pre-norm)
              → CLS → p(nie właściciel), p(właściciel pod presją)
```
341 tys. parametrów. Brakująca modalność = zero + `key_padding_mask` (nic nie jest zgadywane).

**Profil** = pierwsza połowa sesji `calm_1` danej osoby (każdy ma tylko jedną spokojną sesję). Druga
połowa jest próbką „spokój”. Podział jest po medianie okien klawiatury, a okna klawiatury nie są
współdzielone między enrolmentem a próbką.

## Pary i etykiety

| sesja | profil | nie-właściciel | presja |
|---|---|---|---|
| calm (2. połowa), dictation osoby A | A | 0 | 0 |
| scam osoby A | A | 0 | 1 |
| intruder (B na koncie A) | ofiara A | 1 | — |
| dowolna sesja B | A ≠ B | 1 | — |

Intruder wobec własnego profilu jest pomijany (niejednoznaczny). Pary powstają tylko wewnątrz jednego
splitu, cała osoba jest po jednej stronie.

## Trening

```bash
cd /workspace/hackaton/HackYeach-2026-REPO
/venv/main/bin/python -m training.fusion.train            # 3 seedy × 5 foldów na 4 GPU + model końcowy
/venv/main/bin/python -m training.fusion.train --rebuild-cache   # po zmianie data/processed
/venv/main/bin/python -m training.fusion.train --epochs 300 --patience 60 --min-epochs 20
```
- Porównanie pojemności (te same 3 seedy i 5 podziałów, osobny katalog wyników,
  bez nadpisywania modelu końcowego):

```bash
/venv/main/bin/python -m training.fusion.train --variant compact --no-final \
  --output-dir training/artifacts/fusion/experiments/compact
/venv/main/bin/python -m training.fusion.train --variant wider --no-final \
  --output-dir training/artifacts/fusion/experiments/wider
```

- Fold: ~8 osób test, ~7 walidacja (early stopping), reszta trening. Normalizacja tylko z treningu.
- Dropout modalności: tętno 0.3, twarz 0.3, kontekst 0.2, mysz/klawiatura 0.1.
- Pary ważone (każda sesja liczy się raz, klasy zbalansowane). Wynik sesji = średni logit okien.
- Model do alarmowania: 36 osób treningowych, 5 oddzielnych osób do wyboru
  checkpointu i progu. Nie jest trenowany na wszystkich 41 osobach: pozostawienie
  kalibracji poza treningiem jest konieczne, aby nie ustawić progu na wynikach
  osób widzianych przez model.
- Każdy fold uczy się niezależnie, więc liczby `best epoch` nie rosną po kolei.
  `best epoch 22/82` znaczy: 82 epoki wykonane, przywrócono checkpoint z epoki 22.
  Domyślnie limit wynosi 300, early stopping po 60 epokach bez poprawy.
  Wybór checkpointu opiera się na ciągłej, zbalansowanej stracie BCE na poziomie
  pary/sesji; dopiero od epoki 20. Wcześniejsze skokowe AUC na bardzo małym
  zbiorze walidacji dawało niestabilny wybór epoki. Stała prędkość uczenia 3e-4
  sprawia, że harmonogram modelu końcowego nie zależy od limitu epok CV.
  Nie należy na siłę trenować modelu końcowego do 300 epok przy spadku jakości
  walidacji.
- Artefakty: `training/artifacts/fusion/{fusion_model.pt, cv_summary.json, cv_scores.json, train.log}`.
- Sieć: ten sam typ HGB co w notebooku, ale trenowany od nowa na sześciu cechach
  okna (RTT, jitter, latencja, HTTP), bez liczników uploadów i profilu rzeczywistego
  uczestnika. W każdym foldzie model sieci widzi tylko osoby treningowe.
  Sesje **treningowe** fuzji dostają wynik sieci z wewnętrznego OOF po osobach;
  walidacja/test korzystają z modelu na wszystkich osobach treningowych.
  Końcowy checkpoint zawiera zarówno HGB na wszystkich osobach, jak i transformer.

## Wyniki CV (3 seedy × 5 foldów, poziom sesji)

| metryka | fuzja | bez kontekstu | cosinus klawiatury |
|---|---|---|---|
| nie-właściciel AUC | 0.961 ± 0.03 | 0.718 ± 0.08 | 0.722 ± 0.12 |
| nie-właściciel EER | 0.077 | 0.339 | 0.355 |
| nie-właściciel AUC na parach z klawiaturą | 0.957 | 0.777 | 0.722 |
| presja AUC (scam vs calm/dictation) | 0.792 ± 0.14 | 0.753 | — |

Po zmianie wyboru checkpointu i ponownym treningu z HGB sieci (3 seedy × 5 foldów):
nie-właściciel AUC **0.972 ± 0.021**, presja AUC **0.775 ± 0.138**.
Bez kontekstu odpowiednio 0.792 i 0.764. Zmieniono protokół treningu,
więc tych wartości nie należy interpretować jako samego wpływu modelu sieci.
Plik `cv_summary.json` zawiera wyniki wszystkich 15 foldów.

### Pojemność sieci a ryzyko przeuczenia

Przy tych samych foldach i identycznym wejściu porównano aktualną sieć z mniejszą,
mocniej regularyzowaną (96D, dropout 0.2, weight decay 0.1) i szerszą (160D,
dropout 0.2, weight decay 0.1). Obydwie nadal mają 2 warstwy i 4 głowy.

| Wariant | Parametry | AUC nie-właściciel | AUC bez kontekstu | AUC presja |
|---|---:|---:|---:|---:|
| baseline | 341 202 | 0.972 | **0.792** | **0.775** |
| compact | 210 866 | 0.972 | 0.752 | 0.773 |
| wider | 504 306 | 0.973 | 0.771 | 0.751 |

Większa sieć nie poprawiła wykrywania presji i pogorszyła ablacją zachowania
bez kontekstu. Także niższa strata walidacji w compact **nie** oznacza
lepszego AUC; nie wybierać modelu na jednej liczbie. Zostawiono baseline jako
model końcowy; warianty nie nadpisały `fusion_model.pt`. Wyniki wariantów są
w `training/artifacts/fusion/experiments/{compact,wider}/cv_summary.json`.
To eksperymenty na tych samych foldach używanych do wyboru architektury,
więc powyższe AUC są eksploracyjne, a nie niezależnym testem wybranego wariantu.
Na fold walidacyjny przypada niekiedy tylko kilka sesji presji; mocniejszy GPU
nie zwiększa liczby niezależnych osób ani scenariuszy.

### Ile dają cechy biometryczne z kamery?

Na tych samych 3 seedach × 5 foldach porównano pełny model oraz model uczony od
początku z wyłączonymi tokenami tętna i twarzy/postawy **oraz** ich statystykami
w spokojnym profilu. Model bez kamery wybiera epokę i próg tylko na osobach
walidacyjnych; ocena jest na testowych osobach. Dodatkowo wyłączono kamerę tylko
podczas testowania modelu uczonego z kamerą (test awarii kamery).

| Wariant | AUC nie-właściciel | AUC presja właściciela |
|---|---:|---:|
| trenowany i testowany z kamerą | **0.972 ± 0.021** | 0.775 ± 0.138 |
| trenowany z kamerą, testowany bez | 0.961 ± 0.028 | 0.805 ± 0.116 |
| trenowany i testowany bez | 0.961 ± 0.037 | 0.797 ± 0.115 |

Zysk z biometrii kamery dla wykrycia intruza to około **+0.011 AUC** w tym
eksperymencie (pełny vs bez kamery trenowany od zera), nie kilkanaście punktów
procentowych skuteczności. Dla presji nie wykazano zysku; zmiany są niewielkie
wobec zmienności foldów. Przy progach dobieranych osobno na walidacji pełny model
alarmował o 13/19, 16/19, 13/19 scamach (dla 3 seedów); model bez kamery
o 14/19, 10/19, 12/19, przy różnym koszcie fałszywych alarmów. To wciąż
**te same 19** sesji scam, nie 57 niezależnych przypadków.

Maskowanie dotyczy tylko cech biometrycznych `pulse`, `face` i ich profilu;
kontekst (w tym czas odpowiedzi uploadów recordera i zgodność urządzenia)
pozostaje dostępny i może pośrednio kodować obecność wideo. Nie jest to
eksperyment „bez jakichkolwiek śladów działania kamery”. Z 108 sesji cechy
twarzy dostępne były w 83, tętna w 82; brak modalności był maskowany.
Wyniki eksploracyjne, bez niezależnego zbioru nowych użytkowników.

```bash
/venv/main/bin/python -m training.fusion.train --no-camera --no-final \
  --output-dir training/artifacts/fusion/experiments/no_camera
```

Raporty: `training/artifacts/fusion/experiments/{camera_ablation_baseline,no_camera}/cv_summary.json`.
Domyślny model w `training/artifacts/fusion/fusion_model.pt` **nie** został
nadpisany eksperymentem.

### Kamera bez cech zgodności urządzenia

Powtórzono pełne CV (3 seedy × 5 foldów na tych samych osobach) z wyzerowanymi
dziewięcioma cechami porównania urządzenia z profilem, również `device_known`.
Zarówno trening, wybór epoki/progu na walidacji, jak i test nie widzą tych cech.
Pozostały kontekst i fold-local model sieci pozostały bez zmian. Wariant bez
kamery dodatkowo usuwa tętno, twarz/postawę i odpowiadające im statystyki
profilu również w treningu, a nie dopiero przy teście.

| Wariant bez zgodności urządzenia | AUC nie-właściciel | EER nie-właściciel | AUC presja właściciela |
|---|---:|---:|---:|
| z kamerą | **0.840 ± 0.067** | 0.241 ± 0.080 | 0.768 ± 0.123 |
| bez kamery | 0.752 ± 0.120 | 0.318 ± 0.092 | **0.791 ± 0.105** |

Sparowana różnica AUC nie-właściciela wynosi **+0.088** dla kamery (12/15
foldów na korzyść kamery). To dowód użyteczności cech kamery *w tym zbiorze
i przy tej konstrukcji par*, nie 8,8 punktu procentowego gwarantowanej
wykrywalności na nowych urządzeniach. Dla presji różnica wynosi -0.023 AUC
(7/15 foldów na korzyść kamery); nie widać poprawy.

Przy progach ustawianych osobno na walidacji alarm objął odpowiednio
18/19, 15/19, 16/19 sesji scam z kamerą oraz 19/19, 18/19, 18/19 bez
kamery w trzech seedach. Kosztem były alarmy w 48/62, 33/62, 42/62
zwykłych sesji z kamerą i 57/62, 46/62, 38/62 bez niej. Te seedy ponownie
oceniają **te same 19 scamów**; nie są 57 niezależnymi próbami. Naturalnych
przypadków intruza było tylko 0, 1, 0 na seed; większość par intruzów
utworzono sztucznie. Pozostałe cechy sieci/kontekstu mogą nadal zdradzać
sprzęt lub obecność recordera. Jest to eksploracyjna ablacja, nie niezależna
walidacja na nowych osobach, kamerach i urządzeniach.

```bash
/venv/main/bin/python -m training.fusion.train --no-device-match --no-final \
  --gpus 0,1,2,3 --output-dir training/artifacts/fusion/experiments/no_device_with_camera
/venv/main/bin/python -m training.fusion.train --no-device-match --no-camera --no-final \
  --gpus 0,1,2,3 --output-dir training/artifacts/fusion/experiments/no_device_no_camera
```

Raporty: `training/artifacts/fusion/experiments/{no_device_with_camera,no_device_no_camera}/cv_summary.json`.
`--no-final` chroni wdrożony checkpoint; przy trenowaniu własnego modelu
końcowego checkpoint zapisuje `device_match_off` i inferencja respektuje tę flagę.

### Osłabiona, ale zachowana zgodność urządzenia

Zamiast wyłączać dziewięć cech porównania urządzenia (w tym `same_timezone`),
pomnożono je przez 0.25 i losowo wyłączano razem w 50% okien **treningowych**.
Na walidacji, teście i podczas inferencji dostępne są zawsze z mnożnikiem
0.25, bez losowości. Dropout ogranicza poleganie na tych cechach: samo
przeskalowanie wejścia nie gwarantuje mniejszego wpływu, bo sieć mogłaby
zwiększyć wagi. Porównanie obejmuje identyczne 3 seedy × 5 foldów, osoby,
model sieci i pozostały kontekst; jest to jedna zadana konfiguracja,
nie hiperparametry wybrane na podstawie wyników testu.

| Zgodność urządzenia | AUC nie-właściciel z kamerą | AUC nie-właściciel bez kamery | AUC presja z kamerą | AUC presja bez kamery |
|---|---:|---:|---:|---:|
| pełna (poprzedni eksperyment) | 0.972 ± 0.021 | 0.961 ± 0.037 | 0.775 ± 0.138 | 0.797 ± 0.115 |
| osłabiona: 0.25, dropout 0.5 | **0.877 ± 0.056** | 0.854 ± 0.100 | 0.767 ± 0.138 | 0.794 ± 0.114 |
| wyłączona (poprzedni eksperyment) | 0.840 ± 0.067 | 0.752 ± 0.120 | 0.768 ± 0.123 | 0.791 ± 0.105 |

Przy osłabionej zgodności kamera podnosi AUC intruza o 0.023 (10/15 foldów),
ale nie daje przewagi w wykrywaniu presji. EER intruza wynosi odpowiednio
0.202 z kamerą i 0.219 bez. Progi wybrane oddzielnie na walidacji alarmowały
o 18/19, 17/19, 16/19 scamach z kamerą i 17/19, 15/19, 17/19 bez, a także
o 49/62, 37/62, 36/62 oraz 43/62, 44/62, 32/62 zwykłych sesji.
Zatem ograniczenie polegania na urządzeniu wyraźnie pogarsza wynik intruza
w porównaniu z pełną zgodnością i nadal kosztuje wiele fałszywych alarmów.

Nie ma tu geolokalizacji IP ani danych o zmianie miejsca tej samej osoby:
`same_timezone` jest tylko wskaźnikiem strefy czasowej. Te CV **nie mierzą**
odporności na prawdziwe logowanie właściciela z innego miejsca lub urządzenia;
potrzebny jest taki scenariusz w zbiorze testowym. Mnożnik i dropout to
regularizacja, a nie twarda gwarancja maksymalnej wagi cech urządzenia.
Pozostałe cechy sieciowe nadal mogą pośrednio sygnalizować środowisko.

```bash
/venv/main/bin/python -m training.fusion.train --device-match-scale 0.25 \
  --device-match-dropout 0.5 --no-final --gpus 0,1,2,3 \
  --output-dir training/artifacts/fusion/experiments/weak_device_with_camera
/venv/main/bin/python -m training.fusion.train --device-match-scale 0.25 \
  --device-match-dropout 0.5 --no-camera --no-final --gpus 0,1,2,3 \
  --output-dir training/artifacts/fusion/experiments/weak_device_no_camera
```

Raporty: `training/artifacts/fusion/experiments/{weak_device_with_camera,weak_device_no_camera}/cv_summary.json`.
Checkpoint końcowy, jeśli go później wytrenujesz bez `--no-final`, zapisuje
skalę; inferencja stosuje ją automatycznie. Wdrożony checkpoint pozostaje bez
zmian.

Uwagi do interpretacji:
- Większość wyniku „nie-właściciel” daje **zgodność urządzenia** (ten sam UA/ekran/strefa czasowa).
  W danych intruz zawsze siedzi przy innym komputerze. Uczciwa miara samej biometrii zachowania to
  kolumna „bez kontekstu”: 0.78 vs 0.72 dla samego cosinusa klawiatury na tych samych parach.
- Presja ma duży rozrzut (~8 osób na fold). Traktować jako sygnał, nie jako dowód.
- BPM z kamery to estymata eksperymentalna.

## Inferencja

```bash
/venv/main/bin/python -m training.fusion.infer --session <session_id|katalog> --profile <participant_code> [--windows]
/venv/main/bin/python training/inference_xgb_suspicious.py --session <id> --profile <participant_code>
```
`FusionPredictor.predict(session, profile)` sam wylicza wynik modelu sieci zapisanego
w checkpointcie fuzji. Zwraca `p_not_owner`, `p_pressure`, pomocniczy
`network_signal` (średnia prognoza HGB dla scam/intruder, niekalibrowana) oraz wyniki per okno.
Stary checkpoint bez modelu sieci jest odrzucany z instrukcją ponownego treningu.

### Opcjonalny sygnał manipulacji twarzy

Niezależny klasyfikator obrazów [Deep-Fake-Detector-v2-Model](https://huggingface.co/prithivMLmods/Deep-Fake-Detector-v2-Model)
(licencja Apache-2.0, przypięta rewizja) ocenia maksymalnie 16 klatek z
lokalnego nagrania; MediaPipe wykrywa i kadruje twarz przed klasyfikacją.
Nic nie wysyła nagrania do zewnętrznej usługi; pierwszy start pobiera tylko
wagi publicznego modelu. Opcja nie zmienia `p_not_owner`, `p_pressure`,
`review_score` ani progu alarmu i nie wymaga ponownego treningu fuzji.

```bash
/venv/main/bin/python -m pip install -r training/fusion/requirements-deepfake.txt
/venv/main/bin/python -m training.fusion.infer \
  --session <session_id> --profile <participant_code> --deepfake
# Stary punkt wejścia obsługuje tę samą opcję:
/venv/main/bin/python training/inference_xgb_suspicious.py \
  --session <session_id> --profile <participant_code> --deepfake
# Dla własnego nagrania zamiast lokalnych chunków sesji:
/venv/main/bin/python -m training.fusion.infer \
  --session <session_id> --profile <participant_code> --deepfake \
  --deepfake-video /ścieżka/do/nagrania.webm
```

`deepfake_assessment.status` jest `scored_unvalidated` albo `unavailable`
(np. `no_source_video`, `no_face_detected`). Zwracane są liczba ocenionych
klatek oraz mediana, maksimum i 90. percentyl wyniku klasy `Deepfake`
**na klatkach**, nie prawdopodobieństwo, że osoba jest deepfake'em. Nie
interpretuj braku filmu/twarzy ani niskiej oceny jako dowodu autentyczności.
Model jest klasyfikatorem **obrazów**, nie wykrywa replay attack ani
żywotności i nie był walidowany na tych nagraniach z kamery. Nawet prawdziwe
lokalne klatki potrafią otrzymać wysokie wyniki klasy fake. Bez nagrań
deepfake/replay z tego samego środowiska nie ma uczciwego progu decyzji
ani miary false positive/false negative. Wyjście służy tylko jako wskazówka
do ręcznej analizy; nie blokuje użytkownika.

### Alarm do dodatkowej weryfikacji, nie blokada

`training/inference_xgb_suspicious.py` zwraca teraz `review_score`,
`review_threshold` i `review_required`. `review_score` łączy oba wyjścia, ale
**nie jest skalibrowanym procentem fraudu**. Domyślnie używa progu zapisanego
w checkpointcie; argument `--threshold` nadpisuje go świadomie. Przyjęty cel
to co najmniej 95% wykrycia **na walidacji**, osobno dla scamów właściciela
i par intruzów, z najwyższym progiem spełniającym oba warunki. To tylko
skierowanie do ręcznej/dodatkowej weryfikacji; bez automatycznej blokady.

Prawdziwy wynik na testowych osobach **nie osiągnął** celu 95% dla scamów.
Przy 3 seedach (w każdym te same 19 sesji scam, inne modele/splity) progi
wybrane bez patrzenia na test wykryły 13/19, 16/19, 13/19 scamów.
Fałszywy alarm otrzymało odpowiednio 36/62, 27/62, 26/62
spokojnych/dyktowanych sesji własnego właściciela. Syntetyczne pary
intruzów wykryto w 665/681, 643/671, 662/684; naturalnych par
intruz–ofiara w tych splitach było 0, 1, 0. **Nie** mnożyć 19 × 3 jako
57 niezależnych scamów. Próg wdrożonego modelu wynosi 0.1285, dobrany
na zaledwie 3 scamach w 5 osobach walidacyjnych; ten sam zbiór wybrał
również epokę. Nie ma gwarancji 95% wykrycia u nowych osób.

Sprawdzono również eksperymentalny próg 0.05 na zapisanych wynikach testu:
wykrywał 18–19/19 scamów, ale wysyłał do weryfikacji 50–53/62
normalnych sesji (81–85%). Ponieważ próg wybrano *po obejrzeniu testu*,
to tylko analiza kompromisu, a nie uczciwy wynik wdrożeniowy; **nie** jest
domyślnym progiem. Żeby realnie ograniczyć false negative, potrzeba więcej
niezależnych osób i scamów, a także prób intruza wobec własnej ofiary.

## Model sieci — jak go podpiąć

Analiza `/network_session_train.ipynb`:
- `server_request` w `network.parquet` to wyłącznie uploady recordera (`/face`, `/events`, `/video`,
  `/net`, `/api/ping`), nie ruch aplikacji bankowej.
- Notebook czyta `method`/`path` z kolumn najwyższego poziomu, a one są w `payload_json`. Słownik
  LSTM to więc tylko `GET:other:na`, a sekwencja nie niesie informacji.
- Logreg (grouped CV AUC 0.72) prawie w całości opiera się na `n_req` (sam daje 0.735): scam trwa
  dłużej i ma czat, więc recorder wysyła więcej requestów. To artefakt nagrywania.
  Samo RTT daje 0.53, intruz vs reszta 0.52.
- Etykieta `pressure = scam + intruder` miesza dwa różne zadania.

Dlatego fuzja bierze z sieci tylko jakość połączenia per okno (RTT, jitter, latencja, błędy HTTP;
bez liczników requestów). W `net_emb[:, 0]` umieszcza prawdopodobieństwo z HGB;
pozostałe 63 wymiary są zerowe. Nie jest to „embedding LSTM”.
Model `data/processed/models/network/network_hgb.joblib` **nie jest ładowany**:
był wytrenowany na wszystkich osobach, ma 51 cech (w tym `z_*` względem
rzeczywistego użytkownika oraz liczniki uploadów). Wpięcie jego wag do CV
przeciekłoby etykiety i osoby testowe. Zamiast tego `training/fusion/network.py`
trenuje fold-local HGB z tymi samymi hiperparametrami na bezpiecznym podzbiorze
cech; przy trenowaniu końcowym zapisuje nowy model sieci w `fusion_model.pt`.

Tabela bazowa CV powyżej pochodzi z poprzedniego przebiegu bez HGB sieci;
nowe wyniki są pod nią i w aktualnym `cv_summary.json`.

## Co było zepsute w starym kodzie

- `context_vector` zawierał ankietę `stress`/`hurry` (wypełnianą **po** sesji), `condition`, `group`,
  `meta`. `mouse_vector` też miał stress/hurry, a XGB doklejał `[stress, hurry]`. Stąd AUC stresu = 1.0.
  Pikle w `training/artifacts/xgboost*/` są bezwartościowe.
- Profil zawierał samą ocenianą sesję; brak par „B wobec profilu A”.
- Maski modalności z normy wektora; `_numeric_from_session` uśredniał dowolne kolumny (z timestampami).
- `pulse_windows.parquet` ma `heart_rate_bpm = null` wszędzie, więc tętno było puste. Teraz `pulse.parquet`.
- Pole `chat_reply` i markery czatu występują tylko w scam. Wykluczone (`LEAKY_FIELDS`).

`fusion_session_model.py` ma usunięte te przecieki (zostaje dla zgodności),
a oryginalna inferencja XGB jest w `inference_xgb_suspicious_legacy.py` tylko do wglądu.

## CatBoost i XGBoost myszy (GUIDÆTA)

`training/mouse_boost_benchmark.py` porównuje modele na **tych samych** cechach i parach:
task 1 = enrolment, task 2–3 = probe; 5 losowych intruzów na probe. Osoby w train/val/test
są rozłączne. Każdy z pięciu zewnętrznych foldów wybiera jedną z czterech konfiguracji
hiperparametrów na *wewnętrznym* zbiorze walidacyjnym, po czym przelicza skalowanie
na train+val, uczy model i ocenia go raz na test. Punktem odniesienia jest odległość L1.

W pierwotnym notebooku `/Mouse_emmbededr.ipynb` każda próbka probe była najpierw
normalizowana względem profilu **rzeczywistego** użytkownika, również dla pary intruza;
dopiero potem odejmowano profil deklarowanego właściciela. To używa prawdziwej
tożsamości podczas inferencji i czyni pary intruzów błędnymi. Nowy eksperyment uczy
globalną medianę/IQR tylko na osobach treningowych; potem porównuje tę samą próbkę
z medianą task 1 **deklarowanego** użytkownika: `abs(z_probe - z_enroll_claimed)`.
Nie używać wcześniejszego `mouse_catboost_full.cbm` bez ponownego treningu.

| AUC (średnia z 5 testowych foldów) | seed 42 | seed 43 |
|---|---:|---:|
| L1 | 0.671 | 0.679 |
| CatBoost (strojenie) | **0.767** | **0.763** |
| XGBoost (strojenie) | 0.762 | 0.761 |

EER w seed 42: L1 0.377, CatBoost 0.301, XGBoost 0.304.
Różnica CatBoost–XGBoost (~0.003 AUC między seedami) jest zbyt mała, by ogłaszać
XGBoost zwycięzcą. CatBoost zastępuje błędny model myszy, ale **nie** model fuzji.
To benchmark weryfikacji tożsamości na GUIDÆTA (163 osób), a nie wynik HackYeah.
Syntetyczne pary od tych samych osób są skorelowane; nie interpretować ich liczby
jako liczby niezależnych prób. Dopasowanie task 1 → 2/3 pozostaje trudniejsze niż
odtwarzanie tego samego zadania.

```bash
/venv/main/bin/python -m training.mouse_boost_benchmark
/venv/main/bin/python -m training.mouse_boost_benchmark --seed 43 \
  --output training/artifacts/mouse_boost/comparison_seed43.json --no-final
```

Raporty, nowo wytrenowane modele i skalowanie są w `training/artifacts/mouse_boost/`.
`score_mouse(probe, enrollment, kind="catboost")` bierze surowy wektor 20 cech
GUIDÆTA i sesje task 1 deklarowanego właściciela (bez tożsamości osoby z probe).
Model fuzji ma 10-sekundowe okna myszy z **innymi** 19 cechami; nie można wsunąć
GUIDÆTA CatBoosta w token myszy ani cytować tego AUC jako wyniku fuzji.
Najpierw trzeba wystawić wspólny ekstraktor cech lub nauczyć model na oknach HackYeah
i przeprowadzić oddzielny test po uczestnikach.
