from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.workspace_manager.interactors import StationConfigurationInteractor
from culsma_os.workspace_manager.repositories.configuration import SqliteStationConfigurationRepository


class OfflineProfileFixture:
    def describe(self):
        return {'profiles':[{'driver':'test-profile','fields':[]}], 'unavailable':[]}

    def validate(self, driver, configuration):
        return {'valid':driver=='test-profile' and configuration.get('valid') is True,
                'diagnostics':[] if configuration.get('valid') else [{'code':'TEST_INVALID','path':'/valid'}],
                'scope':'Static fixture only'}


class ConfigurationFixture:
    def __init__(self, path):
        self.tokens = TokenInteractor(SessionCredentialRepository())
        self.credential = 'Bearer '+self.tokens.issue_console_session()
        self.repository = SqliteStationConfigurationRepository(path)
        self.interactor = StationConfigurationInteractor(self.tokens,self.repository,OfflineProfileFixture())

    def execute(self, request):
        return self.interactor.execute(self.credential,request)
