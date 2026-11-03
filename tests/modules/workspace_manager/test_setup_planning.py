from copy import deepcopy
import pytest
from culsma_os.workspace_manager.interactors import WorkspacePlanningInteractor


class PlanningFixture:
    @staticmethod
    def location(name, well='1', capacity=200, kinds=None, geometry=None):
        return {'labware': name, 'well': well, 'capacity_uL': capacity,
                'kinds': kinds or ['tube'], 'geometry': geometry, 'placement': {'site': name}}

    @staticmethod
    def demand(name, **values):
        return {'allocation_id': name, 'kind': 'tube', 'capacity_uL': 100, **values}

    @staticmethod
    def catalogue(*locations):
        return {'schema': 'culsma_workspace_catalogue_v1', 'locations': list(locations)}


def test_automatic_and_fixed_assignments_share_one_deterministic_planner():
    f = PlanningFixture
    catalogue = f.catalogue(f.location('rack', '1'), f.location('rack', '2'))
    demands = [f.demand('source'), f.demand('target')]
    before = deepcopy((demands, catalogue))
    planner = WorkspacePlanningInteractor()
    automatic = planner.plan(demands, catalogue)
    fixed = planner.plan(demands, catalogue, {'fixed': {'source': {'labware': 'rack', 'well': '2'}}})
    assert automatic['bindings']['source']['well'] == '1'
    assert fixed['bindings'] == {'source': {'labware': 'rack', 'well': '2'}, 'target': {'labware': 'rack', 'well': '1'}}
    assert (demands, catalogue) == before


def test_soft_preferences_can_fall_back_but_fixed_positions_cannot():
    f = PlanningFixture
    planner = WorkspacePlanningInteractor()
    catalogue = f.catalogue(f.location('rack'))
    address = {'labware': 'missing', 'well': '1'}
    result = planner.plan([f.demand('a')], catalogue, {'preferred': {'a': address}})
    assert not result['items'][0]['preferred_satisfied']
    with pytest.raises(ValueError, match='SETUP_NO_FEASIBLE_LOCATION'):
        planner.plan([f.demand('a')], catalogue, {'fixed': {'a': address}})


def test_backtracking_does_not_let_a_flexible_container_block_a_constrained_one():
    f = PlanningFixture
    result = WorkspacePlanningInteractor().plan([f.demand('small'), f.demand('large', capacity_uL=500)],
        f.catalogue(f.location('large', capacity=1000), f.location('small', capacity=200)))
    assert result['bindings']['large']['labware'] == 'large'
    assert result['bindings']['small']['labware'] == 'small'


def test_plate_wells_stay_together_and_distinct_plates_never_share_one_physical_plate():
    f = PlanningFixture
    catalogue = f.catalogue(*[f.location(name, well, kinds=['well'], geometry=[8,12])
                             for name in ['p1','p2'] for well in ['A1','B1']])
    demands = [f.demand('a', kind='well', carrier='plate1', well='A1', geometry=[8,12]),
               f.demand('b', kind='well', carrier='plate1', well='B1', geometry=[8,12]),
               f.demand('c', kind='well', carrier='plate2', well='A1', geometry=[8,12])]
    result = WorkspacePlanningInteractor().plan(demands, catalogue)
    assert result['bindings']['a']['labware'] == result['bindings']['b']['labware']
    assert result['bindings']['c']['labware'] != result['bindings']['a']['labware']
    with pytest.raises(ValueError, match='SETUP_NO_FEASIBLE_LOCATION'):
        WorkspacePlanningInteractor().plan(demands, catalogue, {'fixed': {
            'a': {'labware':'p1','well':'A1'}, 'b': {'labware':'p2','well':'B1'}}})


@pytest.mark.parametrize('fault', ['capacity','duplicate','geometry','kind','unknown-preference','occupied'])
def test_unusable_locations_are_rejected(fault):
    f = PlanningFixture
    demand = f.demand('a')
    catalogue = f.catalogue(f.location('rack'))
    preferences = None
    if fault == 'capacity': catalogue['locations'][0]['capacity_uL'] = 1
    if fault == 'duplicate': catalogue['locations'] *= 2
    if fault == 'geometry': demand.update(kind='well', carrier='plate', well='A1', geometry=[8,12])
    if fault == 'kind': catalogue['locations'][0]['kinds'] = ['well']
    if fault == 'unknown-preference': preferences = {'fixed': {'unknown': {'labware':'rack','well':'1'}}}
    if fault == 'occupied':
        catalogue['locations'][0]['available'] = False
    with pytest.raises(ValueError):
        WorkspacePlanningInteractor().plan([demand], catalogue, preferences)


def test_driver_layout_is_frozen_with_the_same_plan_without_vendor_interpretation():
    f=PlanningFixture
    catalogue=f.catalogue(f.location('rack'))
    catalogue['layout']={'definition':{'schema':'culsma_layout_v1'},'configuration':{'device_specific':'preserved'}}
    result=WorkspacePlanningInteractor().plan([f.demand('a')],catalogue)
    assert result['layout']==catalogue['layout']
    catalogue['layout']['configuration']['device_specific']='changed'
    assert result['layout']['configuration']['device_specific']=='preserved'
    assert 'layout' not in WorkspacePlanningInteractor().plan([f.demand('a')],f.catalogue(f.location('rack')))


def test_configured_preferences_can_be_overridden_and_incompatible_defaults_are_reported():
    f=PlanningFixture
    catalogue=f.catalogue(f.location('rack','1'),f.location('rack','2'))
    catalogue['preferred_bindings']={'a':{'labware':'rack','well':'2'},'another-program':{'labware':'missing','well':'1'}}
    planner=WorkspacePlanningInteractor()
    assert planner.plan([f.demand('a')],catalogue)['bindings']['a']['well']=='2'
    assert planner.plan([f.demand('a')],catalogue,{'preferred':{'a':{'labware':'rack','well':'1'}}})['bindings']['a']['well']=='1'
    catalogue['preferred_bindings']['a']={'labware':'missing','well':'1'}
    fallback=planner.plan([f.demand('a')],catalogue)
    assert fallback['bindings']['a']['well']=='1' and not fallback['items'][0]['preferred_satisfied']


def test_conflict_explains_materials_fixed_address_and_safe_correction():
    from culsma_os.workspace_manager.models import WorkspacePlanningError
    f = PlanningFixture
    address = {'labware': 'rack', 'well': '1'}
    with pytest.raises(WorkspacePlanningError) as caught:
        WorkspacePlanningInteractor().plan([{**f.demand('a'), 'name': 'Stock'}, {**f.demand('b'), 'name': 'Water'}],
            f.catalogue(f.location('rack')), {'fixed': {'a': address, 'b': address}})
    error = caught.value
    assert error.code == 'SETUP_NO_FEASIBLE_LAYOUT'
    assert 'Stock, Water' in str(error) and 'rack / 1' in str(error)
    diagnostic = error.diagnostics[0]
    assert diagnostic['physical_observation'] is False
    assert 'automatic' in diagnostic['action']
    assert [r['name'] for r in diagnostic['items']] == ['Stock', 'Water']


def test_no_location_diagnostic_records_capacity_and_candidates_without_inventing_reason():
    f = PlanningFixture
    from culsma_os.workspace_manager.models import WorkspacePlanningError
    with pytest.raises(WorkspacePlanningError) as caught:
        WorkspacePlanningInteractor().plan([f.demand('stock', capacity_uL=500)], f.catalogue(f.location('small')))
    item = caught.value.diagnostics[0]['items'][0]
    assert item['required_capacity_uL'] == 500 and item['compatible_locations'] == []
    assert '500' in str(caught.value)
