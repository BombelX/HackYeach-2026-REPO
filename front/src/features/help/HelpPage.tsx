import { Link, useNavigate, useSearchParams } from "react-router";
import { useTask } from "../../app/hooks";
import { Bank24Logo, ErrorNotice, PageTitle } from "../../design/components";
import { api, queryClient } from "../../services/api";
import { stopCamera } from "../camera/store";
import { configureTelemetry } from "../telemetry/collector";
import { clearAuthDraft } from "../auth/pages";
import { clearTransferDraft } from "../transfers/pages";

export function HelpPage() {
  const [params] = useSearchParams();
  const target = params.get("return") || "/";
  const back =
    /^\/(app(?:\/|$)|login$|verify-login$)/.test(target) &&
    !target.startsWith("//")
      ? target
      : "/";
  const task = useTask();
  const navigate = useNavigate();
  const canWithdraw = back.startsWith("/app");
  return (
    <div className="help-shell">
      <a className="skip-link" href="#main">
        Przejdź do treści
      </a>
      <header className="public-header">
        <Link to="/" aria-label="Bank24 — strona główna">
          <Bank24Logo />
        </Link>
        <Link className="button button-secondary" to="/login">
          Zaloguj się
        </Link>
      </header>
      <main className="help-main" id="main" tabIndex={-1}>
        <Link to={back} className="back-link" aria-label="Wróć">
          ← Wróć
        </Link>
        <PageTitle
          title="Centrum pomocy"
          intro="Wskazówki dotyczące korzystania z demonstracji Bank24."
        />
        <div className="help-topics">
          <details open>
            <summary>Logowanie i kody</summary>
            <p>
              Wpisz login i hasło konta demonstracyjnego, a następnie potwierdź
              logowanie osobnym kodem. W trybie demo kod jest pokazany na
              ekranie, a SMS nie jest wysyłany.
            </p>
            <p>
              Jeśli kod wygaśnie, możesz zamówić kolejny. Po pięciu błędnych
              próbach logowanie zostaje czasowo zablokowane.
            </p>
          </details>
          <details>
            <summary>Przelew i jego potwierdzenie</summary>
            <p>
              Porównaj nazwę odbiorcy, cały numer rachunku, tytuł i kwotę z
              dokumentem. Wróć do edycji, jeśli coś się nie zgadza. Kod dotyczy
              wyłącznie danych pokazanych na podsumowaniu.
            </p>
            <p>
              Jeśli połączenie przerwie się podczas potwierdzania, sprawdź
              status tej samej operacji. Nie twórz w zamian drugiego przelewu.
            </p>
          </details>
          <details>
            <summary>Sprawdzenie SafeTransfer</summary>
            <p>
              To demonstracja przepływu i interfejsu. Model oceny ryzyka nie
              jest zwalidowany i może nie zwrócić wyniku. Brak oceny nie
              oznacza, że operacja jest bezpieczna ani niebezpieczna.
            </p>
          </details>
          <details>
            <summary>Kamera i opcjonalne pomiary</summary>
            <p>
              Kamera i telemetria są niezależne, opcjonalne uprawnienia. Nie
              wpływają na dostęp do konta ani przelewów. Kamera przesyła obraz
              do lokalnego serwera analizy i nie rejestruje dźwięku; możesz ją
              wyłączyć w każdej chwili.
            </p>
            <p>
              Wykrycie twarzy nie potwierdza tożsamości. Estymowany puls nie
              jest pomiarem medycznym.
            </p>
          </details>
          <details>
            <summary>Dane demonstracyjne</summary>
            <p>
              Konta, historia i przelewy są fikcyjne. Bank24 nie realizuje
              prawdziwych płatności i nie ma infolinii do obsługi rzeczywistych
              rachunków.
            </p>
          </details>
        </div>
        {canWithdraw && (
          <section className="withdraw-section">
            <h2>Opcjonalne dane tej sesji</h2>
            <p>
              Możesz usunąć metadane użycia, wyłączyć kamerę i skasować
              odpowiedzi ankietowe. Fikcyjna historia konta pozostanie spójna z
              saldem.
            </p>
            <button
              className="button button-secondary"
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  stopCamera();
                  configureTelemetry();
                  await api("/session/withdraw", "POST", {});
                  clearAuthDraft();
                  clearTransferDraft();
                  queryClient.clear();
                  navigate("/", { replace: true });
                })
              }
            >
              {task.busy ? "Usuwamy dane…" : "Usuń dane opcjonalne"}
            </button>
          </section>
        )}
        <ErrorNotice error={task.error} />
        <Link className="button button-primary" to={back}>
          Wróć do Bank24
        </Link>
      </main>
      <footer className="site-footer">
        <span>Bank24 · środowisko demonstracyjne</span>
        <span>Fikcyjne dane i środki</span>
      </footer>
    </div>
  );
}
