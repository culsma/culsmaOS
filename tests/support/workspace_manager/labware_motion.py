"""Real official Flex simulator integration; motion stays outside language semantics."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import ast
import json
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma.runtime.material.args import arg_string
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER


SOURCE = f'''let p=plate(label="Assay",format="96well",capacity=200uL);
let wells=p[A1:A2];
let stock=tube(label="Stock",capacity=2000uL,load=[{BUFFER}:100uL]);
wells[0] << [stock:50uL];
stock << [wells[0]:20uL];
return wells[0];'''


class MotionFixture:
    def build(self, directory, change=None, source=SOURCE):
        plan = TransferMatrixFixture().compile(source, directory)
        mutations = [s for p in plan.plans for s in p.steps if s.op == "Mutation"]
        raw = {"robot_type":"Flex", "api_level":"2.20", "pipette":"flex_1channel_1000", "mount":"left",
            "tiprack":{"load_name":"opentrons_flex_96_tiprack_1000ul","slot":"D3"},
            "labware":{"assay":{"load_name":"nest_96_wellplate_200ul_flat","slot":"D1"},
                       "stock":{"load_name":"opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap","slot":"C1"}},
            "bindings":{}, "labware_moves":{
                mutations[0].step_id:[{"labware":"assay","destination":"D2"}],
                mutations[1].step_id:[{"labware":"assay","destination":"D1"}]}}
        for s in (s for p in plan.plans for s in p.steps if s.op == "AllocContainer"):
            raw["bindings"][s.step_id] = ({"labware":"assay", "well":arg_string(s.args["carrier_position"])}
                if "carrier_position" in s.args else {"labware":"stock", "well":"A1"})
        if change:
            change(raw)
        path = directory / "deck.json"
        path.write_text(json.dumps(raw))
        from culsma_os.program_manager.models import HostBuildContext
        context = HostBuildContext(directory/"os.sqlite3", "opentrons-simulator", path, directory/"artifacts")
        return plan, context, OSApplicationFactory().build(context)

    def waiting(self, app, plan):
        app.client.start()
        identity = app.client.submit_run(RunRequest(plan, init_state(plan)))
        app.client.lifecycle.runs.advance_ready(identity)
        return identity, app.client.execution.pending(identity)
