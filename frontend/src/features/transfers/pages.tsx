import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Link,
  useBeforeUnload,
  useBlocker,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router";
import { useTask } from "../../app/hooks";
import {
  ErrorNotice,
  Field,
  Loading,
  PageTitle,
  Steps,
  useErrorFocus,
} from "../../design/components";
import {
  accountOptions,
  api,
  ApiError,
  type Challenge,
  queryClient,
  type Transfer,
  transferOptions,
} from "../../services/api";
import {
  accountNumber,
  date,
  money,
  parseAmount,
  validNrb,
} from "../../services/validation";
import { useCountdown } from "../auth/pages";
import { collect, flushTelemetry } from "../telemetry/collector";

interface Draft {
  recipient: string;
  number: string;
  title: string;
  amount: string;
  id?: string;
  version?: number;
}
let draft: Draft = { recipient: "", number: "", title: "", amount: "" };
let draftDirty = false;
export function clearTransferDraft() {
  draft = { recipient: "", number: "", title: "", amount: "" };
  draftDirty = false;
}
const terminal = (status: string) =>
  ["completed", "cancelled", "held"].includes(status);
export function transferPath(transfer: Transfer) {
  return `/app/transfers/${transfer.id}/${terminal(transfer.status) ? "status" : transfer.status === "ready" ? "confirm" : "review"}`;
}
function Summary({ transfer }: { transfer: Transfer }) {
  return (
    <section className="transfer-details" aria-label="Szczegóły przelewu">
      <h2>Szczegóły przelewu</h2>
      <dl className="summary-list transfer-summary">
        <div>
          <dt>Odbiorca</dt>
          <dd>{transfer.recipient}</dd>
        </div>
        <div>
          <dt>Rachunek odbiorcy</dt>
          <dd>{accountNumber(transfer.number)}</dd>
        </div>
        <div>
          <dt>Tytuł przelewu</dt>
          <dd>{transfer.title}</dd>
        </div>
        <div>
          <dt>Kwota</dt>
          <dd className="summary-amount">{money(transfer.amount_grosz)}</dd>
        </div>
        <div>
          <dt>Opłata</dt>
          <dd>0,00 zł</dd>
        </div>
      </dl>
    </section>
  );
}
function useTransfer() {
  const id = useParams().id!;
  return useQuery({ ...transferOptions(id), staleTime: 0 });
}

export function TransferFormPage() {
  const [params] = useSearchParams();
  const editId = params.get("edit");
  const account = useQuery(accountOptions);
  const edit = useQuery({
    ...transferOptions(editId || ""),
    enabled: !!editId,
    staleTime: 0,
  });
  const [values, setValues] = useState<Draft>({ ...draft });
  const [dirty, setDirty] = useState(draftDirty);
  const task = useTask();
  const navigate = useNavigate();
  useErrorFocus(task.error);
  useEffect(() => {
    if (edit.data && !terminal(edit.data.status)) {
      const transfer = edit.data;
      if (draft.id === transfer.id && draft.version === transfer.version) {
        setValues({ ...draft });
        setDirty(draftDirty);
        return;
      }
      draft = {
        recipient: transfer.recipient,
        number: accountNumber(transfer.number),
        title: transfer.title,
        amount: (transfer.amount_grosz / 100).toFixed(2).replace(".", ","),
        id: transfer.id,
        version: transfer.version,
      };
      setValues({ ...draft });
      draftDirty = false;
      setDirty(false);
    } else if (!editId && draft.id) {
      clearTransferDraft();
      setValues({ ...draft });
      setDirty(false);
    }
  }, [edit.data, editId]);
  const blocker = useBlocker(
    ({ nextLocation }) =>
      dirty &&
      !nextLocation.pathname.startsWith("/app/transfers/") &&
      nextLocation.pathname !== "/help",
  );
  useBeforeUnload((event) => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  function change(field: keyof Draft, value: string) {
    draft = { ...values, [field]: value };
    setValues({ ...draft });
    setDirty(true);
    draftDirty = true;
    collect("input", "transfer", field, value.length);
  }
  if (account.isPending || (editId && edit.isPending)) return <Loading />;
  if (!account.data || edit.error)
    return (
      <>
        <ErrorNotice error={account.error || edit.error} />
        <Link to="/app">Wróć do konta</Link>
      </>
    );
  if (edit.data && terminal(edit.data.status))
    return (
      <>
        <PageTitle title="Operacja jest zakończona" />
        <Link className="primary-button" to={transferPath(edit.data)}>
          Zobacz wynik
        </Link>
      </>
    );
  const invoice = account.data.invoice;
  return (
    <>
      <Steps current={0} />
      <PageTitle
        title={editId ? "Edytuj przelew" : "Nowy przelew"}
        intro="Wpisz dane odbiorcy i porównaj je z fakturą. W kolejnym kroku sprawdzisz podsumowanie."
      />
      {blocker.state === "blocked" && (
        <section className="notice" role="alert">
          <h2>Co zrobić ze szkicem?</h2>
          <p>
            Zachowaj wpisane dane w tej karcie lub odrzuć szkic. Odświeżenie
            usuwa niezapisany szkic.
          </p>
          <div className="actions">
            <button
              className="secondary-button"
              onClick={() => {
                setDirty(false);
                blocker.proceed();
              }}
            >
              Zachowaj i wyjdź
            </button>
            <button
              className="secondary-button"
              onClick={() => {
                clearTransferDraft();
                setValues({ ...draft });
                setDirty(false);
                blocker.proceed();
              }}
            >
              Odrzuć i wyjdź
            </button>
            <button className="text-button" onClick={() => blocker.reset()}>
              Zostań przy przelewie
            </button>
          </div>
        </section>
      )}
      <div className="transfer-workspace">
        <form
          className="transfer-form"
          aria-busy={task.busy}
          onSubmit={(e) => {
            e.preventDefault();
            void task.run(async () => {
              const errors: Record<string, string> = {};
              const amount = parseAmount(values.amount);
              if (values.recipient.trim().length < 2)
                errors.recipient = "Podaj nazwę odbiorcy.";
              if (!validNrb(values.number))
                errors.number =
                  "Sprawdź 26 cyfr numeru rachunku i jego sumę kontrolną.";
              if (!values.title.trim()) errors.title = "Podaj tytuł przelewu.";
              if (amount === null)
                errors.amount = "Podaj dodatnią kwotę, np. 1250,00.";
              else if (amount > account.data!.balance_grosz)
                errors.amount = "Kwota przekracza dostępne środki.";
              if (Object.keys(errors).length)
                throw new ApiError(
                  422,
                  "fields",
                  "Popraw zaznaczone dane.",
                  errors,
                );
              await flushTelemetry();
              const transfer = await api<Transfer>(
                "/bank/transfers" + (editId ? "/" + editId : ""),
                editId ? "PUT" : "POST",
                {
                  recipient: values.recipient,
                  number: values.number,
                  title: values.title,
                  amount_grosz: amount,
                  version: values.version,
                },
              );
              queryClient.setQueryData(["transfer", transfer.id], transfer);
              draft = { ...values, id: transfer.id, version: transfer.version };
              draftDirty = false;
              setDirty(false);
              navigate(`/app/transfers/${transfer.id}/review`);
            });
          }}
        >
          <p className="source-account">
            Z rachunku: Konto osobiste
            <br />
            <strong>{money(account.data.balance_grosz)}</strong> dostępne
          </p>
          <Field
            id="recipient"
            label="Nazwa odbiorcy"
            value={values.recipient}
            onChange={(e) => change("recipient", e.target.value)}
            maxLength={100}
            error={task.fields.recipient}
            autoComplete="off"
            required
          />
          <Field
            id="number"
            label="Numer rachunku odbiorcy"
            value={values.number}
            onChange={(e) => change("number", e.target.value)}
            maxLength={40}
            error={task.fields.number}
            inputMode="numeric"
            autoComplete="off"
            required
            hint="26 cyfr polskiego numeru NRB."
          />
          <Field
            id="title"
            label="Tytuł przelewu"
            value={values.title}
            onChange={(e) => change("title", e.target.value)}
            maxLength={140}
            error={task.fields.title}
            autoComplete="off"
            required
          />
          <Field
            id="amount"
            label="Kwota (PLN)"
            value={values.amount}
            onChange={(e) => change("amount", e.target.value)}
            error={task.fields.amount}
            inputMode="decimal"
            autoComplete="off"
            required
          />
          <ErrorNotice error={task.error} />
          <button className="primary-button" disabled={task.busy}>
            {task.busy ? "Zapisujemy dane…" : "Sprawdź przelew"}
          </button>
          <Link className="text-button" to="/app">
            Wróć do konta
          </Link>
        </form>
        <aside className="invoice" aria-labelledby="invoice-heading">
          <h2 id="invoice-heading">Faktura do zadania</h2>
          <p className="field-hint">Dokument przykładowy · dane fikcyjne</p>
          <dl className="summary-list">
            <div>
              <dt>Numer faktury</dt>
              <dd>{invoice.reference}</dd>
            </div>
            <div>
              <dt>Odbiorca</dt>
              <dd>{invoice.recipient}</dd>
            </div>
            <div>
              <dt>Rachunek</dt>
              <dd>{accountNumber(invoice.number)}</dd>
            </div>
            <div>
              <dt>Do zapłaty</dt>
              <dd>{money(invoice.amount_grosz)}</dd>
            </div>
            <div>
              <dt>Tytuł</dt>
              <dd>{invoice.title}</dd>
            </div>
          </dl>
          <p>
            Wpisz dane ręcznie. Porównaj cały numer rachunku przed
            potwierdzeniem.
          </p>
        </aside>
      </div>
    </>
  );
}

const decisions = new Map<
  string,
  { independent: boolean | null; compared: boolean }
>();
export function ReviewPage() {
  const query = useTransfer();
  const task = useTask();
  const navigate = useNavigate();
  const id = useParams().id!;
  const [decision, setDecision] = useState(
    decisions.get(id) || { independent: null, compared: false },
  );
  function change(next: typeof decision) {
    decisions.set(id, next);
    setDecision(next);
  }
  if (!query.data)
    return (
      <>
        <Loading />
        <ErrorNotice error={query.error} />
      </>
    );
  const transfer = query.data;
  return (
    <>
      <Steps current={1} labels={["Dane przelewu", "Sprawdzenie", "Kod SMS"]} />
      <PageTitle
        title="Sprawdź przelew przed potwierdzeniem"
        intro="Porównaj dane z dokumentem i potwierdź, że decyzja należy do Ciebie."
      />
      <Summary transfer={transfer} />
      <section className="risk-note" aria-labelledby="risk-heading">
        <p className="eyebrow">SAFETRANSFER</p>
        <h2 id="risk-heading">Ocena ryzyka jest niedostępna</h2>
        <p>
          Nie mamy zwalidowanego modelu, który pozwalałby ocenić ryzyko dla tego
          przelewu. Brak wyniku nie oznacza, że operacja jest bezpieczna lub
          niebezpieczna.
        </p>
        <details>
          <summary>Dlaczego nie ma wyniku?</summary>
          <ul>
            {transfer.risk.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </details>
      </section>
      <fieldset>
        <legend>Czy wykonujesz ten przelew z własnej decyzji?</legend>
        <p className="field-hint">
          Jeśli ktoś wywiera presję, żąda pilnego przelewu lub każe ukrywać jego
          cel, wybierz drugą odpowiedź.
        </p>
        <label className="choice-row">
          <input
            type="radio"
            name="independent"
            checked={decision.independent === true}
            onChange={() => change({ ...decision, independent: true })}
          />
          Tak, podejmuję decyzję samodzielnie
        </label>
        <label className="choice-row">
          <input
            type="radio"
            name="independent"
            checked={decision.independent === false}
            onChange={() => change({ ...decision, independent: false })}
          />
          Ktoś wywiera na mnie presję lub mam wątpliwości
        </label>
      </fieldset>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={decision.compared}
          onChange={(e) => change({ ...decision, compared: e.target.checked })}
        />
        Porównałem odbiorcę, rachunek i kwotę z dokumentem.
      </label>
      {decision.independent === false && (
        <p className="notice warning">
          Wstrzymamy tę operację bez obciążenia rachunku. Nie przekazuj nikomu
          kodu potwierdzenia.
        </p>
      )}
      <ErrorNotice error={task.error} />
      <button
        className="primary-button"
        disabled={
          task.busy || decision.independent === null || !decision.compared
        }
        onClick={() =>
          void task.run(async () => {
            const updated = await api<Transfer>(
              `/bank/transfers/${transfer.id}/intervention`,
              "POST",
              { ...decision, version: transfer.version },
            );
            decisions.delete(id);
            if (terminal(updated.status)) clearTransferDraft();
            queryClient.setQueryData(["transfer", id], updated);
            if (updated.status === "ready") {
              try {
                const challenge = await api<Challenge>(
                  `/bank/transfers/${id}/challenge`,
                  "POST",
                  {},
                );
                queryClient.setQueryData(["transfer-challenge", id], challenge);
              } catch {
                // The confirmation screen can safely retry when a code was not issued.
              }
            }
            navigate(transferPath(updated));
          })
        }
      >
        {task.busy
          ? "Zapisujemy decyzję…"
          : decision.independent === false
            ? "Wstrzymaj przelew"
            : "Przejdź do potwierdzenia"}
      </button>
      <div className="actions">
        <Link className="text-button" to={`/app/transfers/new?edit=${id}`}>
          Edytuj dane
        </Link>
        <button
          className="text-button"
          disabled={task.busy}
          onClick={() =>
            void task.run(async () => {
              await api(`/bank/transfers/${id}/cancel`, "POST", {});
              decisions.delete(id);
              clearTransferDraft();
              navigate(`/app/transfers/${id}/status`);
            })
          }
        >
          Anuluj przelew
        </button>
      </div>
    </>
  );
}

export function ConfirmPage() {
  const query = useTransfer();
  const id = useParams().id!;
  const task = useTask();
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const challenge = useQuery({
    queryKey: ["transfer-challenge", id],
    queryFn: () => api<Challenge>(`/bank/transfers/${id}/challenge`),
    staleTime: 0,
  });
  const countdown = useCountdown(challenge.data);
  useErrorFocus(task.error);
  if (!query.data)
    return (
      <>
        <Loading />
        <ErrorNotice error={query.error} />
      </>
    );
  const transfer = query.data;
  const orderCode = () =>
    task.run(async () => {
      const next = await api<Challenge>(
        `/bank/transfers/${id}/challenge`,
        "POST",
        {},
      );
      queryClient.setQueryData(["transfer-challenge", id], next);
      setCode("");
    });
  return (
    <>
      <Steps current={2} />
      <PageTitle
        title="Potwierdź przelew"
        intro="Kod zatwierdzi tylko te dane. Przed jego wpisaniem sprawdź odbiorcę i kwotę."
      />
      <Summary transfer={transfer} />
      {challenge.error &&
        !(
          challenge.error instanceof ApiError &&
          challenge.error.code === "no_challenge"
        ) && <ErrorNotice error={challenge.error} />}
      <ErrorNotice error={task.error} />
      {!challenge.data ? (
        <button
          className="primary-button"
          disabled={task.busy || challenge.isPending}
          onClick={() => void orderCode()}
        >
          {task.busy ? "Zamawiamy kod…" : "Zamów kod potwierdzenia"}
        </button>
      ) : (
        <>
          <form
            aria-busy={task.busy}
            onSubmit={(e) => {
              e.preventDefault();
              void task.run(async () => {
                try {
                  const result = await api<Transfer>(
                    `/bank/transfers/${id}/submit`,
                    "POST",
                    {
                      challenge_id: challenge.data!.challenge_id,
                      code,
                      version: transfer.version,
                    },
                    { "Idempotency-Key": `bank24-${id}-${transfer.version}` },
                  );
                  queryClient.setQueryData(["transfer", id], result);
                  clearTransferDraft();
                  await Promise.all([
                    queryClient.invalidateQueries({ queryKey: ["account"] }),
                    queryClient.invalidateQueries({ queryKey: ["history"] }),
                  ]);
                  navigate(`/app/transfers/${id}/status`, { replace: true });
                } catch (error) {
                  if (
                    error instanceof ApiError &&
                    (error.status === 0 || error.status >= 500)
                  ) {
                    navigate(`/app/transfers/${id}/status?recover=1`, {
                      replace: true,
                    });
                    return;
                  }
                  throw error;
                }
              });
            }}
          >
            <Field
              label="Kod potwierdzenia"
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) =>
                setCode(
                  e.target.value
                    .replace(/\D/g, "")
                    .slice(0, challenge.data?.code_length ?? 6),
                )
              }
              maxLength={challenge.data?.code_length ?? 6}
              className="otp-code"
              required
              error={task.fields.code}
              hint={
                countdown.expires
                  ? `Kod ważny jeszcze ${countdown.expires} s.`
                  : "Kod wygasł. Zamów nowy."
              }
            />
            {challenge.data.demo_mode && (
              <p className="notice">
                Kod testowy: <strong>1234</strong>. SMS nie jest wysyłany.
              </p>
            )}
            <button
              className="primary-button"
              disabled={task.busy || !countdown.expires}
            >
              {task.busy
                ? "Sprawdzamy status przelewu…"
                : `Potwierdź ${money(transfer.amount_grosz)}`}
            </button>
          </form>
          <button
            className="text-button"
            disabled={task.busy || countdown.cooldown > 0}
            onClick={() => void orderCode()}
          >
            {countdown.cooldown
              ? `Nowy kod za ${countdown.cooldown} s`
              : "Zamów nowy kod"}
          </button>
        </>
      )}
      <div className="actions">
        <Link className="text-button" to={`/app/transfers/new?edit=${id}`}>
          Edytuj dane przelewu
        </Link>
        <button
          className="text-button"
          disabled={task.busy}
          onClick={() =>
            void task.run(async () => {
              await api(`/bank/transfers/${id}/cancel`, "POST", {});
              clearTransferDraft();
              navigate(`/app/transfers/${id}/status`);
            })
          }
        >
          Anuluj przelew
        </button>
      </div>
    </>
  );
}

export function StatusPage() {
  const id = useParams().id!;
  const [params] = useSearchParams();
  const recovering = params.get("recover") === "1";
  const query = useQuery({
    ...transferOptions(id),
    staleTime: 0,
    refetchInterval: recovering
      ? (current) =>
          current.state.data && terminal(current.state.data.status)
            ? false
            : 2000
      : false,
  });
  const transfer = query.data;
  const completed = transfer?.status === "completed";
  const held = transfer?.status === "held";
  const cancelled = transfer?.status === "cancelled";
  return (
    <>
      <PageTitle
        title={
          completed
            ? "Przelew zrealizowany"
            : held
              ? "Przelew wstrzymany"
              : cancelled
                ? "Przelew anulowany"
                : "Sprawdzamy status przelewu"
        }
        intro={
          completed
            ? "Saldo i historia zostały zaktualizowane na serwerze."
            : held
              ? "Rachunek nie został obciążony. Nie przekazuj nikomu kodów ani danych logowania."
              : cancelled
                ? "Nie obciążyliśmy rachunku."
                : "Sprawdzamy tę samą operację. Nie przygotowuj drugiego przelewu."
        }
      />
      {query.isPending && <Loading />}
      <ErrorNotice error={query.error} />
      {query.error && (
        <button
          className="secondary-button"
          onClick={() => void query.refetch()}
        >
          Sprawdź tę operację ponownie
        </button>
      )}
      {transfer && (
        <>
          <div
            className={
              "notice " + (completed ? "success" : held ? "warning" : "")
            }
          >
            <strong>
              {completed
                ? "Zrealizowany"
                : held
                  ? "Wstrzymany"
                  : cancelled
                    ? "Anulowany"
                    : "Jeszcze nie zrealizowany"}
            </strong>
            <p>
              Identyfikator: <span className="operation-id">{transfer.id}</span>
            </p>
            <p>
              Wersja danych: {transfer.version} · {date(transfer.created)}
            </p>
          </div>
          <Summary transfer={transfer} />
          {!terminal(transfer.status) && (
            <>
              <p className="notice">
                Serwer nie zarejestrował wykonania tej operacji. Możesz wrócić
                do niej i sprawdzić kod. Ponowienie dotyczy tego samego
                identyfikatora.
              </p>
              <Link className="primary-button" to={transferPath(transfer)}>
                Wróć do tej operacji
              </Link>
            </>
          )}
          {terminal(transfer.status) && (
            <div className="actions">
              <Link className="primary-button" to="/app">
                Wróć do konta
              </Link>
              <Link className="secondary-button" to="/app/history">
                Zobacz historię
              </Link>
            </div>
          )}
          {held && (
            <Link
              className="text-button"
              to={`/help?return=${encodeURIComponent("/app/transfers/" + id + "/status")}`}
            >
              Gdzie szukać pomocy?
            </Link>
          )}
          {completed && (
            <Link className="text-button" to="/app/survey">
              Oceń przebieg zadania
            </Link>
          )}
        </>
      )}
    </>
  );
}
