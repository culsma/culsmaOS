"""Local console bootstrap use case; never opens a device session."""


class ConsoleSessionInteractor:
    def __init__(self, tokens):
        self.tokens = tokens

    def execute(self):
        return {'schema':'culsma_console_session_v1',
                'access_token':self.tokens.issue_console_session(),
                'scope':'configuration:drafts programs:execute','lifetime':'console_process'}
