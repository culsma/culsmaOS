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

Run `python -m pytest tests/modules/program_manager -q` for an owning module, or `python -m pytest -q` for the full suite. Optional external backend requirements are explicit skips. Coverage and clean-install readiness are separate preparation steps.
