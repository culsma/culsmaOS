"""The suite must fail closed on incomplete or unsuccessful acceptance execution."""

from tests.support.paths import ROOT
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from tests.acceptance.protocols import ProtocolAcceptanceSuite


class AcceptanceRunnerFixture:
    def suite(self,directory):
        source=directory/'source';source.mkdir()
        manifest=json.loads((ROOT/'tests/acceptance/manifests/protocols.json').read_text())
        target=source/'tests/acceptance/manifests/protocols.json';target.parent.mkdir(parents=True)
        target.write_text(json.dumps(manifest))
        for profile in manifest['profiles']:
            paths=[profile[key] for key in ('program','configuration','expected')]
            paths.extend(case['test'].split('::')[0] for case in profile['cases'])
            for relative in paths:
                path=source/relative;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes((ROOT/relative).read_bytes())
        return ProtocolAcceptanceSuite(source)

    def xml(self,suite,path):
        root=ET.Element('testsuites');tests=ET.SubElement(root,'testsuite')
        for profile in suite.manifest['profiles']:
            for case in profile['cases']:
                classname,method=suite.case_key(case['test'])
                for i in range(case['expected_cases']):
                    name=method if case['expected_cases']==1 else f'{method}[{i}]'
                    ET.SubElement(tests,'testcase',classname=classname,name=name,time='0.1')
        ET.ElementTree(root).write(path)
