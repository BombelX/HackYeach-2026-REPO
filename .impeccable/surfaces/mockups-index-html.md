---
version: 1
slug: "mockups-index-html"
primary_target: "mockups/index.html"
related_targets: ["mockups/styles.css","mockups/app.js"]
---

# Bank24: klikalny prototyp

Tryb: Operate. Zakres: dziesięć widoków bankowego przepływu w `mockups/index.html`, przykładowe dane, lokalny podgląd kamery opcjonalny; identyfikacja w `mockups/brand.html`. Istniejące API i frontend diagnostyczny pozostają osobnymi elementami projektu.

## Direction contract

THESIS: Bankowe zadanie ma pierwszeństwo. Formularz i spokojny, czytelny podgląd sąsiadują ze sobą; szczegóły pomiarów rozwijają się na życzenie.

OWN-WORLD: Profesjonalny jasny fintech: białe powierzchnie na chłodnym tle (#f7f9fc), granatowe teksty, główne przyciski i rachunek (#152b4b), ciemny teal (#08786a) w logo i linkach oraz mięta (#67e8c5) jako akcent na rachunku. IBM Plex Sans. Autorski znak B z otwartych obiegów i logotyp Bank24 bez powtórzonego 24. Obramowanie wyznacza obszar logowania i kamery, a przejrzysty pulpit zawiera podsumowanie miesiąca, listę operacji i dane rachunku. Bursztyn, czerwień i zieleń mają odrębne znaczenia. To kolejna iteracja potwierdzonego jasnego kierunku, na prośbę o profesjonalny wygląd i więcej użytecznej treści.

STORY: Użytkownik loguje się, wpisuje kod, przegląda konto, przygotowuje fikcyjny przelew, sprawdza dane i potwierdza kodem albo ogląda scenariusz ostrzeżenia. Może wrócić do edycji lub anulować, a wynik symulacji aktualizuje saldo i historię. Historia pozwala wyszukać odbiorcę, tytuł lub datę, pokazuje status i stan pustych wyników. Pomoc pozwala wrócić do poprzedniego widoku. Zwijane menu prototypu umożliwia wejście bezpośrednio do głównych ekranów oraz jawny wybór zwykłego przelewu lub interwencji.

FIRST VIEWPORT: Na desktopie kamera zajmuje lewą połowę obszaru roboczego, formularz prawą. Logowanie, checkbox i główna akcja są widoczne bez szukania. Po logowaniu panel kamery jest węższy, a konto i przelew zajmują główną przestrzeń. Poniżej 1024 px formularz jest pierwszy także w kolejności klawiatury, kamera ma zwijany podgląd. Formularz auth ma do 520 px, pola 56 px; układ desktop ma maksimum 1320 px i odstęp 40 px. Kamera oraz logowanie zaczynają się na jednej linii. Na telefonie formularz pozostaje pierwszy, pełny numer rachunku mieści się w polu.

FORM: Kierunek i układ potwierdzone przez użytkownika; seed key `user-confirmed-bank24-light`. Prototyp HTML/CSS/JS rozwija istniejący statyczny sposób prezentacji. Sygnatura: rozwijany panel pomiarów pod kamerą, dostępny w całym przepływie.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
