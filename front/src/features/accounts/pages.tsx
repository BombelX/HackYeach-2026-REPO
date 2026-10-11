import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { useTask } from "../../app/hooks";
import {
  ErrorNotice,
  Icon,
  Loading,
  PageTitle,
  Status,
} from "../../design/components";
import {
  accountOptions,
  api,
  historyOptions,
  queryClient,
  type Transaction,
} from "../../services/api";
import { accountNumber, date, money } from "../../services/validation";

function Ledger({ items }: { items: Transaction[] }) {
  return (
    <ul className="ledger">
      {items.map((item) => (
        <li key={item.id}>
          <span
            className={
              "ledger-icon " + (item.amount_grosz > 0 ? "incoming-icon" : "")
            }
          >
            <Icon
              name={item.amount_grosz > 0 ? "transfer" : "history"}
              size={18}
            />
          </span>
          <div className="ledger-info">
            <strong>{item.recipient}</strong>
            <span>{item.title}</span>
            <small>{date(item.created)} · Zrealizowany</small>
          </div>
          <strong className={item.amount_grosz > 0 ? "incoming" : "outgoing"}>
            {item.amount_grosz > 0 ? "+" : "−"}
            {money(Math.abs(item.amount_grosz))}
          </strong>
        </li>
      ))}
    </ul>
  );
}

export function DashboardPage() {
  const account = useQuery(accountOptions);
  const history = useQuery(historyOptions({ offset: 0 }));
  const task = useTask();
  const [copied, setCopied] = useState(false);
  if (account.isPending) return <Loading />;
  if (!account.data)
    return (
      <>
        <ErrorNotice error={account.error} />
        <button
          className="button button-secondary"
          onClick={() => void account.refetch()}
        >
          Pobierz konto ponownie
        </button>
      </>
    );
  const data = account.data;
  const net = data.incoming_grosz - data.outgoing_grosz;
  const total = data.incoming_grosz + data.outgoing_grosz;
  const inflowShare = total
    ? Math.round((data.incoming_grosz / total) * 100)
    : 50;
  const monthMessage = !total
    ? "W tym miesiącu nie ma jeszcze operacji."
    : net > 0
      ? `Wpływy przewyższyły wydatki o ${money(net)}.`
      : net < 0
        ? `Wydatki przewyższyły wpływy o ${money(Math.abs(net))}.`
        : "Wpływy i wydatki są równe.";
  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PRZEGLĄD KONTA</p>
          <PageTitle
            title="Dzień dobry"
            intro="Oto najważniejsze informacje o Twoich finansach."
          />
        </div>
        <span className="demo-chip">Środowisko demo</span>
      </div>
      <section className="account-overview" aria-labelledby="account-title">
        <div className="account-topline">
          <div>
            <p className="account-eyebrow">RACHUNEK OSOBISTY</p>
            <h2 id="account-title">Konto główne</h2>
          </div>
          <span className="account-kind">PLN</span>
        </div>
        <p className="account-nrb">
          {accountNumber(data.number)}{" "}
          <button
            className="copy-button"
            aria-label="Kopiuj numer rachunku"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(data.number);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 2200);
              } catch {
                setCopied(false);
              }
            }}
          >
            <Icon name="copy" size={17} />
          </button>
        </p>
        <p className="balance-label">Dostępne środki</p>
        <strong className="balance">{money(data.balance_grosz)}</strong>
        <div className="account-actions">
          <Link to="/app/transfers/new" className="button button-primary">
            <Icon name="transfer" /> Nowy przelew{" "}
            <Icon name="arrow" size={17} />
          </Link>
          <Link to="/app/history" className="button button-secondary">
            Historia operacji
          </Link>
        </div>
        <p className="copy-status" role="status" aria-live="polite">
          {copied ? "Numer rachunku skopiowano." : ""}
        </p>
      </section>
      <section className="month-summary" aria-labelledby="month-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">MIESIĘCZNE ZESTAWIENIE</p>
            <h2 id="month-title">Wpływy i wydatki</h2>
          </div>
          <time dateTime={data.month}>{data.month}</time>
        </div>
        <div className="month-stat-row">
          <div>
            <span>Wpływy</span>
            <strong className="incoming">{money(data.incoming_grosz)}</strong>
          </div>
          <div>
            <span>Wydatki</span>
            <strong>{money(data.outgoing_grosz)}</strong>
          </div>
        </div>
        <div
          className="balance-bar"
          role="img"
          aria-label={`Udział wpływów ${inflowShare} procent, wydatków ${100 - inflowShare} procent`}
        >
          <span style={{ width: `${inflowShare}%` }} />
          <i style={{ width: `${100 - inflowShare}%` }} />
        </div>
        <p className="month-message">{monthMessage}</p>
      </section>
      <div className="dashboard-details">
        <section className="recent-activity">
          <div className="section-heading">
            <div>
              <p className="eyebrow">TWOJE KONTO</p>
              <h2>Ostatnie operacje</h2>
            </div>
            <Link to="/app/history" className="text-link">
              Cała historia <Icon name="arrow" size={16} />
            </Link>
          </div>
          {history.isPending ? (
            <Loading />
          ) : history.error ? (
            <>
              <ErrorNotice error={history.error} />
              <button
                className="button button-secondary"
                onClick={() => void history.refetch()}
              >
                Spróbuj ponownie
              </button>
            </>
          ) : history.data?.items.length ? (
            <Ledger items={history.data.items.slice(0, 5)} />
          ) : (
            <Status>
              Nie ma jeszcze operacji. Zrealizowane przelewy pojawią się tutaj.
            </Status>
          )}
        </section>
        <section className="account-details">
          <p className="eyebrow">INFORMACJE</p>
          <h2>Dane rachunku</h2>
          <dl className="summary-list">
            <div>
              <dt>Właściciel</dt>
              <dd>{data.name}</dd>
            </div>
            <div>
              <dt>Waluta</dt>
              <dd>Polski złoty · PLN</dd>
            </div>
            <div>
              <dt>Urządzenie</dt>
              <dd>
                {data.trusted_device
                  ? "Zapamiętane na 30 dni"
                  : "Nie zapamiętane"}
              </dd>
            </div>
          </dl>
          {data.trusted_device && (
            <button
              className="text-link"
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  await api("/bank/device", "DELETE");
                  await queryClient.invalidateQueries({
                    queryKey: ["account"],
                  });
                })
              }
            >
              Cofnij zaufanie urządzeniu
            </button>
          )}
          <ErrorNotice error={task.error} />
          <p className="disclaimer">
            Dane przykładowe. Bank24 nie realizuje prawdziwych płatności.
          </p>
        </section>
      </div>
    </div>
  );
}

function HistoryTable({ items }: { items: Transaction[] }) {
  return (
    <div className="history-table-wrap">
      <table className="history-table">
        <thead>
          <tr>
            <th scope="col">Data</th>
            <th scope="col">Odbiorca</th>
            <th scope="col">Tytuł</th>
            <th scope="col" className="numeric">
              Kwota
            </th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td data-label="Data">{date(item.created)}</td>
              <td data-label="Odbiorca">
                <strong>{item.recipient}</strong>
              </td>
              <td data-label="Tytuł">{item.title}</td>
              <td
                data-label="Kwota"
                className={`numeric ${item.amount_grosz > 0 ? "incoming" : "outgoing"}`}
              >
                {item.amount_grosz > 0 ? "+" : "−"}
                {money(Math.abs(item.amount_grosz))}
              </td>
              <td data-label="Status">
                <span className="transaction-status">Zrealizowany</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const search = params.get("q") || "";
  const direction = (params.get("direction") || "all") as
    "all" | "incoming" | "outgoing";
  const query = useQuery(historyOptions({ offset, search, direction }));
  const change = (values: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(values).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key),
    );
    setParams(next, { replace: true });
  };
  const pages = query.data
    ? Math.max(1, Math.ceil(query.data.total / query.data.limit))
    : 1;
  const currentPage = Math.floor(offset / 30) + 1;
  return (
    <div className="history-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">RACHUNEK OSOBISTY</p>
          <PageTitle
            title="Historia operacji"
            intro="Znajdź transakcję po nazwie odbiorcy, tytule lub dacie."
          />
        </div>
        <Link className="button button-primary" to="/app/transfers/new">
          <Icon name="transfer" /> Nowy przelew
        </Link>
      </div>
      <section className="history-panel" aria-label="Lista operacji">
        <div className="history-toolbar">
          <label className="search-field" htmlFor="history-search">
            <Icon name="search" />
            <input
              id="history-search"
              type="search"
              value={search}
              onChange={(event) =>
                change({ q: event.target.value, offset: "" })
              }
              placeholder="Odbiorca, tytuł lub data"
            />
            <span className="visually-hidden">
              Wyszukiwanie obejmuje wszystkie strony wyników
            </span>
          </label>
          <div
            className="history-filters"
            role="group"
            aria-label="Rodzaj operacji"
          >
            {(
              [
                ["all", "Wszystkie"],
                ["incoming", "Wpływy"],
                ["outgoing", "Wydatki"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                className="filter"
                aria-pressed={direction === value}
                onClick={() =>
                  change({
                    direction: value === "all" ? "" : value,
                    offset: "",
                  })
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="result-count" role="status" aria-live="polite">
          {query.isPending
            ? "Wyszukiwanie operacji…"
            : query.data
              ? `${query.data.total} ${query.data.total === 1 ? "operacja" : "operacji"}`
              : ""}
        </p>
        {query.isPending ? (
          <Loading />
        ) : query.error ? (
          <>
            <ErrorNotice error={query.error} />
            <button
              className="button button-secondary"
              onClick={() => void query.refetch()}
            >
              Pobierz ponownie
            </button>
          </>
        ) : query.data?.items.length ? (
          <HistoryTable items={query.data.items} />
        ) : (
          <div className="empty-state">
            <span className="empty-icon">
              <Icon name="search" size={22} />
            </span>
            <h2>
              {search || direction !== "all"
                ? "Nie znaleziono operacji"
                : "Brak operacji"}
            </h2>
            <p>
              {search || direction !== "all"
                ? "Zmień kryteria wyszukiwania lub wybierz inny filtr."
                : "Zrealizowane przelewy pojawią się w tym miejscu."}
            </p>
            {(search || direction !== "all") && (
              <button
                className="button button-secondary"
                onClick={() => {
                  setParams({}, { replace: true });
                  window.setTimeout(
                    () => document.getElementById("history-search")?.focus(),
                    0,
                  );
                }}
              >
                Wyczyść filtry
              </button>
            )}
          </div>
        )}
        <div className="pagination">
          <span>{query.data ? `Strona ${currentPage} z ${pages}` : ""}</span>
          <div>
            <button
              className="button button-secondary"
              disabled={!offset || query.isPending}
              onClick={() =>
                change({ offset: String(Math.max(0, offset - 30)) })
              }
            >
              Poprzednia
            </button>
            <button
              className="button button-secondary"
              disabled={
                !query.data ||
                offset + query.data.limit >= query.data.total ||
                query.isPending
              }
              onClick={() => change({ offset: String(offset + 30) })}
            >
              Następna
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
