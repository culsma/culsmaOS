# Tests

| Directory | Ownership |
| --- | --- |
| `modules/<module>/` | The matching `src/culsma_os/<module>/` contract |
| `integration/` | CLI, complete protocols, resident operation and cross-module execution |
| `architecture/` | Dependency boundaries, public text and test layout |
| `acceptance/` | Reproducible runners and runner tests |
| `support/<module>/` | Shared fixtures, fake ports and scenario harnesses; no collected test cases |
| `fixtures/<module>/` | Static input data |

Test cases do not import other test modules. Shared fixtures have explicit imports. `support/paths.py` owns the checkout root, so moving a test does not alter fixture discovery.

Run `python -m pytest tests/modules/program_manager -q` for an owning module, or `python -m pytest -q` for the full suite. Optional external backend requirements are explicit skips. Clean-install readiness remains S04 work.

Measured on Python 3.11: **938 passed, 10 optional skips** across the full measurement and corrected targeted reruns. The initial three failures remain recorded in the [run ledger](../docs/evidence/test-coverage-20261018.json); this is not a single clean full-suite pass.

| Measurement | Observed |
| --- | ---: |
| Statements | 5050 / 5441 (92.81%) |
| Branches | 1262 / 1600 (78.88%) |
| Implemented methods | 568 / 573 |

The five unobserved methods belong to optional Hamilton compilation. The [method index](../docs/evidence/method-coverage-20261018.json) maps each implementation to a measured context and remaining branches. Execution attribution does not prove assertion quality.

For instrumented simulator runs, use `CULSMA_OS_TEST_TIMEOUT_MULTIPLIER=3 python -m pytest -q --cov=culsma_os --cov-branch --cov-context=test`. This changes only test polling budgets; production deadlines and outcome assertions stay unchanged.
