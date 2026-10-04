# Bank24: klikalne mockupy

Z katalogu repozytorium uruchom:

```powershell
python -m http.server 5174 --bind 127.0.0.1 --directory mockups
```

Otwórz `http://localhost:5174`. Można też otworzyć `index.html` bezpośrednio, ale lokalny serwer daje najbardziej przewidywalną obsługę kamery.

Ekrany: logowanie, symulowany SMS, pulpit, formularz przelewu i ostrzeżenie. Dodatkowo podsumowanie, potwierdzenie przelewu kodem demo, wynik, historia i pomoc. Zwijane menu „Ekrany prototypu” pozwala wejść do każdego głównego ekranu bez przechodzenia całego logowania oraz wybrać scenariusz: zwykły przelew (domyślny) lub ostrzeżenie SafeTransfer.

Przycisk „Uzupełnij dane demo” wypełnia wyłącznie logowanie. Kamera pozostaje po lewej na desktopie; poniżej 1024 px formularz jest pierwszy, a kamera ma zwijany podgląd.

Konto demonstracyjne: `anna.demo` / `bank24`; kod: `1234`.

W formularzu dane wpisuje się ręcznie z widocznej fikcyjnej faktury. Walidacja rachunku sprawdza 26 cyfr, bez rzeczywistej walidacji banku lub sumy kontrolnej. Zwykły przelew po podsumowaniu prowadzi do kodu; scenariusz interwencji wyświetla przygotowane ostrzeżenie. Nie jest to wynik działającej analizy antyfraudowej. Odpowiedź „Nie” prowadzi do potwierdzenia kodem 1234; odpowiedź „Tak” pozwala anulować przelew. Cofnięcie do edycji zachowuje dane. Potwierdzenie aktualizuje saldo i historię w pamięci demonstracji; wylogowanie i odświeżenie zerują tę symulację.

Logo, warianty i zasady użycia: [brand.html](brand.html). Plan docelowego frontendu React oraz kryteria dziesięciu heurystyk Nielsena: [FRONTEND_IMPLEMENTATION_PLAN.md](../FRONTEND_IMPLEMENTATION_PLAN.md).

Wszystkie salda, transakcje, pomiary i wyjaśnienia ryzyka są przykładowe. Kliknięcie „Włącz kamerę” wyświetla zgodę na prawdziwy lokalny podgląd. Ten podgląd nie jest nagrywany, wysyłany ani analizowany; panel parametrów nadal pokazuje przykładowe wartości. Checkbox urządzenia zachowuje stan wyłącznie w pamięci prototypu. Nie zapisuje hasła ani tokenu urządzenia.

Artefakt jest samodzielnym HTML/CSS/JS i nie zmienia istniejącego serwera `aiohttp` ani jego demo `static/webrtc.html`.

## Zasoby

IBM Plex Sans: fonty pobrane z oficjalnego Google Fonts API i hostowane lokalnie w `assets/`. Licencja SIL Open Font License znajduje się w `assets/OFL.txt`.

Źródła: https://fonts.google.com/specimen/IBM+Plex+Sans oraz https://github.com/google/fonts/tree/main/ofl/ibmplexsans.

Ikony są prostą, wspólną rodziną geometrii SVG, zdefiniowaną w `app.js`. Prototyp nie korzysta z zewnętrznych skryptów, fotografii ani żądań do usług bankowych.

Monogram B z dwóch otwartych obiegów zaprojektowano dla Bank24 jako geometrię wektorową. Litery logotypu są krzywymi pochodzącymi z IBM Plex Sans (SIL OFL); warianty w `assets/bank24-*.svg` działają bez fontów.

Profesjonalna iteracja: logotyp Bank24, granatowe akcje, uporządkowane panele, podsumowanie miesiąca wyliczane z operacji demo i dane rachunku. Historia obsługuje wyszukiwanie odbiorcy, tytułu i daty, bez rozróżniania polskich znaków. Brak wyników pozwala wyczyścić zapytanie. Pomoc w stopce zachowuje aktualny kontekst.

Wskazówkę o ochronie haseł i kodów oparto na materiale Ministerstwa Cyfryzacji: https://www.gov.pl/web/cyfryzacja/uwazaj-na-vishing---czyli-oszustwo-z-wykorzystaniem-polaczen-telefonicznych.
