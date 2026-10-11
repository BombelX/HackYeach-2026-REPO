# Bank24 / SafeTransfer frontend audit

4 October 2026. Historical audit of the React application before its redesign, using the supplied nine-screen mockup. The findings below describe that checkpoint, not the current interface. Recommendation: rebuild presentation while preserving APIs, validation, session/consent behavior, versioned transfers and duplicate-debit protection.

## Method and limitations

Reviewed routing, layout, components, CSS, study entry, login, account, transfer, history, camera and help. Playwright/Chrome exercised the real API against a separate SQLite database, creating one PLN 1.00 transfer for desktop and one for mobile without affecting the user's running demo.

Captured 12 screens at 1440 × 1000 and 390 × 844; additionally measured dashboard and form at 390, 768 and 1024 px. Twenty-four axe scans covered WCAG A/AA including 2.1 AA; the phone history filters reported a scrollable-region focus issue. Other clean scans do not establish full accessibility. The Impeccable detector returned `[]`; manual review found issues outside its coverage.

No physical camera, physical-phone test, full screen-reader study, participant study or Core Web Vitals measurement was performed. The hidden-stream finding came from code. Visual conclusions are expert judgments, not conversion evidence. The audit itself did not change application code.

Dated screenshots retain their original interface language to preserve historical evidence. The current English interface is shown in `docs/dashboard.png`.

Text captions in the evidence JSON have been translated into English; geometry and numeric results are unchanged. Captions are therefore no longer verbatim original UI text.

Evidence: [evidence.json](evidence.json), [layout-evidence.json](layout-evidence.json), [capture.mjs](capture.mjs) and [verify-layout.mjs](verify-layout.mjs). Historical servers: banking API port 8083, Vite 5181, database `data/frontend-audit-2026-10-04.sqlite`; stopped after the audit.

## Technical assessment

| Area | Score | Reason |
| --- | --- | --- |
| Accessibility | 2/4 | Semantic forms/focus provide a base; filters, route focus and small help targets need work. |
| Performance | 2/4, provisional | Local fonts use swap and no JS error occurred; repeated external images and no CWV measurement limit confidence. |
| Responsive behavior | 0/4 | Transfer form is practically unreadable at 390 px and account content is clipped. |
| Token/style consistency | 1/4 | Repeated overrides introduce conflicting colors, radii and layouts. Absence of dark mode is not a defect. |
| Interface integrity | 1/4 | Inert filters, fabricated chart, a notification icon that logs out and unsupported security claims. |
| Total | 6/20 | Presentation and behavior require rebuilding. |

Scores assess implementation quality, not backend correctness. P1 significantly obstructs the task or trust; P2 harms understanding/convenience with a workaround. No P0 was demonstrated: automation completed a transfer despite an impractical mobile layout.

## Findings

| ID | Priority | Evidence and correction |
| --- | --- | --- |
| F01 | P1 | A later `.bank-layout` rule reserves a 304 px camera column plus 20 px gap on mobile. At 390 px, the main column measures 16 px; at 768 px it is 338 px. The phone page is 3160 px tall. Use one explicit mobile column with `minmax(0, 1fr)`, nearby invoice context and a collapsed supporting camera module. |
| F02 | P1 | Dashboard cards end at x=407 while the shell ends at x=378. `overflow: clip` hides the defect even when scrollWidth equals viewport width. Set grid children to min-width zero, provide dedicated mobile statistics/rows and let amounts wrap independently. |
| F03 | P1 | Notification bell, avatar, owner name and logout share one button. Clicking the bell redirected to study entry. Separate logout and remove nonfunctional notification controls. |
| F04 | P1 | Always-on protection and 24/7 claims imply validated capabilities absent from the demo. Make demonstration status visible and describe actual checks without effectiveness guarantees. |
| F05 | P2 | A fixed 68% graphic and unconditional income-growth language conflict with account data. Derive summaries from real totals; show an honest empty state. |
| F06 | P1 | Collapsing the camera panel hides presentation without stopping the active stream, and no clear stop action is available. Distinguish collapse from stopping and provide persistent status/control. |
| F07 | P2 | History filters are spans rather than working keyboard controls; the mobile scrolling region fails axe focusability. Use semantic controls with state and accessible scrolling. |
| F08 | P2 | Search covers only the current 30-row page, resets state and leaves a blank 88 px column. Search the complete authorized history and preserve useful state. |
| F09 | P2 | A stock camera image and green dot suggest an active stream when off. Show actual off/permission/error states and real video only when connected. |
| F10 | P2 | Repeated photographs and three competing columns obscure the banking task. Rebuild hierarchy around the form and use restrained supporting content. |
| F11 | P2 | Repeated review/comparison/code screens add unnecessary steps. Consolidate around details, review, verification and result while preserving server-required checks. |
| F12 | P2 | Server ID and version dominate results. Lead with status, amount and recipient; move diagnostics to details. |
| F13 | P2 | Route focus can select a hidden/outside-main heading lacking focus support. Help targets are about 20 × 44 px. Focus a visible main heading and aim for 44 px targets; the measured width alone does not prove a WCAG failure because exceptions apply. |
| F14 | P1 | Appended CSS overrides and inferred `:has` geometry create conflicting grids/gaps. Use explicit layouts and one source for responsive rules. |

Additional issues: a copy icon is not a button; help assumes a fixed camera position; withdrawal has no explanatory confirmation (the destructive action was not exercised); verification visually expects four characters while accepting six. Code length must follow the API.

Historical source locations include `frontend/src/design/styles.css` around lines 164, 1065, 1290, 1356–1367 and 1419, and `frontend/src/layouts/RootLayout.tsx` around 87/102. The directory is now `frontend/`; historical line numbers are evidence pointers, not current locations. Screenshots such as `transfer-390.png` and `dashboard-390.png` were referenced in the original audit; consult available artifacts before relying on them.

## Design interpretation and preserved work

Generic slogans, decorative controls, a fake chart, repeated gradients/capsules and image reuse created an impression of generic generated design. This is an expert assessment of the interface, not proof of how it was produced. Preserve working API integration, native forms, keyboard focus, local fonts/logo, integer amounts, NRB validation, versioned drafts, permissions, null/unavailable distinctions and idempotence.

Apply the mockup hierarchy without adding fake cards, BLIK, mobile-app sign-in or hotline services. The audited flow still included study code/consent before login; the subsequent reimplementation plan replaced that gate with public landing and direct login.

A minimal repair could address individual failures. The recommended option rebuilds presentation while retaining contracts; a broader option also adds landing/materials. Start with layout foundations and banking/history flow, then entry/help, then responsive/accessibility verification. Test zero totals, outgoing amounts exceeding income, many history pages and all failure states. Historical references included Vercel interface guidelines and design skills; they are not runtime dependencies or current acceptance evidence.
