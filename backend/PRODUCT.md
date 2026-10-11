# Bank24 / SafeTransfer

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Osoba testująca demonstrację z fikcyjnym kontem bankowym. Jury i zespół
projektowy oceniają czytelność interfejsu oraz przepływu.

## Product Purpose

Pokazać, jak interfejs może wspierać uważne logowanie i podejmowanie decyzji
podczas przelewu. Modele oceny ryzyka nie są zwalidowane; demonstracja nie
składa obietnic wykrywania oszustw.

## Operating Context

Wejście do produktu to publiczny landing → login i hasło → kod logowania →
dashboard. Strona z kodem uczestnika i wymagana zgoda przed logowaniem zostały
usunięte. Telemetria i kamera są niezależnymi opcjami. Zaimplementowana
reimplementacja jest opisana w `FRONTEND_REIMPLEMENTATION_PLAN.md`.

Frontend React i `bank24_server.py` tworzą lokalną demonstrację logowania,
rachunku, przelewu, historii, pomocy i opinii. Fikcyjne rachunki i operacje są
zapisywane lokalnie. Ocena ryzyka pozostaje jawnie niedostępna (`null`), bo nie
ma zwalidowanego modelu.

## Capabilities and Constraints

Mockupy użytkownika wyznaczają kierunek kompozycji, hierarchię, kolorystykę i
gęstość paneli. Kamera pojawia się jako moduł opcjonalny na ekranie nowego
przelewu; globalny status w nagłówku zapewnia dostęp do akcji Wyłącz.

Demonstracja używa jawnie fikcyjnych danych. Kamera wymaga osobnej zgody w panelu: po jej potwierdzeniu przeglądarka przesyła obraz bez dźwięku przez WebRTC do lokalnego serwera analizy i odbiera aktualne estymacje. Nie zapisujemy nagrań ani dźwięku; pomiary są eksperymentalne i nie potwierdzają tożsamości ani ryzyka.

## Brand Commitments

Bank24 to fikcyjny bank, SafeTransfer to warstwa bezpieczeństwa. Użytkownik wybrał jasny nowoczesny interfejs, a następnie potwierdził jego rozwinięcie w stylu fintech: białe obszary zadań na chłodnym tle, granatowe teksty i główne akcje oraz ciemny teal do linków i zaznaczeń. W kolejnej iteracji użytkownik poprosił o bardziej profesjonalny wygląd, układ, treść i logo. Autorski znak B z otwartych obiegów i logotyp SVG Bank24 stanowią identyfikację banku; mięta pozostaje oszczędnym akcentem na rachunku. Mięta nie oznacza niskiego ryzyka; semantyczne zieleń, bursztyn i czerwień zachowują znaczenia stanu, ostrzeżenia i błędu. Język interfejsu: polski.

## Evidence on Hand

`frontend/README.md` i `BANK24_API.md` opisują uruchomienie oraz wdrożony kontrakt lokalnej aplikacji i kamery. `README.md`, `webrtc_server.py`, `camera_estimator.py` i `static/webrtc.html` opisują worker WebRTC. `mockups/` oraz `FRONTEND_IMPLEMENTATION_PLAN.md` są materiałem referencyjnym i planem; bieżąca implementacja React/API jest źródłem prawdy o działających przepływach.

## Product Principles

- Użytkownik rozumie ostrzeżenie i ma dostępny bezpieczny dalszy krok.
- Brak danych nie oznacza niskiego ryzyka.
- Kamera jest opcjonalna; jej brak nie blokuje przepływu.
- Etykieta scenariusza nie jest przewidywaniem modelu.
- Nie używamy rzeczywistych danych bankowych ani deklaracji skuteczności bez dowodów.
