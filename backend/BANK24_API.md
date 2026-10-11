# Bank24 API v1 — implemented local contract

`bank24_server.py` defaults to loopback port 8081; `webrtc_server.py` provides the
camera worker on port 8080. Vite's development proxy preserves the browser origin.

## Session and sign-in

`POST /api/bootstrap` creates or returns a session through an HttpOnly,
SameSite Strict cookie. The response contains `csrf`, `session_id`, `telemetry`,
`camera`, `authenticated`, `demo_mode`, `camera_transmission`, `study_participant`
and `study_session_id`. Session TTL is two hours. Participant mutations require
the cookie, `X-CSRF-Token` and an allowed Origin. Successful code verification
rotates the session cookie and CSRF token.

| Method and path | Input / result |
| --- | --- |
| POST `/api/session/permissions` | Partial update `{telemetry?:boolean,camera?:boolean}`; returns current session state |
| POST `/api/session/withdraw` | Requires sign-in; deletes participant data for a study session, otherwise current-session optional data; retains the fictional account |
| POST `/api/bank/login` | `{username,password,remember}` → challenge; valid credentials select the account |
| GET / POST `/api/bank/login-challenge` | Read / request another sign-in code |
| POST `/api/bank/verify` | `{challenge_id,code}` → `{ok,csrf}`; full authentication and token rotation |
| POST `/api/bank/logout` | Ends the session and camera resources |
| DELETE `/api/bank/device` | Revokes trust for the current device |
| GET `/api/bank/account` | Requires full sign-in; balance in grosz, NRB, monthly totals, device state and fictional invoice |
| GET `/api/bank/transactions?offset=0&limit=30&q=&direction=all` | Requires sign-in; searched/filtered list with exact `total` before pagination |
| POST `/api/study/survey` | Requires sign-in; `{rating:1..5,comment:string<=500}` |

Study participation is optional in the regular Bank24 demo. When used, participant
codes and consent link the session to the study before sign-in. Camera and
telemetry consent are separate. `direction` accepts `all`, `incoming`, `outgoing`.
History search is case-insensitive and accent-insensitive. Filtering occurs before
offset/limit, with deterministic ordering.

JSON errors use `{code,message,fields}`. Status 401 ends access, 403 indicates
CSRF/origin or permission failures, 409 state/version conflicts, 422 validation,
429 rate limits/cooldowns, and 503 unavailable services. There is no silent mock.

Challenges contain `challenge_id`, `expires_at`, `resend_at`, `demo_mode` and
`code_length`. Times use Unix seconds. Codes last 300 seconds, with a 30-second
resend cooldown and five attempts. `--demo` explicitly uses four-digit OTP `1234`.
Outside demo mode an `otp_provider` adapter must be passed to `create_app`;
without it the server returns 503 instead of pretending to send SMS.

## Transfers

| Method and path | Input / result |
| --- | --- |
| POST `/api/bank/transfers` | `{recipient,number,title,amount_grosz}` → saved preview, 201 |
| PUT `/api/bank/transfers/{id}` | Same fields plus `{version}` → new version; invalidates previous codes and decisions |
| GET `/api/bank/transfers/{id}` | Persistent state owned by the signed-in account |
| POST `/api/bank/transfers/{id}/intervention` | `{version,independent:boolean,compared:true,risk_acknowledged?:boolean}` → `ready` or irreversible `held`; pressure ≥70 requires independent recipient verification |
| GET / POST `/api/bank/transfers/{id}/challenge` | Read / request a code bound to transfer ID and version |
| POST `/api/bank/transfers/{id}/submit` | `{version,challenge_id,code}` plus `Idempotency-Key` → saved result |
| POST `/api/bank/transfers/{id}/cancel` | Cancels an unfinished transfer |

The frontend combines summary, comparison and decision-independence questions.
The API enforces state transitions, so clients cannot skip comparison or release
a held transfer. States follow `review → ready → completed`, with `held` and
`cancelled` alternatives. Amounts are positive integer grosz. NRB account numbers
must pass checksum validation. Submit checks the balance and updates account and
history atomically. Retrying a completed transfer never debits it again.

`risk` exposes separate experimental 0–100 comparison indicators when the relevant
owner profile and telemetry exist. They are neither calibrated probabilities nor
validated detection. Outside a study, without a ready profile or with sparse data,
values remain `null`. The response describes `assessment_status`,
`available_signals`, `missing_reasons`, explanations, `available_modalities` and
model version. Scenario labels are not engine inputs. Comparison, independence
confirmation and OTP requirements still apply. A pressure increase before submit
returns the operation to review and invalidates its old code.

## Study and operator

Participant mutations require the current Bank24 session, CSRF and allowed Origin.
Operator requests require `Authorization: Bearer <BANK24_ADMIN_TOKEN>`;
operator mutations also require Origin. Configure `BANK24_ADMIN_TOKEN` or
`--admin-token`. The operator API is disabled when no token is configured.

| Method and path | Input / result |
| --- | --- |
| POST `/api/admin/participants` (alias POST `/api/study/participants`) | Existing account: `{label,role,bank_username}`; new: `{label,role,username,password,starting_balance_grosz?}`; returns `study_code` once |
| GET `/api/admin/participants` | List without participant codes or passwords |
| GET `/api/admin/scenarios` | Allowed scenarios |
| GET `/api/admin/profiles?bank_username=` | Per-stage profile version, readiness, observations, medians and MAD |
| POST `/api/admin/participants/{id}/assignments` | `{scenario}`; operator assigns before the session |
| POST `/api/study/resolve-code` | `{code}`; links the pre-login session to an issued code |
| POST `/api/study/consent` | `{telemetry:boolean,camera:boolean,recording:false?}`; saves versioned consent |
| POST `/api/study/sessions` | `{}`; creates a session using the next assignment |
| POST `/api/study/sessions/{id}/start` | Starts the session at `login` |
| POST `/api/study/sessions/{id}/stage` | `{stage:'transfer'|'result'}`; stages must advance in order |
| POST `/api/study/sessions/{id}/complete` | Completes and refreshes the baseline for eligible calm owner sessions |
| POST `/api/study/sessions/{id}/abort` | `{reason?}`; aborts an active session |
| POST `/api/study/participants/{id}/withdraw` | Participant deletes own data after supplying their code; operator equivalent: `/api/admin/participants/{id}/withdraw` |
| GET `/api/risk/study-sessions/{id}/latest` | Latest assessment for the session owner |
| GET `/api/risk/study-sessions/{id}/timeline` | Assessments/features across stages |
| GET `/api/admin/sessions?participant_id=&offset=0&limit=30` | Paginated study sessions |
| GET `/api/admin/sessions/{id}` | Details, aggregated features, allowed event metadata and assessments |
| POST `/api/admin/sessions/{id}/abort` | `{reason?}`; ends an abandoned session |
| POST `/api/admin/exports` | `{participant_id?}` or `{session_id?}`; JSON sessions, metadata, features and assessments |

Scenarios: `calm_owner`, `calm_dictation`, `pressure`, `intruder`. Only the operator
assigns them. Session-creation requests cannot choose a scenario. `calm_owner`
requires a participant marked `role='owner'`. Baselines use completed calm owner
sessions with consent and sufficient telemetry: at least three observations per
stage. Profiles store version, medians, MAD and data coverage.

Feature extraction stores no field contents. Events contain interaction type,
field ID, time, input length, normalized pointer movement and locally computed
key dwell time. Typed codes and values are excluded. Refusal/withdrawal stops
collection and deletes linked data. Participation withdrawal removes events,
assessments and assignments, then rebuilds profiles from remaining eligible sessions.

Assessment compares owner medians using MAD with a minimum scale. Minimum event
counts and feature coverage are required; missing data yields `null`, never zero.
`account_takeover_risk` uses sign-in features and `coercion_risk` transfer features.
Responses declare `validated:false`, `model_version`, and `limited` or
`insufficient_data`. These demo indicators do not establish fraud.

## Camera and telemetry

`GET /api/bank/camera-profile` returns readiness, sample counts, version and whether
the current session contributed a sample. POST
`/api/bank/camera-profile/enroll/start` with `{"confirm_calm":true}` marks the start
of a separate recording. POST `/api/bank/camera-profile/enroll` with the same
confirmation saves only data after that marker. Code-verified sign-in, an active
camera and at least 40 seconds of recording with a visible face across most
analysis windows are required. Recordings expire after ten minutes or a camera
session change. One sample is accepted per sign-in.

Three approved samples from separate sessions create a profile. Demo mode
automatically approves the initial three; otherwise operator approval is required.
Later samples always await independent operator verification before creating a
version. The model's own score cannot authorize an update.

- GET `/api/admin/camera-profile/candidates` lists pending samples.
- POST `/api/admin/camera-profile/candidates/{bank_session}/approve` with `{"verified":true}` approves after independent verification.
- DELETE `/api/admin/camera-profile/candidates/{bank_session}` rejects a candidate.

Approval requires `BANK24_ADMIN_TOKEN`. Without an operator, samples that would
wait indefinitely are not accepted. DELETE `/api/bank/camera-profile` removes all
samples, versions and any legacy account profile file. Assessments only read
profiles; missing profiles yield `insufficient_data`. New versions take effect at
the next sign-in, preventing comparison against a profile containing the current
recording. Data lives in SQLite; automatically created legacy profiles are not
imported. Unvalidated camera results may request review but do not automatically
sign users out. Synthetic alarm sign-out remains a demo feature.

POST `/api/webrtc/offer`, GET `/api/sessions/{id}/output` and DELETE
`/api/sessions/{id}` require full sign-in and separate `camera=true` consent.
The gateway checks session ownership. Video has no audio and recordings are not
saved. Worker WebSockets are not exposed directly; authenticated snapshots are
available to the frontend. Revoking permission closes the camera.

POST `/api/telemetry/events` requires `telemetry=true` and accepts
`{page,page_anchor_ms,events:[...]}` with at most 100 events. Allowed fields:
`sequence`, `time_ms`, `type`, `stage`, `field`, optionally `length`, `duration_ms`,
`x`, `y`, `width`, `height`, `delta_y`, `env`, `status`, `keys`, `features`
(as appropriate for the event type). Plaintext typed values are rejected. Types: input, correction, focus, pointer,
key_press, key_dwell, pointerdown, pointerup, click, wheel, paste, copy, cut,
window_blur, hidden, environment, ping, server_request and keyboard_window.
Environment metadata uses an explicit browser/device allowlist. Keyboard windows
carry 16–96 key identifiers and eight timing/category features per stroke;
password fields are rejected. The server converts these transient inputs using
`keystroke_long_epoch_59.pt` and persists only the resulting 128D embedding.
Missing models return 503. Keyboard and mouse windows, interaction markers,
connection timings and device metadata join the camera timeline for both
explicit enrollment and live fusion scoring, only while telemetry consent is enabled.
Stages: login, transfer. Fields use an allowlist. Coordinates
are normalized to 0–1. Duplicate `(session,page,sequence)` entries are skipped.
The server adds the time anchor/receipt time and links events to the active study.
