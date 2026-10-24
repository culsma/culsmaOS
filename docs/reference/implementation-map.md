# Framework implementation map

[Architecture](../../diagrams/readme-overview.svg) · [Component-check catalog](../../tests/architecture/module-map.json) · [Current scope](../../README.md)

| Boundary | Owner |
| --- | --- |
| Compilation and experimental semantics | Independent Culsma language |
| Program admission, frozen workspace, hosted continuation | ProgramManager |
| Centralized execution strategy, FIFO run ownership and operation dispatch | Scheduler / ResourceManager |
| Typed identities and evidence-based material registration | MaterialSystem |
| Physical bindings, positions and motion revisions | WorkspaceManager |
| Liquid/group planning and processing requests | TransferEngine / ProcessingEngine |
| Device capability snapshots and external plugin contracts | DeviceManager / DriverFramework |
| Attempts, evidence, reconciliation and finalization | EventJournal / RecoveryManager / LifecycleManager |

Module packages use Interactor / Repository / Model. Visual functional units do not add package layers. Vendor implementations remain external plugins. MeasurementSystem is reserved.

`ExecutionStrategyInteractor` owns execution-mode selection. The default is
`stepwise`. An explicitly configured `batch` driver receives a privately projected
typed action sequence in one submission. Official Hamilton VENUS simulation passes
two consecutive programs per profile: HiG transport, HHS heat/shake with HiG
centrifugation, and Cytomat incubation. Each pair uses one OS instance and one
combined method per program. Root receipts cover each whole batch;
member records are explicitly derived. Local tests cover unknown-outcome isolation
and recovery without resubmission. Physical commissioning remains separate.

## Transfer validation

Scalar, well-group and restricted multichannel execution retain ordered typed references. Public language group envelopes reach the OS without compiler-level scalar submission. Actual device geometry and capability determine execution waves. Material registration remains per member; shared evidence does not imply per-channel observation.

[Capability matrix](instrument-capability-map.json) · [Acceptance](../../tests/acceptance/manifests/resident.json)
