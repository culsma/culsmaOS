from culsma_os.auth.interactors import TokenInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.program_manager.interactors.console_program import ConsoleProgramInteractor
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
from tests.support.paths import ROOT


class ProgramCommandFixture:
    def __init__(self, directory, resident=None):
        self.root = directory/'sources';self.root.mkdir()
        self.source = self.root/'transfer.culs'
        self.source.write_text((ROOT/'examples/transfer/transfer.culs').read_text())
        self.sources = FileProgramSourceRepository(self.root,directory/'snapshots')
        self.tokens = TokenInteractor(SessionCredentialRepository())
        self.credential = 'Bearer '+self.tokens.issue_console_session()
        self.calls = []
        self.failure = None
        self.resident = resident or self
        self.interactor = ConsoleProgramInteractor(self.tokens,self.sources,CompilationInteractor(),HostedRuntimeInteractor(),self.resident)

    def execute(self,payload):
        self.calls.append(payload)
        if self.failure: raise self.failure
        return {'run_id':'run-1','accepted':True,'request_id':payload.get('request_id')}
