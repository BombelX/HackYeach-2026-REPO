# Weryfikacja — 11 października 2026

## Wyniki lokalne

Środowisko: Windows, Python 3.13, Node.js 24.13.1, zainstalowany Google Chrome.

| Sprawdzenie | Wynik |
| --- | --- |
| Backend: unittest, łącznie bank, profile kamery, fuzja i worker | 31/31 OK |
| Frontend: Vitest | 3/3 OK |
| Frontend: Playwright, pełna końcowa seria | 10/10 OK, 42,6 s |
| Bank: TypeScript + Vite production build | OK |
| Kolektor: Vite production build | OK |
| Kolektor: strona, API health, produkcyjne JS/CSS | OK |
| Kolektor: nieznany endpoint API | HTTP 404 |
| npm ci / audyt zależności obu frontendów | 0 zgłoszonych podatności |
| Git: wykluczenie baz, nagrań, sekretów i danych sesji | sprawdzona lista plików w indeksie |
| Modele w Git LFS | 153 pliki |

Testy przeglądarkowe obejmują przelewy, błędny OTP, ochronę przed podwójnym
obciążeniem, historię, utratę odpowiedzi sieciowej, kontekst pomocy, dostępność
axe, szerokości 320–1920 px oraz anulowanie i zamykanie strumienia kamery.
Kamera w testach używa syntetycznego obrazu; worker działa z `--no-analysis`.
Pobieranie Chromium kończyło się timeoutem, dlatego lokalnie użyto
`PLAYWRIGHT_CHANNEL=chrome`. Domyślny workflow CI używa Chromium Playwright.

## Naprawione problemy

- Brak `scikit-learn` w zależnościach serwera blokował import modelu fuzji.
- Niedomknięte dodatkowe połączenia SQLite blokowały sprzątanie testów na Windows.
- Kolektor szukał zbudowanego UI w `web/dist`, choć aplikacja jest w `front/`.
- Prefiks i port dev kolektora nie pasowały do samodzielnego uruchomienia;
  frontend działa teraz pod `/`, z API `/api` i portem developerskim 5174.
- Fallback SPA kolektora zwracał HTML dla nieznanych adresów API; teraz zwraca
  404 i ogranicza odczyt plików do katalogu buildu.
- Konfiguracja Playwright wskazywała pliki serwerów sprzed konsolidacji i
  wymagała konkretnej ścieżki do interpretera Windows.
- Spóźniona odpowiedź 401 po jawnym wylogowaniu mogła nadpisać przekierowanie
  na stronę główną; stan wylogowania chroni teraz ten przepływ.
- Powtórzony efekt React StrictMode mógł uruchomić kamerę dwa razy;
  uruchamianie jest teraz idempotentne dla aktywnego lub startującego strumienia.
- Cztery pętle wysyłania klatek nie miały ograniczenia tempa; dzielą teraz
  budżet około 30 klatek/s.
- Starsze testy kamery oczekiwały ręcznego startu w banku i landmarków przy
  wyłączonej analizie; zaktualizowano je do obecnego zachowania, zachowując
  sprawdzanie liczby strumieni, transportu obrazu i zwalniania kamery.

## Zakres

Nie uruchamiano pełnego treningu na zewnętrznych datasetach, pomiarów z fizycznej
kamery ani inferencji GPU. Wyniki modeli pozostają eksperymentalne. Workflow
GitHub Actions został dodany, ale jego wykonanie nastąpi po publikacji repo.
Ostrzeżenia aiohttp o tekstowych kluczach aplikacji i ostrzeżenie biblioteki
TestClient nie blokują testów. Kod archiwalny i zewnętrzny zachowano wraz z
oryginalnymi licencjami; nie nadano nowej licencji całemu projektowi.
