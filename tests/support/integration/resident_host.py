"""Acceptance of the resident boundary, queue ownership and lifecycle."""

from tests.support.paths import ROOT
from pathlib import Path
import ast
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import uuid4
import pytest
from culsma_os.bootstrap import OSApplicationFactory, HostLeaseFactory
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter, ResidentProtocolAdapter
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from culsma_os.program_manager.repositories.queue import SqliteRunQueueRepository
from culsma_os.program_manager.interactors.run_state import RunStateInteractor
from culsma_os.program_manager.interactors.runs import TaskInteractor
from culsma_os.program_manager.interactors.preparation import PreparationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma_os.program_manager.models import QueueSubmission
from tests.support.common import FakeSessionFactory, FakeDevicePort, ProgramFixture


class GatePort(FakeDevicePort):
    def __init__(self, entered, release, unknown=False, crash=False):
        super().__init__()
        self.entered, self.release, self.unknown, self.crash = entered, release, unknown, crash
        self.calls = 0

    def execute(self, plan, attempt_id):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            if not self.release.wait(10):
                raise RuntimeError('test device gate timed out')
        if self.crash:
            raise KeyboardInterrupt('test worker crash after durable dispatch intent')
        receipt = super().execute(plan, attempt_id)
        if self.unknown:
            receipt['outcome'] = 'unknown'
        return receipt


class GateSessionFactory(FakeSessionFactory):
    def __init__(self, unknown=False, crash=False):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()
        self.unknown, self.crash = unknown, crash

    def build(self, context):
        old, *description = super().build(context)
        port = GatePort(self.entered, self.release, self.unknown, self.crash)
        self.ports[-1] = port
        return (port, *description)


class ResidentHarness:
    def __init__(self, tmp_path, sessions=None, database=None, config=None):
        self.sessions = sessions or FakeSessionFactory()
        self.context = HostBuildContext(database or tmp_path/'os.sqlite3', 'fake', config, tmp_path/'artifacts')
        self.endpoint = Path('/private/tmp')/('culsma-' + uuid4().hex[:16] + '.sock')
        self.settings = ResidentHostSettings(self.context, self.endpoint, 0.01)
        self.errors = []
        self.host = None
        self.thread = threading.Thread(target=self.serve)
        self.client = ResidentClientAdapter(self.endpoint, 3)

    def serve(self):
        try:
            self.host = OSApplicationFactory({'fake':self.sessions}).build_resident_host(self.settings)
            self.host.serve()
        except BaseException as error:
            self.errors.append(error)

    def start(self, expect='ready'):
        self.thread.start()
        self.wait(lambda: self.client.execute({'action':'host-status'})['status'] == expect)
        return self

    def wait_budget(self, seconds):
        try:
            multiplier = int(os.environ.get('CULSMA_OS_TEST_TIMEOUT_MULTIPLIER', '1'))
        except ValueError as error:
            raise ValueError('TEST_TIMEOUT_MULTIPLIER_INVALID') from error
        if not 1 <= multiplier <= 10:
            raise ValueError('TEST_TIMEOUT_MULTIPLIER_INVALID')
        return seconds * multiplier

    def wait(self, predicate, timeout=10):
        deadline = time.monotonic() + self.wait_budget(timeout)
        last = None
        while time.monotonic() < deadline:
            try:
                value = predicate()
                if value:
                    return value
            except (OSError, ValueError) as error:
                last = error
            if self.errors:
                raise self.errors[0]
            time.sleep(0.01)
        raise AssertionError(f'host condition timed out: {last}')

    def submit(self, **kwargs):
        return self.client.execute({'action':'submit','source':str(ProgramFixture.source),**kwargs})

    def status(self, run_id):
        return self.client.execute({'action':'status','run_id':run_id})

    def stop(self):
        if self.thread.is_alive():
            try:
                self.client.execute({'action':'shutdown'})
            finally:
                if hasattr(self.sessions,'release'):
                    self.sessions.release.set()
                self.thread.join(12)
        assert not self.thread.is_alive()
        assert not self.errors
        self.endpoint.with_name(self.endpoint.name + '.host.lock').unlink(missing_ok=True)
