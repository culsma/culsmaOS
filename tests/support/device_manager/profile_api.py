"""Actual Hamilton definitions, Auth and SQLite; no mocked method catalogue."""
import pytest
import json
from pathlib import Path
from importlib.metadata import EntryPoint
from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.device_manager.instruments.profile_api import InstrumentProfileInteractor
from culsma_os.device_manager.instruments.sqlite_repository import FileModuleProfileRepository
from culsma_os.driver_framework.interactors import DriverInstrumentMethodInteractor
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor, ConfigurationDraftInteractor
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository
from culsma_os.workspace_manager.models import StationConfigurationRequest


class ProfileAPIFixture:
    def __init__(self, root):
        culsma_driver_hamilton = pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
        driver_root = Path(culsma_driver_hamilton.__file__).resolve().parents[2]
        self.configuration = json.loads((driver_root/'tools/local_console/fixtures/magnetic/device.json').read_text())
        self.tokens = TokenInteractor(SessionCredentialRepository())
        self.credential = 'Bearer ' + self.tokens.issue_automation_session()
        self.repository = SqliteStationConfigurationRepository(root/'drafts.sqlite3')
        self.configurations = StationConfigurationInteractor(self.tokens, self.repository, None)
        self.draft = self.configurations.execute(self.credential, StationConfigurationRequest(
            'create', title='Static profile test', driver='hamilton-local', configuration=self.configuration))['draft']
        self.methods = DriverInstrumentMethodInteractor([EntryPoint(name='hamilton-local',
            value='culsma_hamilton_os.providers:HamiltonLocalOSDeviceFactory', group='culsma.os_devices')])
        self.profiles = FileModuleProfileRepository(root/'profiles.sqlite3')
        self.owner = InstrumentProfileInteractor(self.tokens, ConfigurationDraftInteractor(self.repository, None),
            self.methods, self.profiles)
        self.context = dict(draft_id=self.draft['draft_id'], configuration_revision=1, device_id=self.configuration['device_id'])
        self.values = dict(**self.context, module_id=self.configuration['execution']['channel']['id'],
            profile_id='gentle-supernatant', method_id='fixed_height_pipetting', definition_revision='1',
            display_name='Supernatant pipetting', parameters={'aspiration_height_mm': 4.0,
                'dispense_height_mm': 5.0, 'liquid_class': self.configuration['execution']['liquid_class']})
