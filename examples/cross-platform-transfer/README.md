# Shared Transfer acceptance programs

Each scenario uses one unchanged `.culs` file on both backends. Only the device
configuration and driver name change. Source SHA-256 and compiled-plan SHA-256
are checked in every paired run.

| Program | Purpose |
| --- | --- |
| `scalar.culs` | Two sequential 50 µL transfers; also first/second dispense failures |
| `unequal-column.culs` | Eight independent sources to eight destinations, 20–90 µL |
| `horizontal.culs` | Eight horizontal wells, 20 µL each; also second batch failure |
| `unequal-column-small.culs` | 10–80 µL capability boundary: OT-2 P300 preparation rejects 10 µL |

The group programs use existing public `group` and `series` syntax. One-hot volume
series route each source to one destination; zero quantities produce no device action.
Logical containers are mapped to wells of the same nominal Corning 96-well / 360 µL
plate family. This profile does not test the physical shape of a tube.

The OT-2 profile explicitly selects `p300_single_gen2`; STAR explicitly enables eight
independent channels. This is a fixed profile comparison, not automatic instrument
selection or a benchmark of OT-2 against every possible STAR configuration.

```sh
# From the culsmaOS repository, in an environment containing both plugins:
python tests/acceptance/cross_platform_transfer.py --output-dir /tmp/paired-transfer-run
python -m pytest tests/test_cross_platform_transfer.py -q
```

Use a fresh output directory. Full simulator commands, journaled evidence, registered
states, resource ownership, consumable totals and source hashes are retained per case.
The runner fails if either required backend is unavailable; the optional pytest suite
skips when its dependencies are absent.

Success requires the exact language material state and OS registered state to match
the same language reference. Device batch counts may differ. Injected failures must
retain resource isolation and must not replay in the same session or after restart.

An explicit exception to prefix equality is documented: OT-2 single-channel groups
register confirmed members as they complete; the current STAR collective path commits
only when all internal batches succeed. The paired failure test checks these existing
policies separately. It does not certify a unified group recovery contract.

Simulator output and software trackers are not independent physical measurements.
