"""Compatibility between one-shot entry points and explicit resident lifetime."""

from pathlib import Path
import json
import sqlite3
import sys
import pytest
from culsma import cli as language_cli
from culsma_os.bootstrap import OSApplicationFactory, HostLeaseFactory
from culsma_os.cli import CulsmaOSCLI
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from tests.support.common import FakeSessionFactory, FakeDevicePort, ProgramFixture


class InterruptedDevicePort(FakeDevicePort):
    def execute(self, plan, attempt_id):
        self.executions.append(attempt_id)
        raise KeyboardInterrupt('interrupted after durable execution intent')


class InterruptedSessionFactory(FakeSessionFactory):
    def build(self, context):
        old, *description = super().build(context)
        port = InterruptedDevicePort()
        self.ports[-1] = port
        return (port, *description)
