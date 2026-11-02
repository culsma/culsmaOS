"""Persistence port owned by Device Manager; SQLite implementation is in sqlite_repository.py.

Revisions are append-only. save_revision must atomically check expected_revision;
existing runs keep their exact references. No latest-version substitution.
"""
from typing import Protocol
from .models import ModuleProfileDraft, ModuleProfileRevision, ProfileReference


class ModuleProfileRepository(Protocol):
    def list_profiles(self, device_id: str, module_id: str) -> tuple[ModuleProfileRevision, ...]: ...

    def get_revision(self, reference: ProfileReference) -> ModuleProfileRevision: ...

    def save_revision(self, draft: ModuleProfileDraft) -> ModuleProfileRevision: ...
