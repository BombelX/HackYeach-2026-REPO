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
            <small>{date(item.created)} · Completed</small>
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
          Reload account
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
    ? "No transactions this month yet."
    : net > 0
      ? `Income exceeded spending by ${money(net)}.`
      : net < 0
        ? `Spending exceeded income by ${money(Math.abs(net))}.`
        : "Income and spending are equal.";
  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">ACCOUNT OVERVIEW</p>
          <PageTitle
            title="Hello"
            intro="Here are the key details about your finances."
          />
        </div>
        <span className="demo-chip">Demo environment</span>
      </div>
      <section className="account-overview" aria-labelledby="account-title">
        <div className="account-topline">
          <div>
            <p className="account-eyebrow">PERSONAL ACCOUNT</p>
            <h2 id="account-title">Main account</h2>
          </div>
          <span className="account-kind">PLN</span>
        </div>
        <p className="account-nrb">
          {accountNumber(data.number)}{" "}
          <button
            className="copy-button"
            aria-label="Copy account number"
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
        <p className="balance-label">Available funds</p>
        <strong className="balance">{money(data.balance_grosz)}</strong>
        <div className="account-actions">
          <Link to="/app/transfers/new" className="button button-primary">
            <Icon name="transfer" /> New transfer{" "}
            <Icon name="arrow" size={17} />
          </Link>
          <Link to="/app/history" className="button button-secondary">
            Transaction history
          </Link>
        </div>
        <p className="copy-status" role="status" aria-live="polite">
          {copied ? "Account number copied." : ""}
        </p>
      </section>
      <section className="month-summary" aria-labelledby="month-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">MONTHLY SUMMARY</p>
            <h2 id="month-title">Income and spending</h2>
          </div>
          <time dateTime={data.month}>{data.month}</time>
        </div>
        <div className="month-stat-row">
          <div>
            <span>Income</span>
            <strong className="incoming">{money(data.incoming_grosz)}</strong>
          </div>
          <div>
            <span>Spending</span>
            <strong>{money(data.outgoing_grosz)}</strong>
          </div>
        </div>
        <div
          className="balance-bar"
          role="img"
          aria-label={`Income share ${inflowShare} percent, spending ${100 - inflowShare} percent`}
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
              <p className="eyebrow">YOUR ACCOUNT</p>
              <h2>Recent transactions</h2>
            </div>
            <Link to="/app/history" className="text-link">
              Full history <Icon name="arrow" size={16} />
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
                Try again
              </button>
            </>
          ) : history.data?.items.length ? (
            <Ledger items={history.data.items.slice(0, 5)} />
          ) : (
            <Status>
              No transactions yet. Completed transfers will appear here.
            </Status>
          )}
        </section>
        <section className="account-details">
          <p className="eyebrow">INFORMATION</p>
          <h2>Account details</h2>
          <dl className="summary-list">
            <div>
              <dt>Owner</dt>
              <dd>{data.name}</dd>
            </div>
            <div>
              <dt>Currency</dt>
              <dd>Polish zloty · PLN</dd>
            </div>
            <div>
              <dt>Device</dt>
              <dd>
                {data.trusted_device
                  ? "Remembered for 30 days"
                  : "Not remembered"}
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
              Revoke device trust
            </button>
          )}
          <ErrorNotice error={task.error} />
          <p className="disclaimer">
            Sample data. Bank24 does not process real payments.
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
            <th scope="col">Date</th>
            <th scope="col">Recipient</th>
            <th scope="col">Reference</th>
            <th scope="col" className="numeric">
              Amount
            </th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td data-label="Date">{date(item.created)}</td>
              <td data-label="Recipient">
                <strong>{item.recipient}</strong>
              </td>
              <td data-label="Reference">{item.title}</td>
              <td
                data-label="Amount"
                className={`numeric ${item.amount_grosz > 0 ? "incoming" : "outgoing"}`}
              >
                {item.amount_grosz > 0 ? "+" : "−"}
                {money(Math.abs(item.amount_grosz))}
              </td>
              <td data-label="Status">
                <span className="transaction-status">Completed</span>
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
          <p className="eyebrow">PERSONAL ACCOUNT</p>
          <PageTitle
            title="Transaction history"
            intro="Find a transaction by recipient, reference or date."
          />
        </div>
        <Link className="button button-primary" to="/app/transfers/new">
          <Icon name="transfer" /> New transfer
        </Link>
      </div>
      <section className="history-panel" aria-label="Transaction list">
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
              placeholder="Recipient, reference or date"
            />
            <span className="visually-hidden">
              Search covers all result pages
            </span>
          </label>
          <div
            className="history-filters"
            role="group"
            aria-label="Transaction type"
          >
            {(
              [
                ["all", "All"],
                ["incoming", "Income"],
                ["outgoing", "Spending"],
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
            ? "Searching transactions…"
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
              Reload
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
                ? "No matching transactions"
                : "No transactions"}
            </h2>
            <p>
              {search || direction !== "all"
                ? "Change your search or choose another filter."
                : "Completed transfers will appear here."}
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
                Clear filters
              </button>
            )}
          </div>
        )}
        <div className="pagination">
          <span>{query.data ? `Page ${currentPage} of ${pages}` : ""}</span>
          <div>
            <button
              className="button button-secondary"
              disabled={!offset || query.isPending}
              onClick={() =>
                change({ offset: String(Math.max(0, offset - 30)) })
              }
            >
              Previous
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
              Next
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
