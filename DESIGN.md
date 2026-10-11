---
name: Bank24 / SafeTransfer
description: Calm, light fintech interface inspired by the supplied Bank24 screens.
colors:
  navy: "#062f4c"
  navy-hover: "#0a456a"
  accent: "#00645f"
  mint: "#b6e4da"
  mint-hover: "#d0eee7"
  mint-tint: "#e5f2ef"
  ink: "#102b43"
  muted: "#647786"
  line: "#d8e1e5"
  surface: "#ffffff"
  canvas: "#f5f7f7"
  success: "#236a54"
  success-bg: "#edf7f1"
  amber: "#81561b"
  amber-bg: "#fff7e8"
  error: "#a5323a"
typography:
  family: "IBM Plex Sans, Segoe UI, sans-serif"
  body: "16px / 1.55"
  task-heading: "clamp(30px, 4vw, 42px) / 1.15 / 600"
  support: "12–14px / 1.5"
  balance: "clamp(32px, 4vw, 43px), tabular figures"
---

# Bank24 — implemented interface design

The supplied Bank24 mockups guide the hierarchy and composition: light surfaces, a cool neutral background, navy actions and restrained teal. The application uses real demo data and native HTML/CSS. Camera panels show the actual stream; risk displays and security claims must reflect available evidence.

The public landing page at `/` works without the banking API and leads directly to sign-in. Authenticated screens use a consistent bank shell. PLN currency and Polish account-number validation remain part of the banking domain; interface text is English.

## Components and pages

Use the tokens above and local IBM Plex Sans. Buttons and fields have clear focus, pending, disabled and error states. Keep one main heading and primary task per screen. Error messages explain recovery and associate with their fields. Display unavailable measurements explicitly rather than as zero.

The landing page combines a landscape, native headings and links, a clearly illustrative account view, and a short explanation of SafeTransfer. Do not imply guaranteed fraud detection. Login uses a compact form with password visibility, remembered-device choice, help and a separate verification-code step. Demo credentials belong in a disclosure.

The account page shows the actual balance, account number, working copy action, recent transactions and monthly totals. History provides working search and filters. Transfer pages follow details, review and confirmation, with invoice context close to the form. Results emphasize status, amount and recipient; technical identifiers belong in details.

Camera controls are optional and explicit. The transfer page contains the supporting camera panel; the header provides global status and a stop action. Experimental parameters are collapsed by default. Heart rate, face presence, posture and expressions are measurements, not identity verification or proof of coercion.

## Responsive behavior and accessibility

Below 1150 px, move the supporting camera panel below the task. Below 800 px, compact navigation and the sidebar. Below 560 px, use one column. Support 320 px screens, 200% zoom, long values, visible keyboard focus, reduced motion and touch targets of at least 44 × 44 px. Never hide layout defects with clipping. Forms and text remain native and accessible.

## Assets and sources of truth

Implementation: `frontend/src/design/`, `frontend/src/layouts/` and feature pages. Product behavior: `backend/PRODUCT.md`; API: `backend/BANK24_API.md`. Historical audits document earlier states rather than current acceptance results.

The landscape was generated with this prompt:

> Premium editorial landscape photograph for a fictional Polish digital bank landing page: Lake Czorsztyn and the Tatra Mountains at a quiet early sunrise, calm water, soft blue-green palette, subtle mist, sophisticated natural light, generous open sky, realistic photography, no text, no logos, no people, wide 16:9 composition.
