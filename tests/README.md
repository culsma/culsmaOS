# Tests

| Directory | Ownership |
| --- | --- |
| `modules/<module>/` | The matching `src/culsma_os/<module>/` contract |
| `integration/` | CLI, complete protocols, resident operation and cross-module execution |
| `architecture/` | Dependency boundaries, public text and test layout |
| `acceptance/` | Reproducible runners and runner tests |
| `support/<module>/` | Shared fixtures, fake ports and scenario harnesses; no collected test cases |
| `fixtures/<module>/` | Static input data |

Acceptance runners read their manifests from `tests/acceptance/manifests/`.
`tests/architecture/module-map.json` owns expected source components and paths. Internal diagram checks are separate.

Test cases do not import other test modules. Shared fixtures have explicit imports. `support/paths.py` owns the checkout root, so moving a test does not alter fixture discovery.

Run `python -m pytest tests/modules/program_manager -q` for an owning module, or `python -m pytest -q` for the full suite. Optional external backend requirements are explicit skips. Installed profile verification is recorded separately below.

S03 coverage snapshot on Python 3.11: **938 passed, 10 optional skips** across the full measurement and corrected targeted reruns. The initial three failures remain recorded in the [run ledger](../docs/evidence/test-coverage-20261018.json); this is not a single clean full-suite pass.

| Measurement | Observed |
| --- | ---: |
| Statements | 5050 / 5441 (92.81%) |
| Branches | 1262 / 1600 (78.88%) |
| Implemented methods | 568 / 573 |

The five unobserved methods belong to optional Hamilton compilation. The [method index](../docs/evidence/method-coverage-20261018.json) maps each implementation to a measured context and remaining branches. Execution attribution does not prove assertion quality.

For instrumented simulator runs, use `CULSMA_OS_TEST_TIMEOUT_MULTIPLIER=3 python -m pytest -q --cov=culsma_os --cov-branch --cov-context=test`. This changes only test polling budgets; production deadlines and outcome assertions stay unchanged.

| S04 installed profile | Result |
| --- | --- |
| Python 3.11 / 3.12 ordinary wheels | 130 checks passed on each; CLI, complete protocols, resident continuity and recovery |
| Python 3.11 / 3.12 base sdist | CLI help and independent language execution passed without simulator |
| Packaging-only CI profile | 25 checks passed on each Python version, without core/plugin installed |

[Installation evidence](../docs/evidence/distribution-20261018.json). These are selected installed-profile checks, not a full Python 3.12 suite. Compatible dependency wheels are now available through the authenticated internal prerelease; historical hosted checks are retired; all release validation is performed locally.

## 0.1.1 local acceptance

Fresh Python 3.12 ordinary-wheel profile: **967 passed, 10 optional skips**
(977 collected, 956.69 seconds). Optional Hamilton and paired PyLabRobot profiles
were not installed. The final simulator wheel adds license metadata with all
33 runtime files unchanged. A separate fresh Python 3.11 installation passed
`pip check`, one-shot Transfer and resident readiness/submission/completion/stop.
[Evidence](../docs/evidence/public-preview-011-20261018.json).

The internal-design split adds two packaging exclusion cases. The current
architecture and acceptance-runner subset passes 98 cases both in the checkout
and an extracted sdist. Runtime source remains identical to the full-suite baseline.
