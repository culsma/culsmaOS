from tests.support.paths import ROOT
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import threading
import subprocess
import sys
import time
from uuid import uuid4
import pytest
from culsma_os.bootstrap import OSApplicationFactory, OpentronsSessionFactory
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from tests.support.integration.resident_host import ResidentHarness
from tests.support.workspace_manager.heater_shaker_docking import SOURCE
from tests.support.integration.resident_docking import ROOT, SECOND, DeviceFault, ObservedMotionPort, ObservedMotionFactory, ResidentDockingHarness


def test_fifo_runs_keep_material_and_motion_history_separate(tmp_path):
    probe = ObservedMotionFactory(gate_kind='PreparedTransfer')
    host = ResidentDockingHarness(tmp_path,probe).start()
    try:
        first = host.submit()['run_id']
        assert probe.entered.wait(5)
        second = host.submit(host.second_source)['run_id']
        host.assert_following_untouched(second)
        probe.release.set()
        host.wait(lambda:host.status(second)['status']=='completed')
        host.assert_results(first,second)
        assert len(probe.ports) == 1
        # Shared station consumables are not reset for the second language run.
        assert probe.dispatches[-1]['available_tips'] == 92
    finally: host.stop()
    assert probe.ports[0].session.closed


def test_paused_docked_head_blocks_next_program(tmp_path):
    probe = ObservedMotionFactory(gate_kind='PreparedTemperatureHold')
    host = ResidentDockingHarness(tmp_path,probe).start()
    try:
        first = host.submit()['run_id']
        assert probe.entered.wait(5)
        second = host.submit(host.second_source)['run_id']
        start = time.monotonic()
        assert host.client.execute({'action':'pause','run_id':first})['status'] == 'pending'
        assert time.monotonic()-start < 1
        probe.release.set()
        host.wait(lambda:host.status(first)['status']=='paused')
        host.wait(lambda:host.client.execute({'action':'host-status'})['blocked_run']==first)
        host.assert_following_untouched(second)
        assert len(probe.dispatches) == 3
        assert json.loads(host.rows('os_labware_positions')[0][3])['assay']=='module:heater'
        host.client.execute({'action':'resume','run_id':first})
        host.wait(lambda:host.status(second)['status']=='completed')
        host.assert_results(first,second)
    finally: host.stop()


@pytest.mark.parametrize('fault',['open-before','move-after','heat-stop','shake-stop','unload-after'])
def test_unknown_head_blocks_queue_after_restart(tmp_path, fault):
    probe = ObservedMotionFactory(fault=fault)
    host = ResidentDockingHarness(tmp_path,probe).start()
    try:
        first = host.submit()['run_id']
        second = host.submit(host.second_source)['run_id']
        host.wait(lambda:host.status(first)['status']=='needs_reconciliation')
        host.wait(lambda:host.client.execute({'action':'host-status'})['blocked_run']==first)
        host.assert_following_untouched(second)
        before = list(probe.dispatches)
        host.client.execute({'action':'resume','run_id':first})
        host.wait(lambda:not host.status(first)['pending_controls'])
        assert host.status(first)['status']=='needs_reconciliation'
        assert probe.dispatches == before
        assert host.rows('os_resource_locks')
    finally: host.stop()
    fresh = ObservedMotionFactory()
    restarted = ResidentDockingHarness(tmp_path,fresh).start()
    try:
        restarted.wait(lambda:restarted.client.execute({'action':'host-status'})['blocked_run']==first)
        assert restarted.status(first)['status']=='needs_reconciliation'
        restarted.assert_following_untouched(second)
        assert not fresh.dispatches and not fresh.initial[0]['commands']
        assert restarted.rows('os_resource_locks')
    finally: restarted.stop()


def test_graceful_restart_restores_plate_without_repeating_effects(tmp_path):
    probe = ObservedMotionFactory(gate_kind='PreparedTemperatureHold')
    host = ResidentDockingHarness(tmp_path,probe).start()
    first = host.submit()['run_id']
    assert probe.entered.wait(5)
    second = host.submit(host.second_source)['run_id']
    host.stop()  # Waits for current call, then pauses the head without an automatic unload.
    assert len(probe.dispatches)==3
    fresh = ObservedMotionFactory()
    restarted = ResidentDockingHarness(tmp_path,fresh).start()
    try:
        assert restarted.status(first)['status']=='paused'
        restarted.assert_following_untouched(second)
        assert fresh.initial[0]['positions']['assay']=='module:heater'
        assert not fresh.initial[0]['commands'] and not fresh.dispatches
        restarted.client.execute({'action':'resume','run_id':first})
        restarted.wait(lambda:restarted.status(second)['status']=='completed')
        # The first transfer, initial dock and thermal hold are not replayed.
        owners = {r['attempt_id']:r['run_id'] for r in restarted.attempts()}
        assert [owners[d['attempt_id']] for d in fresh.dispatches] == [first]*3+[second]*6
        assert [d['kind'] for d in fresh.dispatches[:3]] == ['PreparedOrbitalShake','PreparedLabwareMove','PreparedTransfer']
        restarted.assert_results(first,second,probe.dispatches + fresh.dispatches)
        assert fresh.dispatches[-1]['available_tips']==92
    finally: restarted.stop()


def test_cancel_does_not_reset_plate_for_next_program(tmp_path):
    probe = ObservedMotionFactory(gate_kind='PreparedTemperatureHold')
    host = ResidentDockingHarness(tmp_path,probe).start()
    try:
        first = host.submit()['run_id']
        assert probe.entered.wait(5)
        second = host.submit(host.second_source)['run_id']
        host.client.execute({'action':'pause','run_id':first})
        probe.release.set()
        host.wait(lambda:host.status(first)['status']=='paused')
        host.client.execute({'action':'cancel','run_id':first})
        host.wait(lambda:host.status(first)['status']=='cancelled')
        registered = host.status(first)['result']['os']['registered_material']
        assert registered['version']==2
        assert {v['metadata']['label']:v['volume_uL'] for v in registered['state']['containers'].values()} == {'Assay_A1':50,'Stock':50}
        host.wait(lambda:host.status(second)['status']=='failed')
        assert host.status(second)['result']['os']['preflight']['status']=='rejected'
        assert 'MOTION_DESTINATION_OCCUPIED' in json.dumps(host.status(second))
        assert not host.attempts(second) and len(probe.dispatches)==3
        position = host.rows('os_labware_positions')[0]
        assert position[2]==1 and json.loads(position[3])['assay']=='module:heater'
        assert not host.rows('os_resource_locks')
    finally: host.stop()

