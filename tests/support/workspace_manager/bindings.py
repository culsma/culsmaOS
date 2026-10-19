from copy import deepcopy
from culsma_os.workspace_manager.interactors import ProgramBindingInteractor, StationConfigurationInteractor
from culsma_os.workspace_manager.models import ProgramBindingRequest, StationConfigurationRequest
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository
from tests.support.program_manager.console_program import ProgramCommandFixture


class BindingProfileFixture:
    def validate(self, driver, configuration):
        valid = configuration.get('valid',True)
        return {'valid':valid,'diagnostics':[] if valid else [{'code':'TEST_PROFILE_INVALID'}]}

    def program_bindings(self, driver, configuration):
        return deepcopy(configuration.get('bindings'))


class ProgramBindingFixture:
    def __init__(self, directory):
        self.programs = ProgramCommandFixture(directory)
        self.repository = SqliteStationConfigurationRepository(directory/'drafts.sqlite3')
        self.profiles = BindingProfileFixture()
        self.drafts = StationConfigurationInteractor(self.programs.tokens,self.repository,self.profiles)
        self.interactor = ProgramBindingInteractor(self.programs.tokens,self.repository,self.profiles,self.programs.source_interactor)
        self.configuration = {'bindings':{'entry.s0::alloc':{'labware':'tubes','well':'A1'},
                                          'entry.s1::alloc':{'labware':'tubes','well':'A2'}}}
        self.draft = self.drafts.execute(self.programs.credential,StationConfigurationRequest('create',
            title='Binding test',driver='fixture',configuration=self.configuration))['draft']
        self.snapshot = self.programs.sources.capture()
        self.request = ProgramBindingRequest(self.draft['draft_id'],1,'transfer.culs',self.snapshot.snapshot_id)

    def execute(self, request=None):
        return self.interactor.execute(self.programs.credential,request or self.request)

    def save(self, configuration):
        return self.drafts.execute(self.programs.credential,StationConfigurationRequest('save',self.draft['draft_id'],1,
            'Changed','fixture',configuration))
