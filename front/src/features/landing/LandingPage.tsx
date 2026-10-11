import { Link } from "react-router";
import { Bank24Logo, Icon } from "../../design/components";

const features = [
  {
    icon: "shield" as const,
    title: "Decyzja należy do Ciebie",
    text: "Czytelne podsumowanie przelewu przed jego zatwierdzeniem.",
  },
  {
    icon: "history" as const,
    title: "Finanse w jednym miejscu",
    text: "Saldo, wpływy, wydatki i historia dostępne w przejrzystym widoku.",
  },
  {
    icon: "transfer" as const,
    title: "Przelew pod kontrolą",
    text: "Sprawdź dane odbiorcy, popraw je lub wstrzymaj operację.",
  },
];

export function LandingPage() {
  return (
    <div className="landing-shell">
      <a className="skip-link" href="#main">
        Przejdź do treści
      </a>
      <header className="landing-header">
        <Link to="/" aria-label="Bank24 — strona główna">
          <Bank24Logo />
        </Link>
        <nav aria-label="Nawigacja główna">
          <a href="#mozliwosci">Możliwości</a>
          <a href="#bezpieczenstwo">Bezpieczeństwo</a>
          <a href="#jak-dziala">Jak to działa</a>
        </nav>
        <Link className="button button-primary landing-login" to="/login">
          Zaloguj się <Icon name="arrow" size={17} />
        </Link>
      </header>
      <main id="main" tabIndex={-1}>
        <section className="landing-hero">
          <div className="hero-copy">
            <p className="eyebrow">
              <span /> BANKOWOŚĆ, KTÓRA JEST PO TWOJEJ STRONIE
            </p>
            <h1>
              Twoje finanse.
              <br />
              <em>Twój spokój.</em>
            </h1>
            <p className="hero-intro">
              Sprawdź, jak może wyglądać prosta i uważna bankowość. Zobacz
              rachunek, przeanalizuj szczegóły przelewu i podejmij decyzję bez
              pośpiechu.
            </p>
            <div className="hero-actions">
              <Link className="button button-primary button-large" to="/login">
                Przejdź do logowania <Icon name="arrow" />
              </Link>
              <a
                className="button button-secondary button-large"
                href="#jak-dziala"
              >
                Poznaj Bank24
              </a>
            </div>
            <p className="hero-note">
              <Icon name="shield" size={17} /> Demonstracja z fikcyjnymi danymi
              i środkami
            </p>
          </div>
          <div
            className="hero-visual"
            role="img"
            aria-label="Górskie jezioro o wschodzie słońca"
          >
            <div className="hero-image-credit">GÓRSKI PORANEK · BANK24</div>
            <div className="balance-float">
              <span className="float-label">Rachunek osobisty</span>
              <strong>12 420,50 zł</strong>
              <span className="float-account">Dostępne środki</span>
              <div className="float-divider" />
              <span className="float-transaction">
                <i>
                  <Icon name="transfer" size={16} />
                </i>
                <span>
                  <b>Ostatnia operacja</b>
                  <small>Zakupy · dzisiaj</small>
                </span>
                <strong>−129,00 zł</strong>
              </span>
            </div>
          </div>
          <div className="hero-bottom-note">
            <span>01 / BANK24</span>
            <span>Bankowość zaprojektowana z myślą o jasnych decyzjach</span>
          </div>
        </section>
        <section className="landing-features" id="mozliwosci">
          <div className="section-intro">
            <p className="eyebrow">PROSTO I PRZEJRZYŚCIE</p>
            <h2>
              Najważniejsze sprawy,
              <br />
              bez zbędnego szumu.
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
        <section className="landing-safety" id="bezpieczenstwo">
          <div className="safety-mark">
            <Icon name="shield" size={28} />
          </div>
          <div>
            <p className="eyebrow">SPOKOJNIE, KROK PO KROKU</p>
            <h2>
              Ważne decyzje zasługują
              <br />
              na chwilę uwagi.
            </h2>
            <p>
              Przed potwierdzeniem zobaczysz komplet danych przelewu. Możesz
              wrócić do edycji, zatrzymać operację lub poprosić o nowy kod.
            </p>
          </div>
          <Link className="text-link" to="/help">
            Jak działa sprawdzenie? <Icon name="arrow" size={16} />
          </Link>
        </section>
        <section className="landing-process" id="jak-dziala">
          <p className="eyebrow">JAK TO DZIAŁA</p>
          <h2>Od logowania do pełnej kontroli.</h2>
          <ol>
            <li>
              <span>1</span>
              <div>
                <strong>Zaloguj się</strong>
                <p>
                  Użyj danych konta demonstracyjnego i potwierdź logowanie
                  kodem.
                </p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>Sprawdź swoje konto</strong>
                <p>Zobacz saldo i przejrzyj ostatnie operacje.</p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>Wykonaj przelew</strong>
                <p>Porównaj dane, podejmij decyzję i potwierdź operację.</p>
              </div>
            </li>
          </ol>
          <Link className="button button-primary button-large" to="/login">
            Zaloguj się <Icon name="arrow" />
          </Link>
        </section>
      </main>
      <footer className="landing-footer">
        <Link to="/" aria-label="Bank24 — strona główna">
          <Bank24Logo />
        </Link>
        <span>Bank24 · Demonstracja HackYeah 2026</span>
        <span>Fikcyjne dane. Bez prawdziwych płatności.</span>
        <Link to="/help">Pomoc</Link>
      </footer>
    </div>
  );
}
