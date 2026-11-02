"""Real SQLite revisions and immutable payloads, without mocks."""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from culsma_os.device_manager.instruments.models import (
    InstrumentModule, ModuleProfileDraft, ModuleProfileError,
)
from culsma_os.device_manager.instruments.sqlite_repository import SqliteModuleProfileRepository
from culsma_os.device_manager.instruments.values import freeze_value, plain_value


class ProfileRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'profiles.sqlite3'
        self.connection = sqlite3.connect(self.path)
        self.repository = SqliteModuleProfileRepository(self.connection)
        self.module = InstrumentModule('device', 'magnet', 'magnet', 'driver', 'config-1', ('deck',))
        self.draft = ModuleProfileDraft(self.module, 'method', None, 'passive', '1',
                                       'Magnet', {'nested': {'labware': ['plate']}})

    def tearDown(self):
        self.connection.close()
        self.directory.cleanup()

    def test_revision_survives_reopen_and_old_version_is_preserved(self):
        first = self.repository.save_revision(self.draft)
        second = self.repository.save_revision(replace(self.draft, expected_revision=first.reference.revision,
                                                      parameters={'nested': {'labware': ['other']}}))
        with sqlite3.connect(self.path) as connection:
            reopened = SqliteModuleProfileRepository(connection)
            self.assertEqual(reopened.get_revision(first.reference), first)
            self.assertEqual(reopened.list_profiles('device', 'magnet'), (first, second))

    def test_stale_writer_is_rejected_and_transaction_rolls_back(self):
        first = self.repository.save_revision(self.draft)
        with sqlite3.connect(self.path) as other:
            competing = SqliteModuleProfileRepository(other)
            with self.assertRaises(ModuleProfileError) as error:
                competing.save_revision(self.draft)
            self.assertEqual(error.exception.code, 'PROFILE_REVISION_CONFLICT')
            self.assertFalse(other.in_transaction)
        self.assertEqual(self.repository.list_profiles('device', 'magnet'), (first,))

    def test_exact_reference_includes_device_and_module(self):
        saved = self.repository.save_revision(self.draft)
        for ref in (replace(saved.reference, module_id='different'),
                    replace(saved.reference, device_id='different'),
                    replace(saved.reference, revision='missing')):
            with self.subTest(ref=ref), self.assertRaises(ModuleProfileError) as error:
                self.repository.get_revision(ref)
            self.assertEqual(error.exception.code, 'PROFILE_REVISION_NOT_FOUND')

    def test_nested_parameters_are_detached_and_immutable(self):
        source = {'nested': {'labware': ['plate']}}
        draft = replace(self.draft, parameters=source)
        source['nested']['labware'].append('changed')
        saved = self.repository.save_revision(draft)
        self.assertEqual(plain_value(saved.parameters), {'nested': {'labware': ['plate']}})
        with self.assertRaises(TypeError):
            saved.parameters['nested']['labware'] = ()
        with self.assertRaises(TypeError):
            saved.parameters['new'] = 1
        self.assertEqual(self.repository.decode(self.repository.encode(saved)), saved)

    def test_invalid_values_fail_instead_of_becoming_json_extensions(self):
        for value in (float('nan'), float('inf'), object(), {1: 'non-string key'}):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                freeze_value(value)
        self.assertEqual(plain_value(freeze_value({'a': [None, True, 3, 2.5, 'x']})),
                         {'a': [None, True, 3, 2.5, 'x']})

    def test_invalid_identity_and_existing_transaction_do_not_write(self):
        with self.assertRaises(ModuleProfileError):
            self.repository.save_revision(replace(self.draft, profile_id=''))
        self.connection.execute('BEGIN')
        with self.assertRaises(ModuleProfileError) as error:
            self.repository.save_revision(self.draft)
        self.assertEqual(error.exception.code, 'PROFILE_TRANSACTION_ALREADY_OPEN')
        self.assertTrue(self.connection.in_transaction)
        self.connection.rollback()
        self.assertEqual(self.repository.list_profiles('device', 'magnet'), ())
