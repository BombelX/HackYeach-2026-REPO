import { useState } from "react";
import { Link } from "react-router";
import { useTask } from "../../app/hooks";
import { ErrorNotice, PageTitle, Status } from "../../design/components";
import { api } from "../../services/api";

export function SurveyPage() {
  const [rating, setRating] = useState("");
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState(false);
  const task = useTask();
  return (
    <>
      <PageTitle
        title="Twoja opinia"
        intro="Oceń, czy przepływ przelewu był dla Ciebie zrozumiały."
      />
      {saved ? (
        <>
          <Status>Dziękujemy. Odpowiedź została zapisana.</Status>
          <Link className="primary-button" to="/app">
            Wróć do konta
          </Link>
        </>
      ) : (
        <form
          aria-busy={task.busy}
          onSubmit={(e) => {
            e.preventDefault();
            void task.run(async () => {
              await api("/study/survey", "POST", {
                rating: Number(rating),
                comment,
              });
              setSaved(true);
            });
          }}
        >
          <fieldset>
            <legend>Jak łatwo było wykonać zadanie?</legend>
            {[1, 2, 3, 4, 5].map((value) => (
              <label className="checkbox-row" key={value}>
                <input
                  type="radio"
                  name="rating"
                  value={value}
                  checked={rating === String(value)}
                  onChange={(e) => setRating(e.target.value)}
                  required
                />
                {value} ·{" "}
                {
                  [
                    "Bardzo trudno",
                    "Trudno",
                    "Ani łatwo, ani trudno",
                    "Łatwo",
                    "Bardzo łatwo",
                  ][value - 1]
                }
              </label>
            ))}
          </fieldset>
          <label className="field">
            Komentarz (opcjonalny)
            <textarea
              maxLength={500}
              rows={4}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <p className="field-hint">
            Nie wpisuj danych osobowych ani danych logowania.
          </p>
          <ErrorNotice error={task.error} />
          <button className="primary-button" disabled={task.busy || !rating}>
            {task.busy ? "Zapisujemy…" : "Wyślij opinię"}
          </button>
        </form>
      )}
    </>
  );
}
