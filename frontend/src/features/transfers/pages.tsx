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
  forcedLogout,
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
    <section className="transfer-details" aria-label="Transfer details">
      <h2>Transfer details</h2>
      <dl className="summary-list transfer-summary">
        <div>
          <dt>Recipient</dt>
          <dd>{transfer.recipient}</dd>
        </div>
        <div>
          <dt>Recipient account</dt>
          <dd>{accountNumber(transfer.number)}</dd>
        </div>
        <div>
          <dt>Transfer reference</dt>
          <dd>{transfer.title}</dd>
        </div>
        <div>
          <dt>Amount</dt>
          <dd className="summary-amount">{money(transfer.amount_grosz)}</dd>
        </div>
        <div>
          <dt>Fee</dt>
          <dd>PLN 0.00</dd>
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
        amount: (transfer.amount_grosz / 100).toFixed(2),
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
      !forcedLogout.active &&
      dirty &&
      !nextLocation.pathname.startsWith("/app/transfers/") &&
      nextLocation.pathname !== "/help",
  );
  useBeforeUnload((event) => {
    if (dirty && !forcedLogout.active) {
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
        <Link to="/app">Back to account</Link>
      </>
    );
  if (edit.data && terminal(edit.data.status))
    return (
      <>
        <PageTitle title="Transaction complete" />
        <Link className="primary-button" to={transferPath(edit.data)}>
          View result
        </Link>
      </>
    );
  const invoice = account.data.invoice;
  return (
    <>
      <Steps current={0} />
      <PageTitle
        title={editId ? "Edit transfer" : "New transfer"}
        intro="Enter recipient details and compare them with the invoice. You will review the summary in the next step."
      />
      {blocker.state === "blocked" && (
        <section className="notice" role="alert">
          <h2>What should happen to the draft?</h2>
          <p>
            Keep the entered details in this tab or discard the draft. Refreshing removes the unsaved draft.
          </p>
          <div className="actions">
            <button
              className="secondary-button"
              onClick={() => {
                setDirty(false);
                blocker.proceed();
              }}
            >
              Keep and leave
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
              Discard and leave
            </button>
            <button className="text-button" onClick={() => blocker.reset()}>
              Stay on transfer
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
                errors.recipient = "Enter the recipient name.";
              if (!validNrb(values.number))
                errors.number =
                  "Check the 26-digit account number and its checksum.";
              if (!values.title.trim()) errors.title = "Enter a transfer reference.";
              if (amount === null)
                errors.amount = "Enter a positive amount, e.g. 1250.00.";
              else if (amount > account.data!.balance_grosz)
                errors.amount = "The amount exceeds available funds.";
              if (Object.keys(errors).length)
                throw new ApiError(
                  422,
                  "fields",
                  "Correct the highlighted details.",
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
            From account: Personal account
            <br />
            <strong>{money(account.data.balance_grosz)}</strong> available
          </p>
          <Field
            id="recipient"
            label="Recipient name"
            value={values.recipient}
            onChange={(e) => change("recipient", e.target.value)}
            maxLength={100}
            error={task.fields.recipient}
            autoComplete="off"
            required
          />
          <Field
            id="number"
            label="Recipient account number"
            value={values.number}
            onChange={(e) => change("number", e.target.value)}
            maxLength={40}
            error={task.fields.number}
            inputMode="numeric"
            autoComplete="off"
            required
            hint="26 digits of a Polish NRB account number."
          />
          <Field
            id="amount"
            label="Amount (PLN)"
            value={values.amount}
            onChange={(e) => change("amount", e.target.value)}
            error={task.fields.amount}
            inputMode="decimal"
            autoComplete="off"
            required
          />
          <Field
            id="title"
            label="Transfer reference"
            value={values.title}
            onChange={(e) => change("title", e.target.value)}
            maxLength={140}
            error={task.fields.title}
            autoComplete="off"
            required
          />
          <ErrorNotice error={task.error} />
          <div className="actions">
            <button className="primary-button" disabled={task.busy}>
              {task.busy ? "Saving details…" : "Review transfer"}
            </button>
            <Link className="text-button" to="/app">
              Back to account
            </Link>
          </div>
        </form>
        <aside className="invoice" aria-labelledby="invoice-heading">
          <h2 id="invoice-heading">Task invoice</h2>
          <p className="field-hint">Sample document · fictional data</p>
          <dl className="summary-list">
            <div>
              <dt>Invoice number</dt>
              <dd>{invoice.reference}</dd>
            </div>
            <div>
              <dt>Recipient</dt>
              <dd>{invoice.recipient}</dd>
            </div>
            <div>
              <dt>Account</dt>
              <dd>{accountNumber(invoice.number)}</dd>
            </div>
            <div>
              <dt>Amount due</dt>
              <dd>{money(invoice.amount_grosz)}</dd>
            </div>
            <div>
              <dt>Reference</dt>
              <dd>{invoice.title}</dd>
            </div>
          </dl>
          <p>
            Enter the details manually. Compare the full account number before confirming.
          </p>
        </aside>
      </div>
    </>
  );
}

type TransferDecision = {
  independent: boolean | null;
  compared: boolean;
  risk_acknowledged: boolean;
};
const decisions = new Map<string, { version: number; value: TransferDecision }>();
export function ReviewPage() {
  const query = useTransfer();
  const task = useTask();
  const navigate = useNavigate();
  const id = useParams().id!;
  const [localDecision, setLocalDecision] = useState<{
    id: string;
    version: number;
    value: TransferDecision;
  } | null>(null);
  if (!query.data)
    return (
      <>
        <Loading />
        <ErrorNotice error={query.error} />
      </>
    );
  const transfer = query.data;
  const defaultDecision: TransferDecision = {
    independent: null,
    compared: false,
    risk_acknowledged: false,
  };
  const decision =
    localDecision?.id === id && localDecision.version === transfer.version
      ? localDecision.value
      : decisions.get(id)?.version === transfer.version
        ? decisions.get(id)!.value
        : defaultDecision;
  function change(next: TransferDecision) {
    const saved = { version: transfer.version, value: next };
    decisions.set(id, saved);
    setLocalDecision({ id, ...saved });
  }
  const cameraModel = transfer.risk.camera_model;
  const needsIndependentCheck =
    (transfer.risk.coercion_risk ?? 0) >= 70 || Boolean(cameraModel?.review_required);
  const hasBehavioralIndicators =
    transfer.risk.account_takeover_risk !== null ||
    transfer.risk.coercion_risk !== null;
  return (
    <>
      <Steps current={1} labels={["Transfer details", "Review", "SMS code"]} />
      <PageTitle
        title="Review transfer before confirming"
        intro="Compare the details with the document and confirm this is your decision."
      />
      <Summary transfer={transfer} />
      <section className="risk-note" aria-labelledby="risk-heading">
        <p className="eyebrow">SAFETRANSFER</p>
        <h2 id="risk-heading">
          {cameraModel
            ? "Camera-based risk assessment"
            : hasBehavioralIndicators
              ? "Experimental behavioral indicators"
              : "Risk assessment unavailable"}
        </h2>
        {hasBehavioralIndicators ? (
          <>
            <p>
              These are unvalidated comparison indicators on a 0–100 scale, not fraud probabilities or identity verification.
            </p>
            <dl className="risk-indicators">
              <div>
                <dt>
                  {cameraModel
                    ? "Owner profile mismatch (camera)"
                    : "Sign-in deviation from baseline"}
                </dt>
                <dd>
                  {transfer.risk.account_takeover_risk === null
                    ? "No result"
                    : `${transfer.risk.account_takeover_risk}/100`}
                </dd>
              </div>
              {!cameraModel && (
                <div>
                  <dt>Transfer deviation</dt>
                  <dd>
                    {transfer.risk.coercion_risk === null
                      ? "No result"
                      : `${transfer.risk.coercion_risk}/100`}
                  </dd>
                </div>
              )}
              {cameraModel && (
                <div>
                  <dt>Review score (threshold {cameraModel.review_threshold.toFixed(2)})</dt>
                  <dd>
                    {cameraModel.review_score.toFixed(2)}
                    {cameraModel.review_required ? " — verification required" : " — within range"}
                  </dd>
                </div>
              )}
            </dl>
          </>
        ) : (
          <p>
            A ready profile or sufficient data is missing. A missing result does not mean the transaction is safe or unsafe.
          </p>
        )}
        <details>
          <summary>
            {hasBehavioralIndicators ? "How should I interpret the result?" : "Why is there no result?"}
          </summary>
          <ul>
            {transfer.risk.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </details>
      </section>
      <fieldset>
        <legend>Are you making this transfer of your own free will?</legend>
        <p className="field-hint">
          If someone is pressuring you, demanding an urgent transfer or asking you to hide its purpose, choose the second answer.
        </p>
        <label className="choice-row">
          <input
            type="radio"
            name="independent"
            checked={decision.independent === true}
            onChange={() => change({ ...decision, independent: true })}
          />
          Yes, this is my own decision
        </label>
        <label className="choice-row">
          <input
            type="radio"
            name="independent"
            checked={decision.independent === false}
            onChange={() => change({ ...decision, independent: false })}
          />
          Someone is pressuring me or I have doubts
        </label>
      </fieldset>
      {needsIndependentCheck && (
        <section className="notice warning" aria-labelledby="risk-check-heading">
          <h2 id="risk-check-heading">Verify the recipient independently</h2>
          <p>
            The experimental deviation indicator is elevated. This does not establish pressure, but verify the recipient through a known official channel before continuing. Do not use a number or link from the message you received.
          </p>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={decision.risk_acknowledged}
              onChange={(event) =>
                change({
                  ...decision,
                  risk_acknowledged: event.target.checked,
                })
              }
            />
            I confirm that I verified the recipient independently.
          </label>
        </section>
      )}
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={decision.compared}
          onChange={(e) => change({ ...decision, compared: e.target.checked })}
        />
        I compared the recipient, account and amount with the document.
      </label>
      {decision.independent === false && (
        <p className="notice warning">
          We will hold this transaction without debiting your account. Do not share the confirmation code with anyone.
        </p>
      )}
      <ErrorNotice error={task.error} />
      <button
        className="primary-button"
        disabled={
          task.busy ||
          decision.independent === null ||
          !decision.compared ||
          (needsIndependentCheck &&
            decision.independent !== false &&
            !decision.risk_acknowledged)
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
          ? "Saving decision…"
          : decision.independent === false
            ? "Hold transfer"
            : "Continue to confirmation"}
      </button>
      <div className="actions">
        <Link className="text-button" to={`/app/transfers/new?edit=${id}`}>
          Edit details
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
          Cancel transfer
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
        title="Confirm transfer"
        intro="The code confirms only these details. Check the recipient and amount before entering it."
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
          {task.busy ? "Requesting code…" : "Request confirmation code"}
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
                    error.code === "risk_review"
                  ) {
                    await queryClient.invalidateQueries({
                      queryKey: ["transfer", id],
                    });
                    queryClient.removeQueries({
                      queryKey: ["transfer-challenge", id],
                    });
                    navigate(`/app/transfers/${id}/review`, {
                      replace: true,
                    });
                    return;
                  }
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
              label="Confirmation code"
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
                  ? `Code valid for another ${countdown.expires} s.`
                  : "Code expired. Request a new one."
              }
            />
            {challenge.data.demo_mode && (
              <p className="notice">
                Test code: <strong>1234</strong>. No SMS is sent.
              </p>
            )}
            <button
              className="primary-button"
              disabled={task.busy || !countdown.expires}
            >
              {task.busy
                ? "Checking transfer status…"
                : `Confirm ${money(transfer.amount_grosz)}`}
            </button>
          </form>
          <button
            className="text-button"
            disabled={task.busy || countdown.cooldown > 0}
            onClick={() => void orderCode()}
          >
            {countdown.cooldown
              ? `New code in ${countdown.cooldown} s`
              : "Request a new code"}
          </button>
        </>
      )}
      <div className="actions">
        <Link className="text-button" to={`/app/transfers/new?edit=${id}`}>
          Edit transfer details
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
          Cancel transfer
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
            ? "Transfer completed"
            : held
              ? "Transfer held"
              : cancelled
                ? "Transfer canceled"
                : "Checking transfer status"
        }
        intro={
          completed
            ? "Balance and history have been updated on the server."
            : held
              ? "Your account was not debited. Do not share codes or sign-in details with anyone."
              : cancelled
                ? "Your account was not debited."
                : "We are checking the same transaction. Do not prepare a second transfer."
        }
      />
      {query.isPending && <Loading />}
      <ErrorNotice error={query.error} />
      {query.error && (
        <button
          className="secondary-button"
          onClick={() => void query.refetch()}
        >
          Check this transaction again
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
                ? "Completed"
                : held
                  ? "Held"
                  : cancelled
                    ? "Canceled"
                    : "Not completed yet"}
            </strong>
            <p>
              ID: <span className="operation-id">{transfer.id}</span>
            </p>
            <p>
              Data version: {transfer.version} · {date(transfer.created)}
            </p>
          </div>
          <Summary transfer={transfer} />
          {!terminal(transfer.status) && (
            <>
              <p className="notice">
                The server has not recorded completion of this transaction. Return to it and check the code. Retrying uses the same ID.
              </p>
              <Link className="primary-button" to={transferPath(transfer)}>
                Back to this transaction
              </Link>
            </>
          )}
          {terminal(transfer.status) && (
            <div className="actions">
              <Link className="primary-button" to="/app">
                Back to account
              </Link>
              <Link className="secondary-button" to="/app/history">
                View history
              </Link>
            </div>
          )}
          {held && (
            <Link
              className="text-button"
              to={`/help?return=${encodeURIComponent("/app/transfers/" + id + "/status")}`}
            >
              Where can I get help?
            </Link>
          )}
          {completed && (
            <Link className="text-button" to="/app/survey">
              Rate the task flow
            </Link>
          )}
        </>
      )}
    </>
  );
}
