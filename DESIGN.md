---
name: Bank24 / SafeTransfer
description: Calm, light fintech interface inspired by the supplied Bank24 screens.
colors:
  navy: "#062f4c"
  navy-hover: "#0a456a"
  accent: "#00645f"
  mint: "#b6e4da"
  mint-hover: "#d0eee7"
  mint-tint: "#e5f2ef"
  ink: "#102b43"
  muted: "#647786"
  line: "#d8e1e5"
  surface: "#ffffff"
  canvas: "#f5f7f7"
  success: "#236a54"
  success-bg: "#edf7f1"
  amber: "#81561b"
  amber-bg: "#fff7e8"
  error: "#a5323a"
typography:
  family: "IBM Plex Sans, Segoe UI, sans-serif"
  body: "16px / 1.55"
  task-heading: "clamp(30px, 4vw, 42px) / 1.15 / 600"
  support: "12–14px / 1.5"
  balance: "clamp(32px, 4vw, 43px), tabular figures"
---

# Bank24 — wdrożony system interfejsu

## Charakter

Interfejs bierze hierarchię i kompozycję z planszy mockupów użytkownika:
jasne powierzchnie, chłodne neutralne tło, granatowe akcje i oszczędny teal.
Układ wykorzystuje prawdziwe dane demo i zwykłe HTML/CSS. Nie naśladuje
obrazka z makiety jako nieinteraktywnego zrzutu. Nie używa stockowej fotografii
w module kamery, fikcyjnych wykresów ryzyka ani komunikatów obiecujących
wykrywanie oszustw.

Publiczny landing pod `/` działa bez pobierania sesji lub API. Prowadzi do
logowania, a następnie przez kod do dashboardu. Bankowość ma oddzielny nagłówek,
nawigację boczną, treść i stopkę. Kamera jest opcjonalnym modułem tylko podczas
nowego przelewu; gdy pracuje, jej status oraz przycisk Wyłącz pozostają w
nagłówku bankowym.

## Tokeny i komponenty

- Font: IBM Plex Sans, lokalne pliki WOFF2 w `frontend/public/brand/`.
- Baza: tło `#f5f7f7`, białe karty, tekst `#102b43`, opisy `#647786` i linie
  `#d8e1e5`.
- Akcja główna: granat `#062f4c`; interakcje i linki: ciemny teal `#00645f`.
  Mięta `#b6e4da` występuje oszczędnie na karcie konta.
- Zieleń, bursztyn i czerwień są zarezerwowane dla komunikatów stanu. Brak
  wyniku modelu jest opisywany tekstem i nie dostaje zielonego stanu.
- Kontrolki mają minimum 44 px wysokości, promień 5 px i widoczny focus.
  Panele mają delikatną krawędź, niewielki promień i nie polegają na cieniu.
- Nagłówki zadań są responsywne; kwoty i numery rachunków używają cyfr
  tabelarycznych. Informacje dodatkowe są spokojniejsze i nie konkurują z CTA.

## Strony

### Landing

Nagłówek ma logo, kotwice do treści i jeden przycisk logowania. Hero składa się
z krótkiej obietnicy, jasnej ścieżki do logowania oraz lokalnej fotografii
górskiego jeziora z drobną kartą fikcyjnego rachunku. Treści są tekstem HTML i
na telefonie układają się pod sobą. Dalsze sekcje opisują działające możliwości,
bez sugerowania realnych produktów lub zwalidowanej ochrony.

Obraz `frontend/public/brand/bank24-landscape.png` wygenerowano narzędziem
ImageGen na potrzeby tego landing page. Prompt: “Premium editorial landscape
photograph for a fictional Polish digital bank landing page: Lake Czorsztyn
and the Tatra Mountains at a quiet early sunrise, calm water, soft blue-green
palette, subtle mist, sophisticated natural light, generous open sky, realistic
photography, no text, no logos, no people, wide 16:9 composition.”

### Logowanie

Samodzielny, wąski panel formularza, na spokojnym tle. Login i hasło są
głównym zadaniem; zapamiętanie urządzenia i pomoc są łatwe do odnalezienia.
Telemetria jest niezaznaczoną opcją z opisem zakresu. Demo credentials
pojawiają się w małej, wyraźnie opisanej sekcji. OTP ma jeden dostępny input,
autofill, filtr znaków, licznik, ponowienie i długość pobieraną z API.

### Konto i historia

Dashboard pokazuje saldo, rachunek i wyraźny CTA nowego przelewu. Podsumowanie
miesiąca wylicza różnicę z realnych wartości i pokazuje pusty stan, gdy nie ma
operacji. Lista transakcji ma czytelne kwoty oraz etykiety. Kopiowanie rachunku
ma prawdziwy przycisk i komunikat dostępnościowy. Historia wyszukuje na serwerze
przed paginacją; filtry mają stan w URL i działają klawiaturą.

### Przelew i kamera

Formularz i faktura są widoczne obok siebie na szerokim ekranie. Ekran
sprawdzenia łączy podsumowanie, stan niezwalidowanej oceny ryzyka, porównanie
danych i pytanie o samodzielność decyzji. Serwer nadal wymusza przejście
`review → ready/held`; po zgodzie na przejście wydawany jest kod, potem wynik.
Użytkownik może edytować lub anulować. Kamera uruchamia się dopiero po osobnej
zgodzie, używa video-only transportu i wyświetla stan, awarię oraz świeżość
wyniku. Każdy ekran bankowy zapewnia skrót Wyłącz, gdy kamera działa.

## Responsywność i dostępność

- Szerokość dokumentu nie może przekraczać viewportu od 320 px wzwyż.
- Poniżej 1150 px panel kamery schodzi pod zadanie; poniżej 800 px nawigacja
  bankowa i sidebar przechodzą w kompaktowe paski; poniżej 560 px wszystkie
  główne siatki układają się w jedną kolumnę.
- Tabela historii zmienia wąskie wiersze w podpisane karty. Pola oraz długie
  wartości mogą się zawijać.
- Każdy widok ma jeden nagłówek H1, skip link, czytelny focus, etykiety pól,
  komunikaty statusu i informację niezależną od koloru. Ograniczamy ruch dla
  `prefers-reduced-motion`.
- Podstawowa nawigacja i formularze działają klawiaturą. Ważne cele dotykowe
  mają co najmniej 44 px wysokości.

## Źródła prawdy

`frontend/src/design/styles.css` jest źródłem aktualnych tokenów i breakpointów;
komponenty i zachowanie opisuje kod w `frontend/src/`. `mockups/` i
`FRONTEND_REIMPLEMENTATION_PLAN.md` są materiałem referencyjnym, a stary audyt
w `docs/frontend-audit-2026-10-04/` pozostaje zapisem stanu przed zmianą.
