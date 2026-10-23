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
