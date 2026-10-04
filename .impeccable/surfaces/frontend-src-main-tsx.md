---
version: 1
slug: "frontend-src-main-tsx"
primary_target: "frontend/src/main.tsx"
related_targets: ["frontend/src/design/styles.css","frontend/src/layouts/RootLayout.tsx"]
---

# Bank24: implementacja aplikacji

Tryb Operate. Zatwierdzone mockupy są wizualną referencją; ta powierzchnia rozszerza je o React, sesję, trwały przelew i jawnie ograniczoną analizę. Użytkownik zatwierdził realizację planu na branchu backend. Kamera pozostaje opcjonalna.

## Direction contract

THESIS: Zadanie bankowe ma pierwszeństwo; trwały wynik serwera zastępuje lokalną symulację. Zachować zatwierdzoną profesjonalną identyfikację i przestronność.

OWN-WORLD: Jasny fintech z białymi obszarami zadania, chłodnym płótnem, granatem #152b4b, ciemnym teal #08786a i miętą #67e8c5 wyłącznie na rachunku. IBM Plex Sans, autorski otwarty znak B i krzywe Bank24. Cienkie ramy, promienie 12–16, czytelne natywne kontrolki.

STORY: Kod uczestnika i zgody prowadzą do logowania oraz kodu; rachunek do ręcznie przygotowanego przelewu, trwałego podsumowania i serwerowego sprawdzenia. Jawny brak oceny nie sugeruje bezpieczeństwa. Można edytować, anulować, zgłosić presję, odzyskać wynik i wrócić z pomocy.

FIRST VIEWPORT: Nowsze mockupy finalne mają pierwszeństwo nad wcześniejszym briefem: zadanie lub formularz jest po lewej, a kamera po prawej na desktopie. Bankowe zadanie ma szerszą kolumnę, panel kamery 286 px. Maksimum 1380 px, pola 56 px. Na telefonie zadanie pierwsze, kamera zwinięta. Podgląd ma oddzielny wiersz podpisu; pomiary startują zwinięte i nie pokazują przykładowych liczb.

FORM: Code-led extension zatwierdzonych mockupów. Seed key: user-confirmed-bank24-light, zachowany z powierzchni mockups/index.html. Memorable interaction: aktualna wersja podsumowania odzyskana po odświeżeniu i jeden wynik mimo utraty odpowiedzi potwierdzenia.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
