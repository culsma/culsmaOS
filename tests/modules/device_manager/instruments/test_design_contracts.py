"""Architecture guards for preparation services and remaining planned contracts."""
import ast
import importlib
import inspect
from pathlib import Path
import unittest

from culsma_os.auth.interactors import AuthorizedInteractor
from culsma_os.device_manager.instruments.interactors import (
    ModuleCatalogueInteractor, SaveModuleProfileInteractor,
    ModuleProfileResolutionInteractor,
)


class InstrumentProfileDesignTests(unittest.TestCase):
    instruments = {
        'centrifuge': 'CentrifugeProfileInteractor',
        'temperature': 'TemperatureProfileInteractor',
        'shaker': 'ShakerProfileInteractor',
        'incubator': 'IncubatorProfileInteractor',
        'plate_transport': 'PlateTransportProfileInteractor',
    }

    def test_instrument_signatures_are_concrete_and_share_one_contract(self):
        for name, class_name in self.instruments.items():
            with self.subTest(instrument=name):
                module = importlib.import_module(
                    'culsma_os.device_manager.instruments.' + name + '.interactors')
                cls = getattr(module, class_name)
                self.assertTrue(issubclass(cls, ModuleProfileResolutionInteractor))
                self.assertFalse(inspect.isabstract(cls))
                self.assertEqual(inspect.signature(cls.prepare_step_method),
                                 inspect.signature(ModuleProfileResolutionInteractor.prepare_step_method))
                self.assertIsInstance(cls(None, None), ModuleProfileResolutionInteractor)

    def test_public_use_cases_preserve_fixed_authorization_entry(self):
        for cls in (ModuleCatalogueInteractor, SaveModuleProfileInteractor):
            with self.subTest(use_case=cls.__name__):
                self.assertIs(cls.execute, AuthorizedInteractor.execute)
                self.assertEqual(cls.required_capability, 'configuration:drafts')
                self.assertFalse(inspect.isabstract(cls))

    def test_instrument_imports_preserve_contract_auth_and_storage_ownership(self):
        package = importlib.import_module('culsma_os.device_manager.instruments')
        root = Path(package.__file__).parent
        allowed = {'__future__', 'abc', 'dataclasses', 'typing', 'culsma.pipeline.plan_nodes', 'culsma.common.source', 'culsma_os.auth.interactors',
                   'collections.abc', 'math', 'types', 'json', 'uuid', 'culsma_os.workspace_manager.models', 'culsma_os.driver_framework.models', 'culsma_os.program_manager.models'}
        storage_imports = {'pathlib', 'contextlib', 'sqlite3'}
        for path in root.rglob('*.py'):
            path_allowed = allowed | (storage_imports if path.name == 'sqlite_repository.py' else set()) | ({'re'} if path.name == 'profile_api.py' else set())
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name, path_allowed, str(path))
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    self.assertTrue(node.module in path_allowed or node.module.startswith('culsma_os.device_manager.instruments.'), str(path))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn('CallerContext', [a.name for a in node.names])

    def test_instrument_runtime_imports_use_explicit_owner_boundaries(self):
        package = importlib.import_module('culsma_os.device_manager.instruments')
        planned = Path(package.__file__).parent
        source = planned.parents[1]
        for path in source.rglob('*.py'):
            if path.is_relative_to(planned):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and 'device_manager.instruments' in (node.module or ''):
                    module = node.module
                    # Persistence remains private to Device Manager/composition.
                    composition = module.endswith('.sqlite_repository') and (
                        path.relative_to(source).as_posix() == 'console/providers.py' and {a.name for a in node.names} == {'FileModuleProfileRepository'} or
                        path.relative_to(source).as_posix() == 'bootstrap.py' and {a.name for a in node.names} == {'FileModuleProfileRepository', 'FileRunProfileBindingRepository'})
                    self.assertFalse(module.endswith(('.repository', '.sqlite_repository', '.selection')) and not composition, str(path))
                    if module.endswith('.interactors'):
                        relative = path.relative_to(source).as_posix()
                        self.assertTrue(relative == 'bootstrap.py' or relative.startswith((
                            'program_manager/interactors/', 'scheduler/', 'processing_engine/interactors/', 'driver_framework/interactors.py')), relative)

    def test_device_implementations_do_not_parse_language_or_register_material(self):
        package = importlib.import_module('culsma_os.device_manager.instruments')
        for path in Path(package.__file__).parent.rglob('*.py'):
            if path.name == 'models.py' or path.name == 'execution_models.py':
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('culsma.runtime', 'culsma.pipeline')), str(path))
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, {'apply_step', 'before_material_state', 'runtime_step', 'material_result'}, str(path))


class InstrumentIndependenceTests(unittest.TestCase):
    def test_instrument_modules_do_not_import_each_other_or_engines(self):
        package = importlib.import_module('culsma_os.device_manager.instruments')
        for name in ('magnet', 'pipetting', 'centrifuge', 'temperature', 'incubator', 'shaker', 'plate_transport'):
            path = Path(package.__file__).parent / name / 'interactors.py'
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    self.assertFalse(any(part in module.split('.') for part in
                        ('processing_engine', 'transfer_engine', 'magnet' if name == 'pipetting' else 'pipetting')))


if __name__ == '__main__':
    unittest.main()
