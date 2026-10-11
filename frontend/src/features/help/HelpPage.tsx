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
        Skip to content
      </a>
      <header className="public-header">
        <Link to="/" aria-label="Bank24 — home page">
          <Bank24Logo />
        </Link>
        <Link className="button button-secondary" to="/login">
          Sign in
        </Link>
      </header>
      <main className="help-main" id="main" tabIndex={-1}>
        <Link to={back} className="back-link" aria-label="Back">
          ← Back
        </Link>
        <PageTitle
          title="Help center"
          intro="Guidance on using the Bank24 demo."
        />
        <div className="help-topics">
          <details open>
            <summary>Sign-in and codes</summary>
            <p>
              Enter the demo account username and password, then confirm sign-in with a separate code. In demo mode the code appears on screen; no SMS is sent.
            </p>
            <p>
              If the code expires, request another. Five failed attempts temporarily block sign-in.
            </p>
          </details>
          <details>
            <summary>Transfer and confirmation</summary>
            <p>
              Compare the recipient name, full account number, reference and amount with the document. Edit any incorrect details. The code applies only to the details shown in the summary.
            </p>
            <p>
              If your connection drops during confirmation, check the status of the same transaction. Do not create a second transfer.
            </p>
          </details>
          <details>
            <summary>SafeTransfer review</summary>
            <p>
              This demonstrates the flow and interface. The risk model is unvalidated and may return no result. A missing assessment does not mean the transaction is safe or unsafe.
            </p>
          </details>
          <details>
            <summary>Camera and optional measurements</summary>
            <p>
              Camera and telemetry permissions are separate and optional. They do not affect access to your account or transfers. The camera sends video to the local analysis server without recording audio; you can turn it off at any time.
            </p>
            <p>
              Face detection does not verify identity. Estimated pulse is not a medical measurement.
            </p>
          </details>
          <details>
            <summary>Demo data</summary>
            <p>
              Accounts, history and transfers are fictional. Bank24 does not process real payments or offer support for real bank accounts.
            </p>
          </details>
        </div>
        {canWithdraw && (
          <section className="withdraw-section">
            <h2>Optional session data</h2>
            <p>
              You can delete usage metadata, turn off the camera and delete survey responses. The fictional account history will remain consistent with the balance.
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
              {task.busy ? "Deleting data…" : "Delete optional data"}
            </button>
          </section>
        )}
        <ErrorNotice error={task.error} />
        <Link className="button button-primary" to={back}>
          Back to Bank24
        </Link>
      </main>
      <footer className="site-footer">
        <span>Bank24 · demonstration environment</span>
        <span>Fictional data and funds</span>
      </footer>
    </div>
  );
}
