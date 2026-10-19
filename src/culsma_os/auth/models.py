from dataclasses import dataclass


@dataclass(frozen=True)
class CallerContext:
    subject: str
    capabilities: frozenset[str]


class ConsoleAccessError(ValueError):
    def __init__(self, code, kind='unauthenticated'):
        super().__init__(code)
        self.code, self.kind = code, kind
