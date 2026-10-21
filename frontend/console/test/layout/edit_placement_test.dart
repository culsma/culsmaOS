import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';
import 'fixture.dart';

class PlacementFixture {
  static Map<String, dynamic> configuration() {
    final c = LayoutData.copy(LayoutFixture.hamiltonProfile()['template']);
    c['carriers'] = <String, dynamic>{};
    c['labware'] = <String, dynamic>{};
    return c;
  }

  static LayoutDefinition definition(Map<String, dynamic> c) =>
      LayoutDefinition(LayoutFixture.hamiltonProfile()['layout'], c);
}

void main() {
  test('all catalogue widths expose exact available track ranges', () {
    const widths = {
      'RGT_CAR_5R60_A00': 1,
      'RGT_CAR_4R200_A00': 2,
      'TIP_CAR_288_HTF_C00': 4,
      'TIP_CAR_288_HTF_B00': 5,
      'CAR_5DWP': 6,
      'CAR_5TIP': 6,
      'PLT_CAR_L5FLEX_MD_A00': 7,
    };
    for (final deck in {'STAR-54': 54, 'STARlet-30': 30}.entries) {
      final c = PlacementFixture.configuration()..['deck_model'] = deck.key;
      final d = PlacementFixture.definition(c);
      for (final model in widths.entries) {
        for (var track = 1; track <= deck.value; track++) {
          expect(
            d.fits(c, model.key, '$track', 'carrier'),
            track + model.value - 1 <= deck.value,
          );
        }
      }
    }
  });

  test(
    'carrier replacement preserves IDs and children but rejects collision or incompatibility',
    () {
      var c = PlacementFixture.configuration();
      final d = PlacementFixture.definition(c);
      c = d.add(c, d.collections.first, 'plates', 'CAR_5DWP', '1');
      final parent = d.items(c).single;
      c = d.placeChild(
        c,
        d.collections.last,
        'source',
        'Ham_DW_Rgt_96_L',
        parent,
        '1',
      );
      final original = LayoutData.canonical(c);
      final changed = d.replaceModel(c, parent, 'PLT_CAR_L5FLEX_MD_A00');
      expect(changed['labware'], c['labware']);
      expect(changed['carriers']['plates']['model'], 'PLT_CAR_L5FLEX_MD_A00');
      expect(
        () => d.replaceModel(c, parent, 'CAR_5TIP'),
        throwsFormatException,
      );
      expect(() => d.remove(c, parent), throwsFormatException);
      c = d.add(c, d.collections.first, 'neighbor', 'RGT_CAR_5R60_A00', '7');
      expect(
        () => d.replaceModel(c, parent, 'PLT_CAR_L5FLEX_MD_A00'),
        throwsFormatException,
      );
      expect(
        d.replacementModels(c, parent).map((m) => m['id']),
        isNot(contains('PLT_CAR_L5FLEX_MD_A00')),
      );
      expect(original, isNot(LayoutData.canonical(c)));
      expect(changed['carriers'].containsKey('neighbor'), isFalse);
    },
  );

  test(
    'reparenting preserves identity and guards occupied or incompatible destinations',
    () {
      var c = PlacementFixture.configuration();
      final d = PlacementFixture.definition(c);
      c = d.add(c, d.collections.first, 'left', 'CAR_5DWP', '1');
      c = d.add(c, d.collections.first, 'right', 'PLT_CAR_L5FLEX_MD_A00', '8');
      c = d.add(c, d.collections.first, 'tips', 'CAR_5TIP', '16');
      final left = d.items(c).firstWhere((i) => i.name == 'left');
      final right = d.items(c).firstWhere((i) => i.name == 'right');
      final tips = d.items(c).firstWhere((i) => i.name == 'tips');
      c = d.placeChild(
        c,
        d.collections.last,
        'source',
        'Ham_DW_Rgt_96_L',
        left,
        '1',
      );
      c = d.placeChild(
        c,
        d.collections.last,
        'destination',
        'Ham_DW_Rgt_96_L',
        right,
        '2',
      );
      final child = d.items(c).firstWhere((i) => i.name == 'source');
      final moved = d.relocateChild(c, child, right, '5');
      expect(moved['labware']['source'], {
        'model': 'Ham_DW_Rgt_96_L',
        'carrier': 'right',
        'site': '5',
      });
      expect(
        () => d.relocateChild(c, child, right, '2'),
        throwsFormatException,
      );
      expect(() => d.relocateChild(c, child, tips, '1'), throwsFormatException);
      expect(() => d.relocateChild(c, left, right, '1'), throwsFormatException);
      expect(() => d.replaceModel(c, child, 'HTF_L'), throwsFormatException);
      final removed = d.remove(moved, child);
      expect(removed['labware'].containsKey('source'), isFalse);
      final parentRemoved = d.remove(removed, left);
      expect(
        () => d.placeChild(
          parentRemoved,
          d.collections.last,
          'new',
          'Ham_DW_Rgt_96_L',
          left,
          '1',
        ),
        throwsFormatException,
      );
      expect(() => d.move(parentRemoved, left, '24'), throwsFormatException);
      expect(d.childDestinations(c, child).length, 9);
    },
  );

  testWidgets('one-track carrier remains selectable without overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1400, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final c = LayoutFixture.controller(
      installedProfile: LayoutFixture.hamiltonProfile(),
    );
    final config = PlacementFixture.configuration();
    config['carriers']['narrow'] = {'model': 'RGT_CAR_5R60_A00', 'track': '1'};
    c.edit(config);
    await tester.pumpWidget(CulsmaConsole(controller: c));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('carrier-narrow')));
    await tester.pumpAndSettle();
    expect(find.text('5-site reagent carrier · 1 track'), findsOneWidget);
    expect(find.text('Compatible labware'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.ensureVisible(find.text('Edit placement'));
    await tester.tap(find.text('Edit placement'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('remove-carriers/narrow')),
    );
    await tester.tap(find.byKey(const ValueKey('remove-carriers/narrow')));
    await tester.pumpAndSettle();
    expect(c.proposal!['carriers'], isEmpty);
    expect(tester.takeException(), isNull);
  });
}
