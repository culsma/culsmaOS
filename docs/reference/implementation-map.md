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
| Native windows, workbar and renderer session client | Flutter console (`frontend/console/lib/features/console/`) |
| Shared console view requests, renderer sessions and display receipts | ConsoleInteraction (`console_interaction/`) |

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

Simulation tip-box replacement is owned by Resource Manager (`SupplyInteractionInteractor` / `SupplyReplacementInteractor`), with station `SqliteSupplyLoadRepository` intents and load baselines. The optional driver `SupplyReplacementPort` supplies inventory and durable receipts. Native `NativeSupplyInteractor` and the three MCP supply tools use the same authorized action. Current support is the explicitly selected Hamilton local model; physical and remote-Agent replacement remain unsupported.
