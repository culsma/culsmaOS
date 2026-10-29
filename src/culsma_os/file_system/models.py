from dataclasses import dataclass


@dataclass(frozen=True)
class FileReadRequest:
    action: str
    root: str = 'installation'
    path: str = ''
    offset: int = 0


class FileReadError(ValueError):
    def __init__(self,code,kind='invalid_request'):
        super().__init__(code);self.code,self.kind=code,kind
