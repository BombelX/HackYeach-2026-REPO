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
        title="Your feedback"
        intro="Tell us whether the transfer flow was clear to you."
      />
      {saved ? (
        <>
          <Status>Thank you. Your response has been saved.</Status>
          <Link className="primary-button" to="/app">
            Back to account
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
            <legend>How easy was the task?</legend>
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
                    "Very difficult",
                    "Difficult",
                    "Neither easy nor difficult",
                    "Easy",
                    "Very easy",
                  ][value - 1]
                }
              </label>
            ))}
          </fieldset>
          <label className="field">
            Comment (optional)
            <textarea
              maxLength={500}
              rows={4}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <p className="field-hint">
            Do not enter personal information or sign-in details.
          </p>
          <ErrorNotice error={task.error} />
          <button className="primary-button" disabled={task.busy || !rating}>
            {task.busy ? "Saving…" : "Send feedback"}
          </button>
        </form>
      )}
    </>
  );
}
