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

Run `python -m pytest tests/modules/program_manager -q` for an owning module, or `python -m pytest -q` for the full suite. Optional external backend requirements are explicit skips. Run acceptance locally; each runner writes fresh evidence to its selected output directory.

For instrumented simulator runs, use:

```sh
CULSMA_OS_TEST_TIMEOUT_MULTIPLIER=3 python -m pytest -q --cov=culsma_os --cov-branch --cov-context=test
```

This changes test polling budgets only; production deadlines and outcome assertions stay unchanged. Execution coverage alone does not prove assertion quality. Historical validation snapshots are maintained outside the public source tree.
