# Software validation

All results below are software checks, not scientific validation of attribution.
Tests use isolated databases and toy fixtures; simulated provider failures are
explicit test stubs, not new model inference.

## Public copy, checked 6 November 2026

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | 61 tests passed |
| `python -m tests.browser_flow --output artifacts/publication-browser` | 14 checks passed; no JavaScript errors or failed requests |
| JavaScript syntax through `node --check` | Passed |
| Live model calls during those checks | 0 |

[Unit result](verification/public-unit.json) and
[browser result](verification/public-browser.json) retain the observed outcomes.
Python 3.12.10 and Playwright 1.63.0 were used. Browser tooling is optional and not
vendored; `requirements-dev.txt` declares the tested Playwright version. There is
no separate frontend build or TypeScript check.

The browser workflow covers fixture idempotence, interactive session completion,
standing and simulated AI arrangements, exact evidence views, comparisons and
stale-result prevention, local diagnostics, imports/exports, simulated evaluator
timeout/retry, keyboard scroll regions and 390px reflow.

## Earlier checks of the same app source

Before preparing this public copy, the full development workspace passed 71
unit/API checks and 35 browser checks (14 workflow, 14 design, 7 motion/phone).
Ten of those unit checks belong to the private-archive-dependent modules excluded
from this release. Do not report 71 as the public clone's test count.

The design checks covered all five pages at 390, 834 and 1440 pixels, plus 320px
reflow, keyboard focus, reduced motion and seven contrast pairs. Motion checks
verified actual local font loading, finite/replayable traces, persisted motion
preferences, cross-site preview-link navigation, and clipboard fallback on an HTTP
origin. A separate six-pair contrast review covered the ink illustration panel.
These are bounded checks, not a WCAG conformance claim. The phone link opening
was user-confirmed, but a complete physical-phone workflow is not verified.

Two failures found during implementation remain documented: a CSS-unit parsing
mistake in the new test harness, and a preview cookie that blocked navigation
from another site. The harness now parses the numeric component. The adapter uses
`SameSite=Lax` for top-level GET navigation while retaining exact Origin and CSRF
requirements for POSTs. The motion suite and four adapter tests passed after the
fix. No historical model failure was converted into a success.

The [research-status document](research-status.md) records the original incorrect
model predictions, deadline failure and unresolved research gates separately.
