import {
  createBrowserRouter,
  Link,
  redirect,
  useRouteError,
  type LoaderFunctionArgs,
} from "react-router";
import { ErrorNotice, PageTitle, Loading } from "../design/components";
import { RootLayout } from "../layouts/RootLayout";
import { AuthLayout, BankLayout } from "../layouts/RouteLayouts";
import {
  accountOptions,
  api,
  queryClient,
  refreshSession,
  sessionOptions,
  type Transfer,
  transferOptions,
} from "../services/api";
import { SurveyPage } from "../features/study/pages";
import { LoginPage, VerifyLoginPage } from "../features/auth/pages";
import { DashboardPage, HistoryPage } from "../features/accounts/pages";
import {
  TransferFormPage,
  ReviewPage,
  ConfirmPage,
  StatusPage,
  transferPath,
} from "../features/transfers/pages";
import { HelpPage } from "../features/help/HelpPage";
import { LandingPage } from "../features/landing/LandingPage";

async function guard(kind: "login" | "bank") {
  const session = await refreshSession();
  if (kind === "bank" && !session.authenticated)
    return redirect(
      "/login?return=" +
        encodeURIComponent(location.pathname + location.search),
    );
  if (kind === "login" && session.authenticated) return redirect("/app");
  return session;
}

function transferLoader(stage: string) {
  return async ({ params }: LoaderFunctionArgs) => {
    const transfer = await queryClient.fetchQuery({
      ...transferOptions(params.id!),
      staleTime: 0,
    });
    if (
      stage !== "status" &&
      ["completed", "held", "cancelled"].includes(transfer.status)
    )
      return redirect(transferPath(transfer));
    if (stage === "confirm" && transfer.status !== "ready")
      return redirect(transferPath(transfer));
    if (stage === "review" && transfer.status === "ready")
      return redirect(transferPath(transfer));
    return transfer;
  };
}

function RouteError() {
  const error = useRouteError();
  return (
    <main className="error-page">
      <PageTitle
        title="Nie udało się otworzyć tego kroku"
        intro="Sprawdź połączenie. Samo ponowne otwarcie strony nie wyśle przelewu."
      />
      <ErrorNotice error={error} />
      <button
        className="button button-primary"
        onClick={() => location.reload()}
      >
        Spróbuj ponownie
      </button>
      <p>
        <Link to="/">Wróć na stronę główną</Link>
      </p>
    </main>
  );
}

function NotFound() {
  return (
    <main className="error-page">
      <PageTitle title="Nie znaleziono strony" />
      <Link to="/" className="button button-primary">
        Wróć na stronę główną
      </Link>
    </main>
  );
}

export const router = createBrowserRouter([
  {
    Component: RootLayout,
    HydrateFallback: Loading,
    ErrorBoundary: RouteError,
    children: [
      { index: true, Component: LandingPage },
      {
        Component: AuthLayout,
        loader: () => guard("login"),
        children: [
          { path: "login", Component: LoginPage },
          {
            path: "verify-login",
            loader: async () => {
              try {
                return await api("/bank/login-challenge");
              } catch {
                return redirect("/login");
              }
            },
            Component: VerifyLoginPage,
          },
        ],
      },
      {
        path: "app",
        Component: BankLayout,
        loader: () => guard("bank"),
        children: [
          {
            index: true,
            loader: async () => queryClient.ensureQueryData(accountOptions),
            Component: DashboardPage,
          },
          { path: "history", Component: HistoryPage },
          { path: "survey", Component: SurveyPage },
          { path: "transfers/new", Component: TransferFormPage },
          {
            path: "transfers/:id/review",
            loader: transferLoader("review"),
            Component: ReviewPage,
          },
          {
            path: "transfers/:id/confirm",
            loader: transferLoader("confirm"),
            Component: ConfirmPage,
          },
          {
            path: "transfers/:id/status",
            loader: transferLoader("status"),
            Component: StatusPage,
          },
          {
            path: "transfers/:id/intervention",
            loader: async ({ params }: LoaderFunctionArgs) => {
              const transfer = await queryClient.fetchQuery({
                ...transferOptions(params.id!),
                staleTime: 0,
              });
              return redirect(transferPath(transfer));
            },
          },
        ],
      },
      { path: "help", Component: HelpPage },
      { path: "study", loader: () => redirect("/login") },
      { path: "study/consent", loader: () => redirect("/login") },
      { path: "*", Component: NotFound },
    ],
  },
]);
