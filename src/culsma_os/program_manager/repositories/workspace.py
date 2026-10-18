"""Read the program workspace catalog without compiling or selecting a program."""
import json
from pathlib import Path
from typing import Protocol


class WorkspaceCatalogRepository(Protocol):
    def read(self): ...


class FileWorkspaceCatalogRepository:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        return self.path.resolve().parent, json.loads(self.path.read_text(encoding='utf-8'))
