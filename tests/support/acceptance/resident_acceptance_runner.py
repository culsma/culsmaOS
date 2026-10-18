"""An acceptance gate cannot pass when cases, inputs or audit evidence are missing."""

from tests.support.paths import ROOT
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from tests.acceptance.resident import ResidentAcceptanceSuite


class ResidentRunnerFixture:
    def suite(self, directory):
        root = directory/'source'; root.mkdir()
        content = (ROOT/'design/resident-acceptance-suite.json').read_bytes()
        path = root/'design/resident-acceptance-suite.json'; path.parent.mkdir(); path.write_bytes(content)
        manifest = json.loads(content)
        inputs = {*manifest['inputs'], *(g['selector'].split('::')[0] for g in manifest['groups'])}
        for relative in inputs:
            target = root/relative; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/relative).read_bytes())
        return ResidentAcceptanceSuite(root)

    def xml(self, suite, path):
        root = ET.Element('testsuites'); tests = ET.SubElement(root,'testsuite')
        for classname, name in sorted(suite.expected()):
            ET.SubElement(tests,'testcase',classname=classname,name=name,time='0.01')
        ET.ElementTree(root).write(path)

    def execute(self, suite, output):
        self.xml(suite,output/'pytest.xml')
        for i in range(suite.manifest['expected_audit_bundles']):
            path = output/'cases'/str(i)/'resident-protocol-audit.json'; path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'scenario':'unit-fixture','runs':[{}],'station':{}}))
        return 0
