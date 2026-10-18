"""Private wheels must identify immutable sources without changing source semantics."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tomllib

import pytest

from tests.support.paths import ROOT

spec = importlib.util.spec_from_file_location('preview_builder', ROOT / 'tools/build_preview_dependencies.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestPreviewArtifacts:
    def metadata(self):
        return {'distribution': 'example', 'source_version': '1.0.8', 'revision': 'a'*40,
                'artifact_version': '1.0.8+g'+'a'*12}

    def source(self):
        return '[project]\nname="example"\nversion="1.0.8"\ndependencies=["other==1.0.8"]\n[tool.example]\nversion="keep"\n'

    def test_stamp_preserves_dependencies_and_other_version_fields(self):
        original = tomllib.loads(self.source())
        stamped = tomllib.loads(module.PreviewDependencyBuilder().stamp_metadata(self.source(), self.metadata()))
        assert stamped['project'].pop('version') == '1.0.8+g'+'a'*12
        original['project'].pop('version')
        assert stamped == original

    @pytest.mark.parametrize('field,value', [('distribution','wrong'),('source_version','2.0'),('artifact_version','1.0.8')])
    def test_wrong_identity_cannot_be_stamped(self, field, value):
        metadata = {**self.metadata(), field: value}
        with pytest.raises(ValueError, match='PREVIEW_'):
            module.PreviewDependencyBuilder().stamp_metadata(self.source(), metadata)

    def repository(self, tmp_path):
        subprocess.run(['git','init','-q',str(tmp_path)],check=True)
        path = tmp_path/'pyproject.toml';path.write_text(self.source())
        subprocess.run(['git','-C',str(tmp_path),'add','pyproject.toml'],check=True)
        subprocess.run(['git','-C',str(tmp_path),'-c','user.name=Test','-c','user.email=test@example.invalid',
                        'commit','-qm','test(packaging): create immutable fixture'],check=True)
        revision = subprocess.check_output(['git','-C',str(tmp_path),'rev-parse','HEAD'],text=True).strip()
        return {'revision':revision}

    def test_wrong_revision_rejects_before_creating_output(self, tmp_path):
        source=tmp_path/'source';source.mkdir();metadata=self.repository(source)
        output=tmp_path/'wheels'
        with pytest.raises(ValueError,match='PREVIEW_SOURCE_REVISION_MISMATCH'):
            module.PreviewDependencyBuilder().build({'core':source},{'core':{**metadata,'revision':'0'*40}},output)
        assert not output.exists()

    def test_tracked_changes_reject_without_reverting_user_work(self, tmp_path):
        metadata=self.repository(tmp_path);path=tmp_path/'pyproject.toml';path.write_text('user changes')
        with pytest.raises(ValueError,match='PREVIEW_SOURCE_TRACKED_CHANGES'):
            module.PreviewDependencyBuilder().validate_source(tmp_path,metadata)
        assert path.read_text()=='user changes'

    def test_untracked_notes_are_preserved_and_are_not_part_of_git_archive(self, tmp_path):
        metadata=self.repository(tmp_path);path=tmp_path/'private-note.txt';path.write_text('private')
        module.PreviewDependencyBuilder().validate_source(tmp_path,metadata)
        assert path.read_text()=='private'
        names=subprocess.check_output(['git','-C',str(tmp_path),'ls-tree','--name-only','HEAD'],text=True)
        assert 'private-note.txt' not in names

    def test_existing_output_cannot_be_overwritten(self, tmp_path):
        existing=tmp_path/'sentinel';existing.write_text('keep')
        with pytest.raises(ValueError,match='PREVIEW_OUTPUT_MUST_BE_NEW'):
            module.PreviewDependencyBuilder().build({}, {}, tmp_path)
        assert existing.read_text()=='keep'
