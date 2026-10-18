from .repository import WorkspaceInspectionRepository
from hashlib import sha256
import json
from culsma.runtime.material.args import arg_string
from culsma.domains.labware import PlateGeometry
from .models import ResolvedContainerRef, LayoutSnapshot, SpaceBinding, WorkspaceAddress, ProgramWorkspacePort
from .repository import SpaceRepository, LabwarePositionRepository


class SpaceInteractor:

    def __init__(self, repository: SpaceRepository, configured_positions, well_capacities, labware_geometries=None, workspaces: ProgramWorkspacePort | None = None):
        self.repository = repository
        self.positions = configured_positions
        self.capacities = well_capacities
        self.geometries = dict(labware_geometries or {})
        self.workspaces = workspaces

    def bind(self, run_id, material_state, allocation_steps=()):
        snapshot = self.preview(run_id, material_state, allocation_steps)
        self.repository.put(snapshot)
        return snapshot

    def preview(self, run_id, material_state, allocation_steps=()):
        declarations = {}
        for step in allocation_steps:
            if step.op != "AllocContainer" or step.step_id in declarations:
                raise ValueError("WORKSPACE_ALLOCATION_DECLARATION_INVALID")
            declarations[step.step_id] = step
        workspace = self.program_workspace(run_id)
        positions = self.configured_positions(workspace)
        bindings = tuple(
            self.resolve_binding(identity, container, declarations, material_state, positions)
            for identity, container in material_state.get("containers", {}).items()
        )
        self.validate_carriers(bindings)
        payload = []
        for b in bindings:
            value = (b.reference.container_id, b.labware, b.well, b.capacity_uL)
            if b.carrier_id is not None:
                value += (b.carrier_namespace, b.carrier_id, b.carrier_position, b.carrier_geometry)
            if b.carrier_instance_id is not None:
                value += (b.carrier_instance_id,)
            payload.append(value)
        if workspace is not None:
            payload.append(('workspace', workspace['id'], workspace['plan_fingerprint']))
        revision = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return LayoutSnapshot(run_id, revision, bindings)

    def resolve_binding(self, identity, container, declarations, material_state=None, positions=None):
        metadata = container.get("metadata", {})
        kind = metadata.get("kind")
        if kind not in {"tube", "well"}:
            raise ValueError("WORKSPACE_CONTAINER_KIND_UNSUPPORTED")
        allocation = metadata.get("allocation_step_id")
        if allocation is None:
            raise ValueError("WORKSPACE_EXTERNAL_BINDING_UNSUPPORTED")
        address = (self.positions if positions is None else positions).get(allocation)
        if address is None:
            raise ValueError("WORKSPACE_BINDING_MISSING")
        capacity = metadata.get("capacity_uL")
        if capacity is None or (address.labware, address.well) not in self.capacities or capacity > self.capacities[address.labware, address.well]:
            raise ValueError("WORKSPACE_CAPACITY_MISMATCH")
        carrier = namespace = position = geometry = instance = None
        if kind == "well":
            step = declarations.get(allocation)
            if step is None or arg_string(step.args.get("kind")) != "well" or arg_string(step.args.get("carrier_kind")) != "plate":
                raise ValueError("WORKSPACE_WELL_DECLARATION_REQUIRED")
            carrier = arg_string(step.args.get("carrier_id"))
            namespace = arg_string(step.args.get("container_namespace"))
            position = arg_string(step.args.get("carrier_position"))
            if not carrier or not namespace or not position:
                raise ValueError("WORKSPACE_WELL_DECLARATION_REQUIRED")
            geometry = self.declared_geometry(step)
            if self.geometries.get(address.labware) != geometry:
                raise ValueError("WORKSPACE_PLATE_GEOMETRY_UNSUPPORTED")
            PlateGeometry(*geometry).validate_position(position)
            if position != address.well:
                raise ValueError("WORKSPACE_WELL_POSITION_MISMATCH")
            if metadata.get('plate_ref') is not None:
                from culsma.runtime.material.refs import resolve_plate_reference, MaterialReferenceError
                try:
                    reference = resolve_plate_reference(material_state or {}, metadata['plate_ref'])
                except MaterialReferenceError as error:
                    raise ValueError('WORKSPACE_PLATE_REFERENCE_INVALID') from error
                if reference.rows is not None and (reference.rows, reference.cols) != geometry:
                    raise ValueError('WORKSPACE_PLATE_GEOMETRY_UNSUPPORTED')
                instance = reference.id
        return SpaceBinding(ResolvedContainerRef(identity), address.labware, address.well, float(capacity), allocation, carrier, namespace, position, geometry, instance)

    def program_workspace(self, run_id):
        return self.workspaces.workspace_for_run(run_id) if self.workspaces is not None else None

    def configured_positions(self, workspace):
        if workspace is None:
            return self.positions
        allowed = {(a.labware, a.well) for a in self.positions.values()}
        positions = {}
        for step_id, value in workspace['bindings'].items():
            address = WorkspaceAddress(**value)
            if (address.labware, address.well) not in allowed:
                raise ValueError('WORKSPACE_ADDRESS_UNCONFIGURED')
            positions[step_id] = address
        return positions

    def routes(self, run_id, legacy_routes):
        workspace = self.program_workspace(run_id)
        return workspace['routes'] if workspace is not None else legacy_routes

    @staticmethod
    def scope_for_effect(pending):
        suffix = ':' + pending.prepared.runtime_step.step_id
        if not pending.effect_id.endswith(suffix):
            raise ValueError('WORKSPACE_EFFECT_SCOPE_INVALID')
        return pending.effect_id[:-len(suffix)]

    def declared_geometry(self, step):
        dimensions = []
        for name in ("carrier_rows", "carrier_cols"):
            value = step.args.get(name)
            if (not isinstance(value, dict) or value.get("kind") != "IRQuantity"
                    or value.get("unit") is not None):
                raise ValueError("WORKSPACE_PLATE_GEOMETRY_REQUIRED")
            raw = value.get("value")
            if type(raw) not in {int, float} or not 0 < raw < float("inf") or int(raw) != raw:
                raise ValueError("WORKSPACE_PLATE_GEOMETRY_REQUIRED")
            dimensions.append(int(raw))
        return tuple(dimensions)

    def validate_carriers(self, bindings):
        if len({(b.labware, b.well) for b in bindings}) != len(bindings):
            raise ValueError("WORKSPACE_LOCATION_CONFLICT")
        carriers = {}
        physical = {}
        for b in bindings:
            if b.carrier_id is None:
                continue
            key = (('instance', b.carrier_instance_id) if b.carrier_instance_id is not None
                   else ('legacy', b.carrier_namespace, b.carrier_id))
            if key in carriers and carriers[key] != b.labware:
                raise ValueError("WORKSPACE_CARRIER_SPLIT")
            if b.labware in physical and physical[b.labware] != key:
                raise ValueError("WORKSPACE_CARRIER_COLLISION")
            carriers[key] = b.labware
            physical[b.labware] = key

    def get(self, run_id):
        return self.repository.get(run_id)

    def validate_snapshot(self, run_id, revision):
        snapshot = self.get(run_id)
        if snapshot.revision != revision:
            raise ValueError("WORKSPACE_LAYOUT_STALE")
        self.validate_carriers(snapshot.bindings)
        positions = self.configured_positions(self.program_workspace(run_id))
        for b in snapshot.bindings:
            position = positions.get(b.allocation_step_id)
            if position is None or (position.labware, position.well) != (b.labware, b.well):
                raise ValueError("WORKSPACE_LAYOUT_STALE")
            if b.capacity_uL > self.capacities.get((b.labware, b.well), 0):
                raise ValueError("WORKSPACE_CAPACITY_STALE")
            if b.carrier_id is not None and (b.carrier_geometry is None or self.geometries.get(b.labware) != b.carrier_geometry or b.carrier_position != b.well):
                raise ValueError("WORKSPACE_LAYOUT_STALE")

    def locate(self, run_id, reference):
        if not isinstance(reference, ResolvedContainerRef):
            raise TypeError("Typed reference required")
        return next((b for b in self.get(run_id).bindings if b.reference == reference))


class LabwareMotionInteractor:
    """Own carrier mapping and physical placement, never experimental material."""
    def __init__(self, repository: LabwarePositionRepository, space, snapshot, run_store=None):
        from copy import deepcopy
        self.repository, self.space, self.run_store = repository, space, run_store
        self.snapshot = deepcopy(snapshot)
        self.capabilities = self.snapshot.motion_capabilities

    def initialize(self, evidence, reservations):
        import hashlib
        import json
        from pathlib import Path
        if not self.capabilities:
            current = self.repository.get(self.snapshot.device_id)
            if current is not None and current[0] != self.snapshot.configuration_revision:
                raise ValueError('MOTION_CONFIGURATION_MISMATCH')
            return
        with reservations.station_guard():
            attempts = tuple(a for a in evidence.attempts_for_device(self.snapshot.device_id) if self.is_move_attempt(a))
            legacy = self.repository.legacy_position(self.snapshot.device_id)
            registrations = self.repository.legacy_registrations({a.effect_id for a in attempts})
            current = self.repository.get(self.snapshot.device_id)
            if current is None and any(Path(store).resolve() != Path(self.run_store).resolve()
                                       for store in reservations.run_stores()):
                raise ValueError('STATION_WORKSPACE_LEGACY_AMBIGUOUS')
            if legacy is not None:
                if legacy[0] != self.snapshot.configuration_revision:
                    raise ValueError('MOTION_CONFIGURATION_MISMATCH')
                self.validate_legacy(legacy, registrations, attempts, evidence)
                digest = hashlib.sha256(json.dumps([legacy, registrations], sort_keys=True).encode()).hexdigest()
                self.repository.adopt(self.snapshot.device_id, legacy, registrations, digest)
            elif registrations:
                raise ValueError('STATION_WORKSPACE_LEGACY_INCOMPLETE')
            self.repository.initialize(self.snapshot.device_id, self.snapshot.configuration_revision,
                                       self.capabilities['initial_locations'])
            self.positions()  # Configuration must match the shared registry.
            for attempt in attempts:
                fact = evidence.find_evidence(attempt.effect_id)
                if self.registered(attempt.effect_id, fact) or fact is not None and fact.outcome == 'rejected':
                    continue
                self.record_intent(attempt, fact)

    def record_intent(self, attempt, evidence=None):
        from dataclasses import asdict
        if not self.is_move_attempt(attempt):
            raise ValueError('MOTION_ATTEMPT_INVALID')
        self.repository.record_pending(self.snapshot.device_id, {'attempt': asdict(attempt),
            'run_store': self.run_store,
            'outcome': evidence.outcome if evidence is not None else 'awaiting_evidence'})

    def reject(self, attempt, evidence):
        if (evidence is None or evidence.outcome != 'rejected' or evidence.mode != attempt.mode
                or evidence.run_id != attempt.run_id or evidence.effect_id != attempt.effect_id
                or evidence.attempt_id != attempt.attempt_id):
            raise ValueError('MOTION_REJECTION_UNCONFIRMED')
        self.repository.reject(attempt.effect_id)

    def require_known(self):
        if self.repository.pending(self.snapshot.device_id):
            raise ValueError('STATION_MOTION_UNCONFIRMED')

    def positions(self):
        from copy import deepcopy
        initial = self.capabilities.get("initial_locations", {})
        stored = self.repository.get(self.snapshot.device_id)
        if stored is None:
            return 0, deepcopy(initial)
        configuration, revision, positions = stored
        if configuration != self.snapshot.configuration_revision:
            raise ValueError("MOTION_CONFIGURATION_MISMATCH")
        return revision, positions

    def validate_routes(self, plan, run_id=None):
        from culsma.pipeline.plan_nodes import PlanStepTree
        routes = self.space.routes(run_id, self.capabilities.get("before_steps", {}))
        steps = {s.step_id: s for p in plan.plans for s in PlanStepTree.leaves(p.steps)}
        # A group is a separate execution envelope. This slice does not attach moves inside one.
        scalar = {s.step_id for p in plan.plans for s in p.steps if s.op in {"Mutation", "env_hold", "agit", "sep"}}
        if not isinstance(routes, dict) or set(routes) - scalar:
            raise ValueError("MOTION_ROUTE_STEP_UNSUPPORTED")
        if any(steps[key].op not in {"Mutation", "env_hold", "agit", "sep"} for key in routes):
            raise ValueError("MOTION_ROUTE_STEP_UNSUPPORTED")

    def route_intents(self, pending, allocations, positions, revision, start=0):
        self.require_known()
        from .models import CarrierRef, LabwareMoveIntent
        from copy import deepcopy
        layout = None
        intents = []
        current = deepcopy(positions)
        step = pending.prepared.runtime_step
        run_id = self.space.scope_for_effect(pending)
        routes = self.space.routes(run_id, self.capabilities.get("before_steps", {}))
        for offset, route in enumerate(routes.get(step.step_id, ())[start:]):
            ordinal = start + offset
            if layout is None:
                layout = self.space.preview(run_id, pending.before_material_state, allocations)
            labware, destination = route["labware"], route["destination"]
            candidates = [b for b in layout.bindings if b.labware == labware]
            carriers = {(b.carrier_namespace, b.carrier_id, b.carrier_instance_id) for b in candidates}
            if not candidates or len(carriers) != 1 or any(None in identity[:2] for identity in carriers):
                raise ValueError("MOTION_TYPED_CARRIER_REQUIRED")
            if (labware not in self.capabilities.get("movable_labware", ())
                    or labware not in current or destination not in self.capabilities.get("destinations", ())):
                raise ValueError("MOTION_ROUTE_UNSUPPORTED")
            dock = self.capabilities.get("docks", {}).get(destination)
            if dock is not None and labware not in dock["labware"]:
                raise ValueError("MOTION_DOCK_INCOMPATIBLE")
            if destination in current.values():
                raise ValueError("MOTION_DESTINATION_OCCUPIED")
            carrier = CarrierRef(*next(iter(carriers)))
            intents.append(LabwareMoveIntent(f"{step.step_id}/motion/{ordinal}", carrier, labware,
                current[labware], destination, revision + offset))
            current[labware] = destination
        return tuple(intents), current

    def select_module(self, labware, modules, positions=None):
        if not modules:
            raise ValueError("PROCESSING_MODULE_UNAVAILABLE")
        docks = self.capabilities.get("docks", {})
        if any(f"module:{name}" in docks for name in modules):
            if positions is None:
                self.require_known()
                _, positions = self.positions()
            selected = [name for name in modules if positions.get(labware) == f"module:{name}"]
            if len(selected) != 1:
                raise ValueError("PROCESSING_LABWARE_NOT_DOCKED")
            return selected[0]
        if len(modules) != 1:
            raise ValueError("PROCESSING_MODULE_AMBIGUOUS")
        return modules[0]

    def require_module(self, labware, module, positions=None):
        dock = f"module:{module}"
        if dock not in self.capabilities.get("docks", {}):
            return  # Existing fixed-position profiles preserve their binding contract.
        if positions is None:
            _, positions = self.positions()
        if positions.get(labware) != dock:
            raise ValueError("PROCESSING_LABWARE_NOT_DOCKED")

    def project_move(self, labware, source, destination, projected):
        """Validate a proposed placement without changing registered station state."""
        from copy import deepcopy
        self.require_known()
        revision, positions = projected
        if (labware not in self.capabilities.get("movable_labware", ())
                or positions.get(labware) != source
                or destination not in self.capabilities.get("destinations", ())):
            raise ValueError("MOTION_PROJECTED_ROUTE_INVALID")
        if destination in positions.values():
            raise ValueError("MOTION_DESTINATION_OCCUPIED")
        dock = self.capabilities.get("docks", {}).get(destination)
        if dock is not None and labware not in dock["labware"]:
            raise ValueError("MOTION_DOCK_INCOMPATIBLE")
        after = deepcopy(positions)
        after[labware] = destination
        return revision + 1, after

    def validate_preflight(self, pending, allocations, projected):
        self.require_known()
        revision, positions = projected
        intents, after = self.route_intents(pending, allocations, positions, revision)
        return revision + len(intents), after

    def is_move_attempt(self, attempt):
        return attempt.context.get("description", {}).get("operation_kind") == "labware_move"

    def registered(self, effect_id, evidence=None):
        record = self.repository.registration(effect_id)
        return (record is not None and (evidence is None or
            record["evidence_id"] == evidence.evidence_id and record["effect_id"] == evidence.effect_id))

    def condition_release_intent(self, activation):
        from .models import CarrierRef, LabwareMoveIntent
        self.require_known()
        condition = activation.context["description"]["retained_condition"]
        route = condition["release_motion"]
        labware, source, destination = (route[key] for key in ("labware", "source", "destination"))
        revision, positions = self.positions()
        if (positions.get(labware) != source or destination in positions.values()
                or destination not in self.capabilities.get("destinations", ())
                or destination.startswith("module:")
                or labware not in self.capabilities.get("movable_labware", ())):
            raise ValueError("PROCESSING_RELEASE_PLACEMENT_INVALID")
        layout = self.space.get(activation.run_id)
        candidates = [b for b in layout.bindings if b.labware == labware]
        carriers = {(b.carrier_namespace, b.carrier_id, b.carrier_instance_id) for b in candidates}
        if not candidates or len(carriers) != 1 or any(None in key[:2] for key in carriers):
            raise ValueError("MOTION_TYPED_CARRIER_REQUIRED")
        return LabwareMoveIntent(f"{activation.effect_id}/condition-release/motion",
            CarrierRef(*next(iter(carriers))), labware, source, destination, revision)

    def validate_completion(self, attempt, evidence):
        if not self.is_move_attempt(attempt):
            raise ValueError('MOTION_ATTEMPT_INVALID')
        desc = attempt.context["description"]
        intent = desc["motion_intent"]
        expected = {key: intent[key] for key in ("step_id", "labware", "source", "destination", "position_revision")}
        if (evidence is None or evidence.outcome != "completed" or evidence.mode != "simulation"
                or evidence.attempt_id != attempt.attempt_id or evidence.run_id != attempt.run_id
                or evidence.effect_id != attempt.effect_id or evidence.payload.get("operation_kind") != "labware_move"
                or evidence.payload.get("request") != expected
                or evidence.payload.get("phases") != {"move": "returned"}
                or (desc.get("required_access") and evidence.payload.get("completed_access") != desc["required_access"])
                or attempt.context["configuration_revision"] != self.snapshot.configuration_revision):
            raise ValueError("MOTION_COMPLETION_UNCONFIRMED")
        return intent

    def validate_legacy(self, position, registrations, attempts, evidence):
        from copy import deepcopy
        current = deepcopy(self.capabilities['initial_locations'])
        indexed = {attempt.effect_id: attempt for attempt in attempts}
        intents = []
        for effect, record in registrations.items():
            attempt = indexed.get(effect)
            if attempt is None:
                raise ValueError('STATION_WORKSPACE_LEGACY_PROOF_MISSING')
            fact = evidence.find_evidence(effect)
            intent = self.validate_completion(attempt, fact)
            if record != {'effect_id': effect, 'evidence_id': fact.evidence_id, 'intent': intent}:
                raise ValueError('STATION_WORKSPACE_LEGACY_PROOF_MISMATCH')
            intents.append(intent)
        ordered = sorted(intents, key=lambda intent: intent['position_revision'])
        if [intent['position_revision'] for intent in ordered] != list(range(position[1])):
            raise ValueError('STATION_WORKSPACE_LEGACY_HISTORY_INCOMPLETE')
        for intent in ordered:
            if current.get(intent['labware']) != intent['source'] or intent['destination'] in current.values():
                raise ValueError('STATION_WORKSPACE_LEGACY_POSITION_MISMATCH')
            current[intent['labware']] = intent['destination']
        if current != position[2]:
            raise ValueError('STATION_WORKSPACE_LEGACY_POSITION_MISMATCH')

    def register(self, attempt, evidence):
        from copy import deepcopy
        self.record_intent(attempt, evidence)
        intent = self.validate_completion(attempt, evidence)
        if self.registered(attempt.effect_id, evidence):
            return
        revision, before = self.positions()
        if revision != intent["position_revision"] or before.get(intent["labware"]) != intent["source"] or intent["destination"] in before.values():
            raise ValueError("MOTION_POSITION_REVISION_CONFLICT")
        after = deepcopy(before)
        after[intent["labware"]] = intent["destination"]
        self.repository.apply(self.snapshot.device_id, self.snapshot.configuration_revision,
            self.capabilities["initial_locations"], revision, after,
            {"effect_id": attempt.effect_id, "evidence_id": evidence.evidence_id, "intent": intent})


class WorkspaceInspectionInteractor:
    def __init__(self, repository: WorkspaceInspectionRepository):
        self.repository = repository

    def inspect(self, device, evidence):
        stored = self.repository.position(device.device_id)
        initial = device.motion_capabilities.get('initial_locations', {})
        revision, positions = (stored[1], stored[2]) if stored else (0, initial)
        status = 'registered' if stored and revision > 0 else ('configured' if initial else 'not_declared')
        reasons = []
        if stored and stored[0] != device.configuration_revision:
            reasons.append('configuration_mismatch')
        registrations = self.repository.registrations()
        for operation in evidence.operations:
            attempt, receipt = operation.attempt, operation.evidence
            description = attempt.context.get('description', {})
            if description.get('operation_kind') != 'labware_move':
                continue
            if receipt is not None and receipt.outcome == 'rejected':
                continue
            record = registrations.get(attempt.effect_id)
            if (receipt is None or receipt.outcome != 'completed' or record is None
                    or record.get('evidence_id') != receipt.evidence_id
                    or record.get('intent') != description.get('motion_intent')
                    or not stored or revision <= description['motion_intent']['position_revision']):
                reasons.append(attempt.effect_id)
        pending = self.repository.pending(device.device_id)
        reasons.extend(record['attempt']['effect_id'] for record in pending)
        return {'status': 'unknown' if reasons else status, 'basis': status,
                'scope': self.repository.scope(device.device_id),
                'pending_motion': [{'run_id': record['attempt']['run_id'], 'effect_id': record['attempt']['effect_id'],
                    'attempt_id': record['attempt']['attempt_id'], 'run_store': record['run_store'],
                    'status': record['outcome']} for record in pending],
                'configuration_revision': stored[0] if stored else device.configuration_revision,
                'revision': revision, 'last_confirmed': positions if stored and revision > 0 else None,
                'configured_initial': initial, 'current': None if reasons or not positions else positions,
                'unresolved_motion': list(dict.fromkeys(reasons))}


class WorkspaceProfileInteractor:
    """Validate program-local bindings/routes without knowing a vendor or device."""
    def validate(self, identity, plan, bindings, routes):
        from copy import deepcopy
        from culsma.pipeline.plan_nodes import PlanStepTree
        if type(identity) is not str or not identity.strip():
            raise ValueError('WORKSPACE_PROFILE_INVALID')
        steps = tuple(s for p in plan.plans for s in PlanStepTree.leaves(p.steps))
        allocations = {s.step_id for s in steps if s.op == 'AllocContainer'}
        if not isinstance(bindings, dict) or set(bindings) != allocations:
            raise ValueError('WORKSPACE_BINDINGS_MISMATCH')
        addresses = set()
        for address in bindings.values():
            if (not isinstance(address, dict) or set(address) != {'labware', 'well'}
                    or any(type(address[k]) is not str or not address[k] for k in ('labware', 'well'))):
                raise ValueError('WORKSPACE_PROFILE_INVALID')
            value = address['labware'], address['well']
            if value in addresses:
                raise ValueError('WORKSPACE_LOCATION_CONFLICT')
            addresses.add(value)
        scalar = {s.step_id for p in plan.plans for s in p.steps if s.op in {'Mutation', 'env_hold', 'agit', 'sep'}}
        if not isinstance(routes, dict) or set(routes) - scalar:
            raise ValueError('WORKSPACE_ROUTE_INVALID')
        labware = {address[0] for address in addresses}
        for moves in routes.values():
            if not isinstance(moves, list) or not moves:
                raise ValueError('WORKSPACE_ROUTE_INVALID')
            for move in moves:
                if (not isinstance(move, dict) or set(move) != {'labware', 'destination'}
                        or any(type(move[k]) is not str or not move[k] for k in move)
                        or move['labware'] not in labware):
                    raise ValueError('WORKSPACE_ROUTE_INVALID')
        return {'schema': 'culsma_run_workspace_v1', 'id': identity,
                'bindings': deepcopy(bindings), 'routes': deepcopy(routes)}
