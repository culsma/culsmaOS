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

For Hamilton native layout import acceptance, point `CULSMA_OS_TEST_HAMILTON_LAYOUT` at the Test32 revision 2 station layout. The private layout stays outside the distribution. Transfer fixtures live in `tests/fixtures/driver_framework/hamilton/`; the installed driver supplies labware geometry.
A default installed simulator profile skips Hamilton-dependent cases explicitly;
release reports distinguish those skips from separately verified Hamilton integration.

The polling multiplier applies to both in-process and CLI resident harnesses. It does not shorten protocol timings or relax result assertions.
