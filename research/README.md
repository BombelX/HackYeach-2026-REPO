# Research and analysis

The runnable bank lives in `frontend/` and `backend/`; the current collection app
lives in `data-collector/`. This directory retains research code and results.

| Directory | Purpose |
| --- | --- |
| [training/](training/README.md) | Training, inference and benchmark code |
| [training/artifacts/](training/artifacts/) | Canonical saved checkpoints, experiment reports and plots |
| [session-study/](session-study/README.md) | Original study implementation, analysis scripts, specifications and tests |

The third-party [SAPIMouse code and models](../models/sapimouse/README.md), including its license, are bundled under `models/sapimouse/`.

Saved outputs belong under `training/artifacts/`, separate from Python source.
The previous copies beside training source files were byte-for-byte duplicates
and have been removed. GUIDÆTA EDA reports have one copy under
`../eda/reports/guidaeta/`. Research checkpoints may require `git lfs pull`.
Raw sessions, participant data and local caches remain ignored.

The original `session-study/server` and `session-study/web` are a research
snapshot, not aliases for `data-collector`. The current collector adds a risk
screen/endpoint and other changes; the study's face-analysis scripts and tests
also import the original server. Consolidating these implementations requires
an explicit migration rather than deleting matching files independently.

Some archived preprocessing scripts import a `preprocessing` package that is
not included in this checkout. The former extensionless `research/preprocessing`
file contained only a docstring and did not supply that package. Those research
pipelines require restoring their implementation before they can run.
