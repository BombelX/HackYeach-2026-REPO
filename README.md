# Bank24 — platforma do zbierania danych (HackYeah 2026)

Strona udająca bankowość internetową (układ dwuetapowego logowania jak w Pekao24, **własna marka Bank24**). Prowadzi uczestnika przez spokojne logowania, dyktowanie numeru, presję „pracownika banku” i włamanie na cudze konto. W jednym zegarze zapisuje:

- obraz z kamery (opcjonalnie) oraz punkty twarzy / postawy / RGB skóry
- klawiaturę i mysz z timestampami
- środowisko przeglądarki, Resource Timing, ping RTT, IP/ASN

To **nie jest prawdziwy bank**. Stopka i baner to powtarzają — nie kopiujemy nazwy ani logo Pekao, żeby Google i CERT nie oznaczyły domeny jako phishing.

## Szybki start (Windows)

```powershell
cd web
npm install
cd ..\server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Dwa terminale:

```powershell
# 1. API
cd server
.\.venv\Scripts\Activate.ps1
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# 2. UI
cd web
npm run dev
```

Albo skrypt:

```powershell
.\scripts\start.ps1
```

Otwórz http://localhost:5173 (badanie) i http://localhost:5173/admin (panel). Hasło panelu: `hackyeah` (albo zmienna `ADMIN_PASSWORD`).

## HTTPS / tunel (kamera)

`getUserMedia` wymaga HTTPS poza localhost. Wystaw Vite albo zbudowany backend:

```powershell
cloudflared tunnel --url http://127.0.0.1:5173
```

Na hali: `npm run build` w `web/`, potem sam uvicorn na 8000 serwuje `web/dist`, tunel na port 8000.

## Przebieg badania (~12 min)

1. Kod uczestnika z panelu (`P-…`)
2. Zgody (wideo osobno)
3. Kalibracja kamery 60 s
4. Zapamiętanie własnego loginu
5. Sesje: spokój ×2, dyktowanie / oszust / intruz (kolejność środka losowa), spokój na koniec
6. Po każdej sesji stres i pośpiech 1–7

Intruz: 20 s kartka z wyciekiem, 90 s na przelew z cudzego konta, losowy alert o nowym urządzeniu. Oszust: synteza mowy dyktuje „rachunek techniczny” i licznik 2 min.

## Dane

```
data/participants.sqlite
data/sessions/<id>/meta.json
data/sessions/<id>/events.jsonl
data/sessions/<id>/face.jsonl
data/sessions/<id>/net.jsonl
data/sessions/<id>/video/*.webm
data/sessions/<id>/survey.json
```

Eksport do Parquet (cechy per etap + maska sygnałów):

```powershell
cd server
.\.venv\Scripts\python.exe export.py --out ..\data\export
```

## vast.ai

Trening modeli nie jest w tej aplikacji. Zbieranie danych trzymaj na laptopie + tunel. Na vast.ai rezerwuj 400–500 GB dysku z góry (nie da się potem powiększyć).

## Struktura repozytorium

- `web/` — frontend aplikacji badania i panel admina
- `server/` — API, zapis zdarzeń i eksport danych
- `scripts/` — skrypty pomocnicze do uruchamiania lokalnego
