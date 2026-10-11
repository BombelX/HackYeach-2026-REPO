import { Link } from "react-router";
import { Bank24Logo, Icon } from "../../design/components";

const features = [
  {
    icon: "shield" as const,
    title: "The decision is yours",
    text: "A clear transfer summary before confirmation.",
  },
  {
    icon: "history" as const,
    title: "Your finances in one place",
    text: "Balance, income, spending and history in one clear view.",
  },
  {
    icon: "transfer" as const,
    title: "Transfers under control",
    text: "Check recipient details, edit them or pause the transaction.",
  },
];

export function LandingPage() {
  return (
    <div className="landing-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="landing-header">
        <Link to="/" aria-label="Bank24 — home page">
          <Bank24Logo />
        </Link>
        <nav aria-label="Main navigation">
          <a href="#mozliwosci">Features</a>
          <a href="#security">Security</a>
          <a href="#how-it-works">How it works</a>
        </nav>
        <Link className="button button-primary landing-login" to="/login">
          Sign in <Icon name="arrow" size={17} />
        </Link>
      </header>
      <main id="main" tabIndex={-1}>
        <section className="landing-hero">
          <div className="hero-copy">
            <p className="eyebrow">
              <span /> BANKING ON YOUR SIDE
            </p>
            <h1>
              Your finances.
              <br />
              <em>Your peace of mind.</em>
            </h1>
            <p className="hero-intro">
              Discover simple, thoughtful banking. View your account, review transfer details and take your time to decide.
            </p>
            <div className="hero-actions">
              <Link className="button button-primary button-large" to="/login">
                Go to sign in <Icon name="arrow" />
              </Link>
              <a
                className="button button-secondary button-large"
                href="#how-it-works"
              >
                Discover Bank24
              </a>
            </div>
            <p className="hero-note">
              <Icon name="shield" size={17} /> Demo with fictional data and funds
            </p>
          </div>
          <div
            className="hero-visual"
            role="img"
            aria-label="Mountain lake at sunrise"
          >
            <div className="hero-image-credit">MOUNTAIN MORNING · BANK24</div>
            <div className="balance-float">
              <span className="float-label">Personal account</span>
              <strong>PLN 12,420.50</strong>
              <span className="float-account">Available funds</span>
              <div className="float-divider" />
              <span className="float-transaction">
                <i>
                  <Icon name="transfer" size={16} />
                </i>
                <span>
                  <b>Latest transaction</b>
                  <small>Shopping · today</small>
                </span>
                <strong>−PLN 129.00</strong>
              </span>
            </div>
          </div>
          <div className="hero-bottom-note">
            <span>01 / BANK24</span>
            <span>Banking designed for clear decisions</span>
          </div>
        </section>
        <section className="landing-features" id="mozliwosci">
          <div className="section-intro">
            <p className="eyebrow">SIMPLE AND CLEAR</p>
            <h2>
              What matters most,
              <br />
              without the noise.
            </h2>
          </div>
          <div className="feature-grid">
            {features.map((feature, index) => (
              <article className="feature-card" key={feature.title}>
                <span className="feature-number">0{index + 1}</span>
                <span className="feature-icon">
                  <Icon name={feature.icon} size={21} />
                </span>
                <h3>{feature.title}</h3>
                <p>{feature.text}</p>
              </article>
            ))}
          </div>
        </section>
        <section className="landing-safety" id="security">
          <div className="safety-mark">
            <Icon name="shield" size={28} />
          </div>
          <div>
            <p className="eyebrow">TAKE YOUR TIME, STEP BY STEP</p>
            <h2>
              Important decisions deserve
              <br />
              a moment of attention.
            </h2>
            <p>
              You will see all transfer details before confirmation. You can edit them, stop the transaction or request a new code.
            </p>
          </div>
          <Link className="text-link" to="/help">
            How does the review work? <Icon name="arrow" size={16} />
          </Link>
        </section>
        <section className="landing-process" id="how-it-works">
          <p className="eyebrow">HOW IT WORKS</p>
          <h2>From sign-in to full control.</h2>
          <ol>
            <li>
              <span>1</span>
              <div>
                <strong>Sign in</strong>
                <p>
                  Use the demo account credentials and confirm sign-in with a code.
                </p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>Check your account</strong>
                <p>View your balance and recent transactions.</p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>Make a transfer</strong>
                <p>Compare the details, decide and confirm the transaction.</p>
              </div>
            </li>
          </ol>
          <Link className="button button-primary button-large" to="/login">
            Sign in <Icon name="arrow" />
          </Link>
        </section>
      </main>
      <footer className="landing-footer">
        <Link to="/" aria-label="Bank24 — home page">
          <Bank24Logo />
        </Link>
        <span>Bank24 · HackYeah 2026 demo</span>
        <span>Fictional data. No real payments.</span>
        <Link to="/help">Help</Link>
      </footer>
    </div>
  );
}
