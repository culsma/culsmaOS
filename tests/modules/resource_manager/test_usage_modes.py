"""Simulation must never consume physical tip inventory, including old stores."""
import sqlite3
import pytest
from culsma_os.resource_manager.repository import SqliteRunReservationRepository


def test_usage_migrates_legacy_records_and_partitions_execution_modes(tmp_path):
    connection = sqlite3.connect(tmp_path / 'station.db')
    connection.execute('CREATE TABLE os_station_usage(evidence_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,consumption TEXT NOT NULL)')
    connection.execute('INSERT INTO os_station_usage VALUES(?,?,?)', ('old', 'hamilton', '{"tips":3}'))
    connection.commit()
    repo = SqliteRunReservationRepository(connection, tmp_path / 'station.lock')
    repo.record_usage('wet-run', 'hamilton', {'tips': 1}, mode='physical')
    repo.record_usage('wet-run', 'hamilton', {'tips': 1}, mode='physical')
    assert repo.usage('hamilton') == {'tips': 3}
    assert repo.usage('hamilton', mode='physical') == {'tips': 1}
    with pytest.raises(ValueError, match='STATION_USAGE_CONFLICT'):
        repo.record_usage('wet-run', 'hamilton', {'tips': 1}, mode='simulation')
    connection.close()


def test_simulated_tip_replacement_does_not_change_physical_stock():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from culsma_os.resource_manager.interactors import ConsumableInteractor
    device = SimpleNamespace(get=lambda _: SimpleNamespace(mode='physical', consumable_capacities={'tips': 10}))
    evidence = Mock(); evidence.known_consumption.return_value = {'tips': 2}
    loads = Mock()
    loads.records.return_value = [{'status': 'applied', 'resource_id': 'tips', 'positions': ['1'], 'baseline': 20},
                                 {'status': 'applying'}]
    stock = ConsumableInteractor(device, evidence, loads)
    assert stock.capacities('hamilton') == {'tips': 10}
    assert stock.current_consumption('hamilton') == {'tips': 2}
    stock.require('hamilton', {'tips': 8})
    with pytest.raises(ValueError, match='OS_CONSUMABLES_INSUFFICIENT'):
        stock.require('hamilton', {'tips': 9})
    loads.records.assert_not_called()


def test_restore_after_tip_rack_change_uses_current_driver_session():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from culsma_os.resource_manager.interactors import ConsumableInteractor
    previous = SimpleNamespace(device_id='hamilton', mode='simulation', consumable_capacities={'B4': 96})
    current = SimpleNamespace(device_id='hamilton', mode='physical', consumable_capacities={'B5': 8})
    device = SimpleNamespace(get=lambda _: previous, configured_snapshot=current)
    evidence = Mock()
    evidence.known_consumption.return_value = {'B4': 10, 'B5': 2}
    stock = ConsumableInteractor(device, evidence)
    assert stock.session_configuration('hamilton') is current
    assert stock.restore(Mock(), 'hamilton') == {'B5': 2}
    evidence.known_consumption.assert_called_once_with('hamilton', mode='physical')
    assert stock.capacities('hamilton') == {'B5': 8}
