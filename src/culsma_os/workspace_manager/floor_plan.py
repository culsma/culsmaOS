"""Versioned station geometry for the console, separate from motion calibration."""
import re

from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.device_manager.instruments.station_settings import instrument_identity
from .models import ConfigurationError


KINDS = ("centrifuge", "incubator", "washer", "dispenser", "shaker", "magnet", "temperature", "vortexer", "other")
LEVELS = ("deck", "below", "above")


def valid_request(request):
    action = request.get("action") if isinstance(request, dict) else None
    if action == "read":
        return set(request) == {"action"}
    if action not in ("save", "check", "apply"):
        return False
    keys = {"action", "revision", "configuration_fingerprint"}
    if action == "save":
        keys.add("plan")
    return (set(request) == keys and type(request["revision"]) is int and request["revision"] >= 0
            and isinstance(request["configuration_fingerprint"], str)
            and re.fullmatch(r"[a-f0-9]{64}", request["configuration_fingerprint"]) is not None)


def validate_plan(plan, instruments):
    if not isinstance(plan, dict) or set(plan) not in ({"areas", "equipment"}, {"areas", "equipment", "deck"}):
        raise ValueError("FLOOR_PLAN_INVALID")
    metric = "deck" in plan
    areas, equipment = plan["areas"], plan["equipment"]
    if not isinstance(areas, list) or not isinstance(equipment, list):
        raise ValueError("FLOOR_PLAN_INVALID")

    def number(value):
        return type(value) is int and value.bit_length() <= 53

    def dimensions(rect):
        return all(number(rect.get(k)) and rect[k] > 0 for k in ("width", "height"))

    def overlap(a, b):
        return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
                and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])

    def label(value):
        return isinstance(value, str) and 1 <= len(value.strip()) <= 80

    deck = plan.get("deck", {"width": 100, "height": 100})
    if not isinstance(deck, dict) or set(deck) != {"width", "height"} or not dimensions(deck):
        raise ValueError("FLOOR_PLAN_DECK_INVALID")
    reserved = [{"x": 0, "y": 0, **deck, "level": "deck"}]
    by_area = {}
    for area in areas:
        fields = {"id", "name", "x", "y", "width", "height"}
        if metric:
            fields.add("level")
        if (not isinstance(area, dict) or set(area) != fields
                or not label(area["id"]) or not label(area["name"])
                or any(not number(area[k]) for k in ("x", "y"))
                or not dimensions(area) or area.get("level", "deck") not in LEVELS):
            raise ValueError("FLOOR_PLAN_AREA_INVALID")
        if area["id"] in by_area:
            raise ValueError("FLOOR_PLAN_AREA_DUPLICATE")
        level = area.get("level", "deck")
        if any(other["level"] == level and overlap(area, other) for other in reserved):
            raise ValueError("FLOOR_PLAN_AREA_OVERLAP")
        by_area[area["id"]] = area
        reserved.append({**area, "level": level})
    item_ids, modules, slots = set(), set(), set()
    footprints = {}
    for item in equipment:
        fields = {"id", "name", "kind", "area_id", "x", "y", "instrument", "handoff"}
        if (not isinstance(item, dict)
                or (set(item) != fields and (not metric or set(item) != fields | {"width", "height"}))
                or not label(item["id"]) or not label(item["name"]) or item["kind"] not in KINDS
                or not label(item["area_id"]) or item["area_id"] not in by_area
                or any(not number(item[k]) or item[k] < 0 for k in ("x", "y"))
                or (item["handoff"] is not None and not label(item["handoff"]))):
            raise ValueError("FLOOR_PLAN_EQUIPMENT_INVALID")
        area = by_area[item["area_id"]]
        if "width" in item and not dimensions(item):
            raise ValueError("FLOOR_PLAN_EQUIPMENT_INVALID")
        if (item["x"] + item.get("width", 0) > (area["width"] if metric else 100)
                or item["y"] + item.get("height", 0) > (area["height"] if metric else 100)):
            raise ValueError("FLOOR_PLAN_EQUIPMENT_OUTSIDE")
        slot = (item["area_id"], item["x"], item["y"])
        if item["id"] in item_ids or slot in slots:
            raise ValueError("FLOOR_PLAN_EQUIPMENT_OVERLAP")
        item_ids.add(item["id"])
        slots.add(slot)
        if "width" in item:
            placed = footprints.setdefault(item["area_id"], [])
            if any(overlap(item, other) for other in placed):
                raise ValueError("FLOOR_PLAN_EQUIPMENT_OVERLAP")
            placed.append(item)
        instrument = item["instrument"]
        if instrument is not None:
            if not isinstance(instrument, str) or instrument not in instruments:
                raise ValueError("FLOOR_PLAN_INSTRUMENT_UNAVAILABLE")
            if instrument in modules or item["kind"] != instruments[instrument]["kind"]:
                raise ValueError("FLOOR_PLAN_INSTRUMENT_INVALID")
            modules.add(instrument)


class StationFloorPlanInteractor:
    def __init__(self, repository, configuration, context, snapshot_reader, instrument_settings=None):
        self.repository = repository
        self.configuration = configuration
        self.context = context
        self.snapshot_reader = snapshot_reader
        self.instrument_settings = instrument_settings
        self.catalogue_cache = None

    def catalogue(self):
        if self.catalogue_cache is not None:
            return self.catalogue_cache
        entries = {}
        if self.snapshot_reader is not None and self.context.config_path is not None:
            snapshot = self.snapshot_reader.execute(self.context.config_path)
            advertised = snapshot.instrument_drivers or {}
            for operation, instances in snapshot.processing_capabilities.items():
                candidates = [kind for kind, operations in advertised.items() if operation in operations]
                for module, capability in instances.items():
                    kind = capability.get("instrument_kind")
                    if kind is None and len(candidates) == 1:
                        kind = candidates[0]
                    if kind in KINDS:
                        identity = instrument_identity(snapshot.device_id, module)
                        entry = {"id": identity, "name": module, "kind": kind}
                        if capability.get("instrument_kind") is not None:
                            entries[identity] = entry
                        else:
                            entries.setdefault(identity, entry)
        if self.instrument_settings is not None:
            settings = self.instrument_settings.execute({
                'action': 'read', 'configuration_fingerprint': self.configuration.fingerprint,
            })
            for row in settings['instruments']:
                if row['kind'] in KINDS:
                    entries.setdefault(row['id'], {key: row[key] for key in ('id', 'name', 'kind')})
        self.catalogue_cache = entries
        return entries

    def applied(self):
        state = self.repository.read()
        if state["applied"] is None:
            return None
        return {**state["applied"], "revision": state["applied_revision"],
                "source": "station_floor_plan", "physical_observation": False,
                "configuration_current": state.get("applied_fingerprint") == self.configuration.fingerprint}

    def execute(self, request, require_idle):
        if not valid_request(request):
            raise ValueError("FLOOR_PLAN_REQUEST_INVALID")
        self.configuration.verify(self.context)
        action = request["action"]
        fingerprint = self.configuration.fingerprint
        state = self.repository.read()
        if action != "read":
            if request["configuration_fingerprint"] != fingerprint:
                raise ValueError("HOST_CONFIGURATION_STALE")
            if request["revision"] != state["revision"]:
                raise ValueError("FLOOR_PLAN_REVISION_CONFLICT")
            if action == "save":
                validate_plan(request["plan"], self.catalogue())
                state.update(draft=request["plan"], checked_fingerprint=None)
            elif action == "check":
                validate_plan(state["draft"], self.catalogue())
                state["checked_fingerprint"] = fingerprint
            elif action == "apply":
                if state["checked_fingerprint"] != fingerprint:
                    raise ValueError("FLOOR_PLAN_CHECK_REQUIRED")
                validate_plan(state["draft"], self.catalogue())
                require_idle()
                state.update(applied=state["draft"], applied_revision=state["revision"] + 1,
                             applied_fingerprint=fingerprint, checked_fingerprint=None)
            state = self.repository.save(state)
        return {**state, "configuration_fingerprint": fingerprint, "instruments": list(self.catalogue().values())}


class ConsoleFloorPlanInteractor(AuthorizedInteractor):
    required_capability = "configuration:activate"

    def __init__(self, tokens, resident):
        super().__init__(tokens)
        self.resident = resident

    def perform(self, request):
        if not valid_request(request):
            raise ConfigurationError("FLOOR_PLAN_REQUEST_INVALID")
        try:
            return self.resident.execute({"action": "floor-plan", "floor_plan_request": request})
        except OSError as error:
            raise ConfigurationError("FLOOR_PLAN_HOST_UNAVAILABLE", "unavailable") from error
        except ValueError as error:
            code = str(error)
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) is None:
                code = "FLOOR_PLAN_REJECTED"
            raise ConfigurationError(code, "conflict") from error
