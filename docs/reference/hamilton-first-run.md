# Hamilton simulation acceptance and instrument readiness

The current milestone is repeatable simulation of realistic, complex protocols.
Use unchanged benchmark modules as acceptance targets and keep reduced cases as
diagnostic fixtures. Run the full baseline, repeated runs on the same station,
and targeted interruptions at meaningful boundaries. Record the execution path,
material and consumables, plate positions, receipts and final resource state.

| Case | Current evidence | Next simulation acceptance |
| --- | --- | --- |
| Benchmark 01, cell transfection | Original source completed in the Hamilton local model. The tube holder is a local model. | Use as the first full-program regression. Repeat on one resident station and check layout, inventory and terminal state. Exercise an interruption during incubation and verify recovery without repeat dispatch. |
| Benchmark 05, magnetic bead immunoprecipitation | Hamilton local tests cover capture, wash, elution and named fractions within the reviewed profile. A separate virtual workflow station completes the declared-concentration variant (113 semantic steps, 83 operations); this does not qualify the original workflow for Hamilton hardware. | Retain both regressions separately. Review temperature, agitation, carrier and transfer requirements before extending the Hamilton profile. |
| Benchmark 04, suspension cell staining | The compiled original contains 24 centrifuge steps. | Build up from a wash cycle to repeated centrifugation, pellet retention and liquid transfer. Check positions, balance constraints represented by the model, and consumable accounting. |
| Benchmark 02, selective plating | The split simulation passed with explicit synthetic evidence and durable handoff. | Keep it as the regression for missing capabilities, rejected receipts, and restart across a handoff. Track native single-program coverage separately. |
| Benchmark 09, double-sided SPRI | Compiles and requires a supplied concentration. | Use after the magnetic baseline to exercise two selection stages and a declared external input. |

Run broad regressions in the local simulator. Use the official VENUS simulator to
cross-check representative new or changed Hamilton methods, layouts and module
routes. Track each result as local model, official simulation or explicit
synthetic workflow evidence. Keep unsupported steps visible in strict device
validation. The 9 modules and 3 composites compile against the current language
checkout. Compilation, simulator completion and instrument results are separate
acceptance outcomes.

## Later instrument acceptance

The current OS/Agent path is accepted for simulation. Workflow simulation is
off by default and its synthetic readouts cannot be used as instrument evidence.
The Agent can admit a hash-pinned method, but it does not confirm physical
completion. The OS also rejects physical device registration and physical
effect resolutions. Enabling the Agent's launch flag alone does not close this
gap.

| Gate | What to verify | Evidence to keep |
| --- | --- | --- |
| Prepare offline | Pick one fixed aqueous transfer method. Freeze the Culsma source, exact HSL/STP/LAY bundle, deck and labware revisions, tip type and liquid class. Check the final bundle in VENUS simulation. | Input identities and hashes, simulation report, expected source and destination. |
| Verify onsite in VENUS | With the instrument owner present, identify the installed VENUS version and the idle instrument. Compare the planned and actual deck, calibration, source, destination, tips and waste. Use the lab's approved aqueous verification method for one transfer. | Operator-verified setup, native run trace, independently checked transfer result. |
| Close the OS path | Add an explicit physical transfer profile, a separate physical receipt bound to the same job, attempt and bundle, and OS material registration based on that receipt. Test lost replies, incomplete traces and restart without redispatch. Review hardware enablement separately. | One accepted device execution and one OS material update. An ambiguous outcome must retain isolation and be reconciled before the next run. |
| Expand | Repeat the aqueous transfer on the same deck, then do three-well dispensing. Qualify plate movement and each adjacent module separately before combining them. | Verified deck and peripheral routes, instrument traces and result checks. |

A VENUS run launched onsite by the operator validates the instrument method.
It counts as an OS-controlled run only when the OS dispatches it and records a
validated physical receipt for that same attempt. Process exit is insufficient.
