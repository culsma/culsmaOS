import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';
import 'fixture.dart';

void main() {
  test('driver selector chooses different deck definitions', () {
    final p = LayoutFixture.profile();
    final config = LayoutData.copy(p['template']);
    final ot = LayoutDefinition(p['layout'], config);
    config['robot_type'] = 'Flex';
    final flex = LayoutDefinition(p['layout'], config);
    expect(ot.id, isNot(flex.id));
    expect(ot.positions.first.id, '10');
    expect(flex.positions.first.id, 'A1');
    config['robot_type'] = 'unknown';
    expect(() => LayoutDefinition(p['layout'], config), throwsFormatException);
  });
  test(
    'move preserves all unrelated fields and rejects occupied and reserved slots',
    () {
      final c = LayoutFixture.controller();
      final d = c.definition!;
      final original = LayoutData.canonical(c.proposal);
      final tubes = d.items(c.proposal!).firstWhere((i) => i.name == 'tubes');
      final moved = d.move(c.proposal!, tubes, '3');
      expect(moved['labware']['tubes']['slot'], '3');
      expect(moved['bindings'], c.proposal!['bindings']);
      expect(LayoutData.canonical(c.proposal), original);
      for (final target in ['2', '12', 'unknown']) {
        expect(() => d.move(c.proposal!, tubes, target), throwsFormatException);
      }
    },
  );
  test(
    'add uses driver catalogue and guards duplicate names and occupied slots',
    () {
      final c = LayoutFixture.controller();
      final d = c.definition!;
      final collection = d.collections.first;
      final model = d.catalogue(collection, c.proposal!).first['id'];
      final added = d.add(c.proposal!, collection, 'new_plate', model, '3');
      expect(added['labware']['new_plate']['slot'], '3');
      for (final name in ['tubes', '', '../bad']) {
        expect(
          () => d.add(c.proposal!, collection, name, model, '3'),
          throwsFormatException,
        );
      }
      expect(
        () => d.add(c.proposal!, collection, 'new', 'invented-model', '3'),
        throwsFormatException,
      );
      expect(
        () => d.add(c.proposal!, collection, 'new', model, '1'),
        throwsFormatException,
      );
    },
  );
  test('module footprint and nested children are preserved', () {
    final c = LayoutFixture.controller();
    c.proposal!['modules'] = {
      'thermal': {'model': 'thermocyclerModuleV2', 'slot': '7'},
    };
    c.proposal!['labware']['pcr'] = {
      'module': 'thermal',
      'load_name': 'nest_96_wellplate_100ul_pcr_full_skirt',
    };
    final d = c.definition!;
    for (final id in ['7', '8', '10', '11']) {
      expect(d.occupant(c.proposal!, id)!.name, 'thermal');
    }
    final pcr = d.items(c.proposal!).firstWhere((i) => i.name == 'pcr');
    expect(pcr.parent, 'thermal');
    expect(() => d.move(c.proposal!, pcr, '3'), throwsFormatException);
  });
  test('generic position geometry supports tracks without vendor branches', () {
    final p = LayoutFixture.profile();
    final metadata = LayoutData.copy(p['layout']);
    metadata['variants'] = {
      'OT-2': {
        'id': 'fixture-track-v1',
        'label': 'Track fixture',
        'width': 30,
        'height': 10,
        'positions': [
          {
            'id': 'track10',
            'label': 'Track 10',
            'x': 9,
            'y': 0,
            'width': 5,
            'height': 10,
            'accepts': ['labware'],
          },
        ],
      },
    };
    final d = LayoutDefinition(metadata, p['template']);
    expect(d.positions.single.width, 5);
    expect(d.width, 30);
  });
  test('unsupported version and invalid geometry are rejected', () {
    final p = LayoutFixture.profile();
    final meta = LayoutData.copy(p['layout']);
    meta['revision'] = 99;
    expect(() => LayoutDefinition(meta, p['template']), throwsFormatException);
    meta['revision'] = 1;
    meta['variants']['OT-2']['width'] = 0;
    expect(() => LayoutDefinition(meta, p['template']), throwsFormatException);
  });
  test(
    'carrier moves reserve their whole footprint and keep child site bindings',
    () {
      final c = LayoutFixture.controller(
        installedProfile: LayoutFixture.hamiltonProfile(),
      );
      final d = c.definition!;
      final carrier = d
          .items(c.proposal!)
          .firstWhere((i) => i.name == 'plates');
      final targets = d.destinations(c.proposal!, carrier).map((p) => p.id);
      expect(targets, contains('4'));
      expect(
        targets,
        isNot(contains('5')),
      ); // Span would intersect tips at track 10.
      expect(
        targets,
        isNot(contains('50')),
      ); // Six-track footprint exceeds deck.
      final moved = d.move(c.proposal!, carrier, '20');
      expect(moved['labware']['source']['carrier'], 'plates');
      expect(moved['labware']['source']['site'], '1');
      expect(d.occupant(moved, '25')!.name, 'plates');
      expect(
        () => d.add(c.proposal!, d.collections.first, 'new', 'CAR_5DWP', '8'),
        throwsFormatException,
      );
    },
  );
  test(
    'carrier sites reject duplicates, incompatible models and invalid sites',
    () {
      final c = LayoutFixture.controller(
        installedProfile: LayoutFixture.hamiltonProfile(),
      );
      final d = c.definition!;
      final parent = d.items(c.proposal!).firstWhere((i) => i.name == 'plates');
      final childCollection = d.collections.last;
      final placed = d.placeChild(
        c.proposal!,
        childCollection,
        'destination',
        'Ham_DW_Rgt_96_L',
        parent,
        '2',
      );
      expect(placed['labware']['destination']['site'], '2');
      for (final values in [
        ['Ham_DW_Rgt_96_L', '1'],
        ['Ham_DW_Rgt_96_L', '6'],
        ['HTF_L', '2'],
      ]) {
        expect(
          () => d.placeChild(
            c.proposal!,
            childCollection,
            'new',
            values[0],
            parent,
            values[1],
          ),
          throwsFormatException,
        );
      }
      expect(c.canApply, isFalse);
      c.valid = true;
      c.confirmed = true;
      expect(c.canApply, isFalse);
    },
  );
  test('changing declared deck clears a selection that no longer exists', () {
    final c = LayoutFixture.controller(
      installedProfile: LayoutFixture.hamiltonProfile(),
    );
    c.selectPosition('54');
    final updated = LayoutData.copy(c.proposal!);
    updated['deck_model'] = 'STARlet-30';
    c.edit(updated);
    expect(c.selectedPosition, isNull);
    expect(c.proposal!['carriers']['plates']['track'], '1');
  });
}
