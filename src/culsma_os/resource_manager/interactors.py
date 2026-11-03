from contextlib import contextmanager
from .repository import ResourceRepository, ResourceInspectionRepository
from .models import ExecutionPermit, ResourceConflict, SupplyReplacementPort


class ResourceInteractor:

    def __init__(self, repository: ResourceRepository, consumables, reservations=None):
        self.repository = repository
        self.consumables = consumables
        self.reservations = reservations

    def acquire(self, plan, attempt_id):
        parent = self.reservations.owned(plan.context.run_id) if self.reservations else None
        permit = ExecutionPermit(plan.effect_id, attempt_id, plan.context.resource_ids, parent)
        self.repository.acquire(permit)
        return permit

    def validate_permit(self, permit):
        self.repository.validate(permit)

    def authorize_dispatch(self, permit):
        self.repository.authorize(permit)

    def validate_active_permit(self, permit):
        self.repository.validate_authorized(permit)

    def settle(self, attempt_id, evidence):
        if (
            evidence.outcome in {"completed", "rejected"}
            and evidence.mode == "simulation"
        ):
            self.repository.release(attempt_id)

    def abandon_preparation(self, permit):
        self.repository.abandon_reserved(permit.attempt_id)

    def occupied(self):
        return self.repository.occupied()

    def active_attempts(self):
        return self.repository.active_attempts()

    def require_consumables(self, plan):
        self.consumables.require(
            plan.context.device_id, plan.description["resource_requirements"]
        )


class ConsumableInteractor:
    def __init__(self, device, evidence, loads=None):
        self.device = device
        self.evidence = evidence
        self.loads = loads
        self.simulation_run_id = None

    def require(self, device_id, requirements):
        capacities = self.capacities(device_id)
        consumed = self.current_consumption(device_id)
        if self.loads and any(r['status']=='applying' for r in self.loads.records()):
            raise ValueError('SUPPLY_REPLACEMENT_UNRESOLVED')
        if not isinstance(requirements, dict):
            raise ValueError("OS_RESOURCE_REQUIREMENTS_INVALID")
        for resource, amount in requirements.items():
            if not isinstance(resource, str) or type(amount) is not int or amount < 0:
                raise ValueError("OS_RESOURCE_REQUIREMENTS_INVALID")
            if (
                resource not in capacities
                or consumed.get(resource, 0) + amount > capacities[resource]
            ):
                raise ValueError("OS_CONSUMABLES_INSUFFICIENT")

    def active_loads(self, device_id):
        if getattr(getattr(self.device, 'readiness', None), 'simulation_scope', 'station') == 'run':
            return {}
        values={}
        for row in self.loads.records(device_id) if self.loads else ():
            if row['status']=='applied':values[row['resource_id']]=row
        return values

    def capacities(self, device_id):
        values=dict(self.device.get(device_id).consumable_capacities)
        for key,row in self.active_loads(device_id).items():
            if key in values:values[key]=len(row['positions'])
        return values

    def current_consumption(self,device_id):
        if getattr(getattr(self.device, 'readiness', None), 'simulation_scope', 'station') == 'run':
            if self.simulation_run_id is None:
                return {key:0 for key in self.device.get(device_id).consumable_capacities}
            return self.evidence.known_run_consumption(device_id, self.simulation_run_id)
        totals=self.evidence.known_consumption(device_id);loads=self.active_loads(device_id)
        current={key:totals.get(key,0)-(loads[key]['baseline'] if key in loads else 0)
            for key in self.device.get(device_id).consumable_capacities}
        if any(v<0 for v in current.values()):raise ValueError('SUPPLY_ACCOUNTING_STALE')
        return current

    def restore(self,port,device_id):
        loads=self.active_loads(device_id)
        active={key:value for key,value in loads.items() if key in self.device.get(device_id).consumable_capacities}
        if active:
            restore=getattr(port,'restore_supply_loads',None)
            if restore is None:raise ValueError('SUPPLY_RESTORE_UNSUPPORTED')
            restore(active)
        return self.current_consumption(device_id)


class StationUsageInteractor:
    def __init__(self, repository):
        self.repository = repository

    def record(self, evidence, device_id):
        if evidence.mode != "simulation":
            raise ValueError("STATION_USAGE_MODE_UNSUPPORTED")
        if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in evidence.consumed_resources.items()):
            raise ValueError("STATION_USAGE_INVALID")
        if evidence.consumed_resources:
            self.repository.record_usage(evidence.evidence_id, device_id, evidence.consumed_resources)

    def known(self, device_id, excluded_evidence_ids=()):
        return self.repository.usage(device_id, excluded_evidence_ids)


class RunReservationInteractor:
    def __init__(self, repository, safety, station_id, run_store, device, usage, owner_id=None):
        from uuid import uuid4
        self.repository, self.safety = repository, safety
        self.station_id, self.run_store, self.device = station_id, run_store, device
        self.usage = usage
        self.owner_id = owner_id or str(uuid4())

    def acquire(self, run_id):
        self.safety.require_run(run_id)
        resources = tuple(sorted({f"{self.device.mode}:device:{self.device.device_id}", *self.device.shared_resources}))
        return self.repository.claim(self.station_id, run_id, self.owner_id, self.run_store, resources)

    def owned(self, run_id):
        value = self.repository.get(run_id)
        if value is None or value.status != "active" or value.owner_id != self.owner_id or value.run_store != self.run_store:
            raise ResourceConflict("RUN_OWNER_STALE")
        self.repository.validate_owner(value)
        return value

    @contextmanager
    def run_guard(self, run_id):
        with self.repository.guard():
            value = self.owned(run_id)
            yield value

    @contextmanager
    def permit_guard(self, permit, run_id):
        with self.repository.guard():
            current = self.owned(run_id)
            if permit.run_reservation != current:
                raise ResourceConflict("RUN_OWNER_STALE")
            yield

    def take_over(self, run_id):
        self.safety.require_run(run_id)
        return self.repository.take_over(run_id, self.owner_id, self.run_store)

    def finish(self, run_id):
        with self.run_guard(run_id) as reservation:
            proof = self.safety.release_proof(run_id)
            if proof is None:
                return False
            self.safety.synchronize_usage(run_id)
            self.repository.release_run(reservation, proof)
            return True

    def get(self, run_id):
        return self.repository.get(run_id)

    def release_confirmation(self, run_id):
        from .models import RunReleaseConfirmation
        with self.repository.guard():
            value = self.repository.get(run_id)
            if value is None or value.status != "released" or value.run_store != self.run_store:
                return None
            stored = self.repository.release_proof(run_id)
            current = self.safety.release_proof(run_id)
            if (stored is None or current is None or stored.get("run_id") != run_id
                    or stored.get("mode") != "simulation" or type(stored.get("revision")) is not int
                    or stored.get("evidence_ids") != current["evidence_ids"]
                    or stored.get("reason") != current["reason"]
                    or stored.get("body_outcome", current["body_outcome"]) != current["body_outcome"]):
                return None
            return RunReleaseConfirmation(run_id, value.run_store, value.generation,
                stored["revision"], tuple(stored["evidence_ids"]))

    def released_safely(self, run_id):
        return self.release_confirmation(run_id) is not None

    @contextmanager
    def station_guard(self):
        with self.repository.guard():
            yield

    def run_stores(self):
        return self.repository.run_stores()

    def close(self):
        self.repository.close()


class StationPathInteractor:
    def database_path(self, context):
        import os
        from pathlib import Path
        from hashlib import sha256
        station_id = context.station_id or os.environ.get('CULSMA_OS_STATION_ID', 'local')
        station_root = context.station_root or Path(os.environ.get(
            'CULSMA_OS_STATION_ROOT', str(Path.home() / '.local/state/culsma-os/stations')))
        return station_root / (sha256(station_id.encode()).hexdigest() + '.sqlite3')

    def device_state_directory(self, context):
        from hashlib import sha256
        path = self.database_path(context)
        return path.parent / (path.stem + '-devices') / sha256(context.driver_name.encode()).hexdigest()


class ResourceInspectionInteractor:
    def __init__(self, repository: ResourceInspectionRepository, station):
        self.repository, self.station = repository, station

    def inspect(self):
        if self.station.active:
            return self.observe()
        with self.station:
            return self.observe()

    def observe(self):
        return {'locks': self.repository.locks(), 'permits': self.repository.permits(),
                'station_reservations': self.repository.reservations(),
                'station_locks': self.repository.station_locks(),
                'station_run_stores': self.repository.run_stores(),
                'station_usage': self.repository.usage(), 'supply_loads':self.repository.supply_loads(), **self.repository.accounting()}

    def consumables(self, device, evidence, resources, unresolved):
        totals = dict(evidence.known_consumption)
        local_ids = set(evidence.evidence_ids)
        for record in resources['station_usage']:
            if record['device_id'] == device.device_id and record['evidence_id'] not in local_ids:
                for name, amount in record['consumption'].items():
                    totals[name] = totals.get(name, 0) + amount
        # Parent ownership can span a different run store: do not infer idleness from local attempts alone.
        occupied = bool(resources['permits'] or resources['locks'] or resources['station_reservations']
                        or resources['station_locks'])
        uncertain = bool(unresolved or occupied or evidence.accounting != 'recorded'
                         or resources['local_accounting'] != 'recorded'
                         or resources['station_accounting'] != 'recorded')
        loads={}
        for row in resources.get('supply_loads',[]):
            if row['device_id']==device.device_id and row['status']=='applied':loads[row['resource_id']]=row
        result={}
        for name,capacity in device.consumable_capacities.items():
            load=loads.get(name);baseline=load['baseline'] if load else 0
            loaded=len(load['positions']) if load else capacity
            active=totals.get(name,0)-baseline
            unknown=uncertain or active<0
            if device.mode == 'simulation' and device.simulation_scope != 'station':
                result[name] = {'configured_capacity': capacity, 'known_consumed': totals.get(name, 0),
                    'scope': device.simulation_scope, 'status': 'history_only',
                    'loaded_capacity': None, 'current_load_id': None, 'current_load_consumed': None,
                    'remaining_upper_bound': None, 'available_from_records': None,
                    'guidance': 'Historical consumption across experiments. Read the experiment loading plan for this run; this total is not current stock.'}
                continue
            result[name]={'configured_capacity':capacity,'loaded_capacity':loaded,'known_consumed':totals.get(name,0),
                'current_load_id':load['request_id'] if load else 'initial','current_load_consumed':active,
                'remaining_upper_bound':max(0,loaded-active),
                'available_from_records':None if unknown else max(0,loaded-active),'status':'unknown' if unknown else 'recorded'}
        return result



class SupplyReplacementInteractor:
    """Resident-owned, guarded simulation replacement with durable two-store reconciliation."""
    def __init__(self, repository, guard, port: "SupplyReplacementPort | None", devices):
        self.repository,self.guard,self.port,self.devices=repository,guard,port,devices

    def current(self):
        from .models import SupplyReplacementError
        if self.port is None:return {'supported':False,'reason':'The installed driver has no consumable replacement port.'}
        view=self.port.describe()
        if not view.get('supported'):return view
        records=self.repository.records(view['device_id'])
        applied=[r for r in records if r['status']=='applied' and r['resource_id']==view['resource_id']]
        pending=[r for r in records if r['status']=='applying']
        from hashlib import sha256
        import json
        view={**view,'driver_revision':view['revision'], 'current_load':applied[-1] if applied else None,
              'pending':pending,'history':records}
        view['revision']=sha256(json.dumps({'driver':view['driver_revision'],'last':applied[-1]['request_id'] if applied else None},sort_keys=True).encode()).hexdigest()
        return view

    def require_settled(self):
        if any(r['status']=='applying' for r in self.repository.records()):
            raise ValueError('SUPPLY_REPLACEMENT_UNRESOLVED')

    def baseline(self, view):
        resource=view['resource_id'];device=view['device_id'];report=self.devices.execute()
        row=next((d for d in report['devices'] if d['device_id']==device),None)
        counts=row['consumables'].get(resource) if row else None
        if counts is None or counts.get('status')!='recorded' or type(counts.get('known_consumed')) is not int:
            raise ValueError('SUPPLY_ACCOUNTING_UNAVAILABLE')
        consumed=counts['known_consumed']
        previous=view['current_load']['baseline'] if view['current_load'] else 0
        if consumed-previous!=len(view['stock']['used']):
            raise ValueError('SUPPLY_ACCOUNTING_MISMATCH')
        return consumed

    def execute(self, action, payload, origin, require_idle):
        from .models import SupplyReplacementError
        if action=='show':return self.current()
        with self.guard.guard():
            old=self.repository.get(payload['request_id'])
            if action=='status':
                if old is None:raise SupplyReplacementError('SUPPLY_REQUEST_NOT_FOUND','not_found')
                return self.reconcile(old)
            if old is not None:
                if old['payload']!=payload or old['origin']!=origin:
                    raise SupplyReplacementError('SUPPLY_REQUEST_CONFLICT')
                return self.reconcile(old)
            require_idle()
            self.require_settled()
            view=self.current()
            if not view.get('supported') or view['mode']!='simulation':
                raise SupplyReplacementError('SUPPLY_SIMULATION_REPLACEMENT_UNSUPPORTED')
            if payload['expected_revision']!=view['revision'] or payload['resource_id']!=view['resource_id']:
                raise SupplyReplacementError('SUPPLY_PROFILE_STALE')
            positions=payload['positions']
            if not positions or len(positions)!=len(set(positions)) or not set(positions)<=set(view['position_choices']):
                raise SupplyReplacementError('SUPPLY_POSITIONS_INVALID','invalid_request')
            record={'request_id':payload['request_id'],'payload':payload,'origin':origin,'status':'applying',
                'device_id':view['device_id'],'resource_id':view['resource_id'],'positions':positions,
                'baseline':self.baseline(view),'driver_token':view['stock']['token'],'previous_load':view['stock']['load_id'],
                'source':'simulation_declaration','physical_observation':False,'receipt':None}
            self.repository.insert(record)
            try:
                receipt=self.port.replace(record['request_id'],view['driver_revision'],positions)
                return self.accept_receipt(record,receipt)
            except Exception:
                return record  # Persisted intent retains isolation. Status only reads a receipt.

    def accept_receipt(self, record, receipt):
        if not isinstance(receipt,dict) or receipt.get('request_id')!=record['request_id']:return record
        if receipt.get('status')=='applied':
            if (receipt.get('resource_id')!=record['resource_id'] or receipt.get('positions')!=record['positions']
                    or receipt.get('load_id')!=record['request_id'] or receipt.get('source')!='local_model'
                    or receipt.get('physical_observation') is not False):return record
            return self.repository.settle(record['request_id'],'applied',receipt)
        if receipt.get('status') in {'rejected','not_applied'}:
            return self.repository.settle(record['request_id'],'rejected',receipt)
        return record

    def reconcile(self, record):
        if record['status']!='applying' or self.port is None:return record
        try:receipt=self.port.receipt(record['request_id'],record['driver_token'],record['resource_id'])
        except Exception:return record
        return self.accept_receipt(record,receipt)


from culsma_os.auth.interactors import AuthorizedInteractor


class SupplyInteractionInteractor(AuthorizedInteractor):
    required_capability='consumables:simulate'

    def __init__(self,tokens,resident):
        super().__init__(tokens)
        self.resident=resident

    def perform_authorized(self,caller,request):
        import re
        from dataclasses import asdict
        from .models import SupplyReplacementRequest,SupplyReplacementError
        if not isinstance(request,SupplyReplacementRequest) or request.action not in {'show','replace','status'}:
            raise SupplyReplacementError('SUPPLY_REQUEST_INVALID','invalid_request')
        value=asdict(request)
        if request.action=='show':
            if any(value[k] is not None for k in ['request_id','expected_revision','resource_id','positions']) or request.simulation_acknowledged:
                raise SupplyReplacementError('SUPPLY_REQUEST_INVALID','invalid_request')
        else:
            if not isinstance(request.request_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request.request_id) is None:
                raise SupplyReplacementError('SUPPLY_REQUEST_INVALID','invalid_request')
            if request.action=='replace':
                if (request.simulation_acknowledged is not True or not isinstance(request.expected_revision,str)
                        or re.fullmatch(r'[a-f0-9]{64}',request.expected_revision) is None
                        or not isinstance(request.resource_id,str) or not 1<=len(request.resource_id)<=256
                        or not isinstance(request.positions,list) or not 1<=len(request.positions)<=384
                        or any(not isinstance(p,str) or not 1<=len(p)<=128 for p in request.positions)):
                    raise SupplyReplacementError('SUPPLY_REQUEST_INVALID','invalid_request')
            elif any(value[k] is not None for k in ['expected_revision','resource_id','positions']) or request.simulation_acknowledged:
                raise SupplyReplacementError('SUPPLY_REQUEST_INVALID','invalid_request')
        try:return self.resident.execute({'action':'supply-'+request.action,'supply_change':value,'supply_origin':caller.subject})
        except SupplyReplacementError:raise
        except ValueError as e:
            code=str(e)
            if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) is None:code='SUPPLY_HOST_REJECTED'
            raise SupplyReplacementError(code,'conflict') from e
        except OSError as e:raise SupplyReplacementError('SUPPLY_HOST_UNAVAILABLE','unavailable') from e
        except ValueError as e:
            code=str(e)
            raise SupplyReplacementError(code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) else 'SUPPLY_REQUEST_REJECTED') from e
