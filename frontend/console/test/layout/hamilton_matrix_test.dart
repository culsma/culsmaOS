import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';
import 'fixture.dart';

void main() {
  for (final deck in {'STAR-54': 54, 'STARlet-30': 30}.entries) {
    test(
      '${deck.key} offers every legal carrier origin and rejects overhang',
      () {
        final profile = LayoutFixture.hamiltonProfile();
        final configuration = LayoutData.copy(profile['template']);
        configuration['deck_model'] = deck.key;
        configuration['carriers'] = <String, dynamic>{};
        configuration['labware'] = <String, dynamic>{};
        final definition = LayoutDefinition(profile['layout'], configuration);
        for (final model in ['CAR_5DWP', 'CAR_5TIP']) {
          for (var track = 1; track <= deck.value; track++) {
            if (track <= deck.value - 5) {
              final added = definition.add(
                configuration,
                definition.collections.first,
                'carrier',
                model,
                '$track',
              );
              final carrier = definition.items(added).single;
              expect(definition.footprint(carrier), {
                for (var n = track; n < track + 6; n++) '$n',
              });
              expect(definition.destinations(added, carrier).map((p) => p.id), [
                for (var n = 1; n <= deck.value - 5; n++) '$n',
              ]);
            } else {
              expect(
                () => definition.add(
                  configuration,
                  definition.collections.first,
                  'carrier',
                  model,
                  '$track',
                ),
                throwsFormatException,
              );
            }
          }
        }
        expect(configuration['carriers'], isEmpty);
      },
    );
  }

  test('all five compatible racks stay attached when their carrier moves', () {
    final profile = LayoutFixture.hamiltonProfile();
    for (final pair in {
      'CAR_5DWP': 'Ham_DW_Rgt_96_L',
      'CAR_5TIP': 'HTF_L',
    }.entries) {
      var configuration = LayoutData.copy(profile['template']);
      configuration['carriers'] = <String, dynamic>{};
      configuration['labware'] = <String, dynamic>{};
      final definition = LayoutDefinition(profile['layout'], configuration);
      configuration = definition.add(
        configuration,
        definition.collections.first,
        'carrier',
        pair.key,
        '1',
      );
      final parent = definition.items(configuration).single;
      for (var site = 1; site <= 5; site++) {
        configuration = definition.placeChild(
          configuration,
          definition.collections.last,
          'rack_$site',
          pair.value,
          parent,
          '$site',
        );
        expect(
          () => definition.placeChild(
            configuration,
            definition.collections.last,
            'duplicate_$site',
            pair.value,
            parent,
            '$site',
          ),
          throwsFormatException,
        );
      }
      final originalChildren = LayoutData.canonical(configuration['labware']);
      final moved = definition.move(configuration, parent, '49');
      expect(LayoutData.canonical(moved['labware']), originalChildren);
      expect(moved['carriers']['carrier']['track'], '49');
      expect(configuration['carriers']['carrier']['track'], '1');
      expect(
        definition.items(moved).where((i) => i.parent == 'carrier').length,
        5,
      );
    }
  });

  test(
    'nine full carriers occupy STAR-54 without space for another carrier',
    () {
      final profile = LayoutFixture.hamiltonProfile();
      var configuration = LayoutData.copy(profile['template']);
      configuration['carriers'] = <String, dynamic>{};
      configuration['labware'] = <String, dynamic>{};
      final definition = LayoutDefinition(profile['layout'], configuration);
      for (var n = 0; n < 9; n++) {
        final model = n.isEven ? 'CAR_5DWP' : 'CAR_5TIP';
        final rack = n.isEven ? 'Ham_DW_Rgt_96_L' : 'HTF_L';
        configuration = definition.add(
          configuration,
          definition.collections.first,
          'carrier_$n',
          model,
          '${1 + 6 * n}',
        );
        final parent = definition
            .items(configuration)
            .firstWhere((i) => i.name == 'carrier_$n');
        for (var site = 1; site <= 5; site++) {
          configuration = definition.placeChild(
            configuration,
            definition.collections.last,
            'rack_${n}_$site',
            rack,
            parent,
            '$site',
          );
        }
      }
      expect(definition.items(configuration).length, 54);
      for (final position in definition.positions) {
        expect(definition.occupant(configuration, position.id), isNotNull);
        expect(
          definition.fits(configuration, 'CAR_5DWP', position.id, 'carrier'),
          isFalse,
        );
      }
      configuration['deck_model'] = 'STARlet-30';
      final smaller = LayoutDefinition(profile['layout'], configuration);
      // Changing the platform must not silently remove the user's placements.
      expect(smaller.items(configuration).length, 54);
      final outside = smaller
          .items(configuration)
          .firstWhere((i) => i.name == 'carrier_8');
      expect(smaller.destinations(configuration, outside), isEmpty);
    },
  );
}
