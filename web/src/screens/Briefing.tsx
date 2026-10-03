import { useProtocol } from "../protocol/ProtocolContext";
import type { Condition } from "../types";

const COPY: Record<Condition, { title: string; body: string }> = {
  calm_1: {
    title: "Sesja spokojna 1",
    body: "Zaloguj się na swoje konto i opłać fakturę z pulpitu. Wszystkie dane przelewu przepisz ręcznie z faktury. Nie spiesz się.",
  },
  calm_2: {
    title: "Sesja spokojna 2",
    body: "Druga spokojna sesja: znowu swoje konto i faktura, dane przepisujesz ręcznie. Chcemy zobaczyć Twój zwykły rytm.",
  },
  dictation: {
    title: "Przelew z telefonu",
    body: "Zaloguj się na swoje konto. Po zalogowaniu zadzwoni księgowa i spokojnie podyktuje dane do przelewu. Włącz dźwięk i wpisuj na bieżąco.",
  },
  scam: {
    title: "Telefon z banku",
    body: "Zaloguj się jak zwykle. Po zalogowaniu może zadzwonić pracownik banku. Traktuj tę rozmowę tak, jakby była prawdziwa, i zrób to, o co prosi. Włącz dźwięk.",
  },
  intruder: {
    title: "Przejęcie konta",
    body: "Przez 20 sekund zobaczysz dane z „wycieku”. Zaloguj się nimi na cudze konto. Od zalogowania masz 90 sekund, żeby przelać jak najwięcej na konto z Twojej kartki, zanim właściciel się zorientuje. Na hali jest tablica wyników.",
  },
  calm_3: {
    title: "Sesja spokojna na koniec",
    body: "Ostatnia spokojna sesja na Twoim koncie. Znowu opłać fakturę, bez presji.",
  },
};

export function Briefing() {
  const { condition, index, join, beginCondition, error } = useProtocol();
  if (!condition || !join) return null;
  const copy = COPY[condition];
  return (
    <div className="study-shell">
      <div className="study-card">
        <p className="tiny">
          Sesja {index + 1} / {join.condition_order.length}
        </p>
        <h1>{copy.title}</h1>
        <p className="lead">{copy.body}</p>
        {error && <p className="error">{error}</p>}
        <button className="btn accent" onClick={() => void beginCondition()}>
          Otwórz Bank24
        </button>
      </div>
    </div>
  );
}
