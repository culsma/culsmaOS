"""Resident reconfiguration and restart: fake devices, real OS worker lifecycle."""
from dataclasses import replace
import json
from culsma_os.driver_framework.execution_mode import (
    ExecutionMode,SimulationExecutionImplementation,PhysicalExecutionImplementation)
from tests.support.common import FakeSessionFactory
from tests.support.integration.resident_host import ResidentHarness
from tests.support.integration.configuration_activation import activation_payload


class ModeSessionFactory(FakeSessionFactory):
    def __init__(self):
        super().__init__()
        self.snapshots=[]

    def legacy_execution_selection(self, configuration):
        return {'mode':'simulation','simulator':'vendor'}

    def execution_implementations(self):
        return (SimulationExecutionImplementation('vendor','Simulator',self.build_selected),
                PhysicalExecutionImplementation('Hardware',self.build_selected))

    def build_selected(self, context, selection):
        assert all(port.closed for port in self.ports), 'Only one station worker may own devices'
        port,snapshot,positions,capacities,mapper=super().build(context)
        snapshot=replace(snapshot,mode=selection.mode,shared_resources=('fake:gantry',),
            instrument_drivers={'pipetting':('transfer',),'incubator':('thermal_hold',)})
        self.snapshots.append(snapshot)
        return port,snapshot,positions,capacities,mapper


def test_switch_physical_and_restart_preserves_selection_and_device_inventory(tmp_path):
    initial=tmp_path/'initial.json';initial.write_text(json.dumps({
        'execution_selection':{'mode':'simulation','simulator':'vendor'}}))
    sessions=ModeSessionFactory()
    resident=ResidentHarness(tmp_path,sessions,config=initial).start()
    try:
        baseline=sessions.snapshots[-1]
        target={'execution_selection':{'mode':'physical','simulator':None}}
        resident.client.execute(activation_payload(resident,target))
        resident.wait(lambda:resident.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')
        assert sessions.snapshots[-1].mode is ExecutionMode.PHYSICAL
        assert sessions.snapshots[-1].instrument_drivers==baseline.instrument_drivers
        assert sessions.ports[0].closed and not sessions.ports[-1].closed
        assert not any(port.executions for port in sessions.ports)
    finally: resident.stop()
    restarted=ResidentHarness(tmp_path,sessions,config=initial).start()
    try:
        assert sessions.snapshots[-1].mode is ExecutionMode.PHYSICAL
        assert sessions.snapshots[-1].instrument_drivers==baseline.instrument_drivers
        restored=restarted.client.execute({'action':'configuration-status'})
        assert restored['active']['origin']['draft_id']=='test-draft'
        restarted.client.execute(activation_payload(restarted,
            {'execution_selection':{'mode':'simulation','simulator':'vendor'}},'back-to-simulation'))
        restarted.wait(lambda:restarted.client.execute({'action':'configuration-status'})['receipt']['status']=='applied')
        assert sessions.snapshots[-1].mode is ExecutionMode.SIMULATION
        assert sessions.snapshots[-1].instrument_drivers==baseline.instrument_drivers
    finally: restarted.stop()
