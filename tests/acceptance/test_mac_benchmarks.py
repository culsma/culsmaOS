"""Benchmark audit requirements come from the real public Culsma compiler."""
from pathlib import Path
import importlib.util


def load_audit_module():
    path=Path(__file__).resolve().parents[2]/'tools/test_mac_benchmarks.py'
    spec=importlib.util.spec_from_file_location('benchmark_audit',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_audit_describes_named_outputs_and_author_changes_without_rewriting(tmp_path):
    source='''let s=tube(capacity=5000uL,load=[content(kind=formulation,type=buffer,code="BUF"):100uL]);
s.materials.replace({s.materials[0]:content(kind=formulation,type=buffer,code="NEW"):100uL});
let fractions=sep(sample=s,program=centrifuge_program(drive=300g,keep_source="pellet"));
return fractions;'''
    path=tmp_path/'protocol.culs';path.write_text(source);before=path.read_bytes()
    report=load_audit_module().compile_case(path)
    assert report['host_diagnostics']==[]
    assert report['requirements']['named_separation_outputs']==1
    assert report['requirements']['separation_programs']=={'centrifuge_program':1}
    assert report['requirements']['container_kinds']=={'tube':1}
    assert report['requirements']['measurement_operations']=={}
    assert path.read_bytes()==before


def test_audit_reports_unsupported_readout_and_fields_without_inventing_results(tmp_path):
    source='''let s=tube(capacity=5000uL);
with env(thermal=37C,co2=5%,duration=2s) {hold(sample=s);}
let measured=img(sample=s,quantity=fluorescence);return measured;'''
    path=tmp_path/'protocol.culs';path.write_text(source)
    report=load_audit_module().compile_case(path)
    assert report['requirements']['measurement_operations']=={'img':1}
    assert report['requirements']['environment_fields']==['co2','duration','thermal']
    assert [d['operation'] for d in report['host_diagnostics']]==['img']
    assert 'result' not in report


def test_audit_retains_early_semantic_errors_even_when_lowered_plan_has_none(tmp_path):
    source='''let source=tube(capacity=60mL,load=[content(kind=formulation,type=buffer,code="OLD"):100uL]);
let plate1=plate(format="96well",capacity=2000uL);let a=plate1[A1];a << [source:20uL];
a[0].materials.replace({a[0].materials[0]:content(kind=formulation,type=buffer,code="NEW"):20uL});return a;'''
    path=tmp_path/'invalid.culs';path.write_text(source)
    report=load_audit_module().compile_case(path)
    assert any(d['code']=='SEM_MATERIAL_REPLACE_INVALID' and d['severity']=='error' for d in report['language_diagnostics'])
