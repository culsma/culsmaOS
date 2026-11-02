"""Legacy imports remain compatible; execution implementations have moved."""
import ast
from pathlib import Path
from culsma_os.processing_engine.interactors import ProcessingInteractor, MagneticPreparationInteractor
from culsma_os.program_manager.interactors.processing_preparation import ProcessingPreparationInteractor
from culsma_os.program_manager.interactors.magnetic_intents import MagneticPreparationInteractor as ProgramMagnetic
from culsma_os.processing_engine.models import MagneticSeparationIntent
from culsma_os.device_manager.instruments.magnet.models import MagneticSeparationIntent as DeviceMagnetic
from culsma_os.transfer_engine.interactors import TransferInteractor
from culsma_os.program_manager.interactors.transfer_preparation import TransferPreparationInteractor
from tests.support.paths import ROOT


def test_legacy_imports_preserve_type_identity():
    assert ProcessingInteractor is ProcessingPreparationInteractor
    assert MagneticPreparationInteractor is ProgramMagnetic
    assert MagneticSeparationIntent is DeviceMagnetic
    assert TransferInteractor is TransferPreparationInteractor


def test_legacy_engine_modules_contain_only_import_exports():
    for name in ('processing_engine','transfer_engine'):
        for path in (ROOT/'src/culsma_os'/name).rglob('*.py'):
            tree=ast.parse(path.read_text())
            assert not any(isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) for n in ast.walk(tree)), path
