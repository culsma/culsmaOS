# Framework implementation map

[Architecture](../../diagrams/abstract-machine-os-functional-units-v1.svg) · [Modules](../module/README.md) · [Component-check catalog](../../tests/architecture/module-map.json) · [Current scope](../../README.md)

| Boundary | Owner |
| --- | --- |
| Compilation and experimental semantics | Independent Culsma language |
| Program admission, frozen workspace, hosted continuation | ProgramManager |
| FIFO run ownership and operation dispatch | Scheduler / ResourceManager |
| Typed identities and evidence-based material registration | MaterialSystem |
| Physical bindings, positions and motion revisions | WorkspaceManager |
| Liquid/group planning and processing requests | TransferEngine / ProcessingEngine |
| Device capability snapshots and external plugin contracts | DeviceManager / DriverFramework |
| Attempts, evidence, reconciliation and finalization | EventJournal / RecoveryManager / LifecycleManager |

Module packages use Interactor / Repository / Model. Visual functional units do not add package layers. Vendor implementations remain external plugins. MeasurementSystem is reserved.

## Transfer validation

Scalar, well-group and restricted multichannel execution retain ordered typed references. Public language group envelopes reach the OS without compiler-level scalar submission. Actual device geometry and capability determine execution waves. Material registration remains per member; shared evidence does not imply per-channel observation.

[Group contracts](../contracts/transfer-group-contracts.json) · [Transfer design](../contracts/transfer-batch-execution.md) · [Capability matrix](instrument-capability-map.json) · [Acceptance](../../tests/acceptance/manifests/resident.json)

Remaining preparation is tracked in the serial [public preview plan](../release/preview-readiness.json). Historical drafts are outside the public source tree.
