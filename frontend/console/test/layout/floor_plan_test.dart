import 'package:culsma_console/features/layout/interactor/floor_plan_controller.dart';
import 'package:culsma_console/features/layout/view/floor_plan_board.dart';
import 'package:culsma_console/features/layout/view/floor_plan_editor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixture.dart';

void main() {
  testWidgets('floor plan labels stay clear of equipment and narrow tracks', (
    tester,
  ) async {
    final washer = <String, dynamic>{
      'id': 'washer',
      'name': 'Tall washer',
      'kind': 'washer',
      'area_id': 'rear',
      'x': 0,
      'y': 0,
      'width': 250,
      'height': 160,
    };
    Future<void> show() => tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FloorPlanBoard(
            plan: {
              'deck': {'width': 600, 'height': 280},
              'areas': [
                {
                  'id': 'rear',
                  'name': 'Rear shelf',
                  'x': 0,
                  'y': -160,
                  'width': 600,
                  'height': 160,
                  'level': 'deck',
                },
              ],
              'equipment': [washer],
            },
            deck: FloorPlanDeck([
              (
                id: 'a',
                label: 'A',
                description: 'Wide track',
                sites: 1,
                rect: const Rect.fromLTWH(0, 0, .15, 1),
              ),
              (
                id: 'b',
                label: 'B',
                description: 'Narrow track',
                sites: 1,
                rect: const Rect.fromLTWH(.15, 0, .012, 1),
              ),
            ]),
          ),
        ),
      ),
    );
    await show();
    final caption = tester.getRect(find.text('Rear shelf'));
    final footprint = tester.getRect(find.byTooltip('Tall washer'));
    expect(caption.left, greaterThan(footprint.right));
    expect(find.text('A'), findsOneWidget);
    expect(find.text('B'), findsNothing);
    expect(find.byTooltip('B · Narrow track'), findsOneWidget);
    washer['width'] = 600;
    await show();
    expect(find.text('Rear shelf'), findsNothing);
    expect(find.byTooltip('Rear shelf'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'add instruments from the chosen position and move an existing placement',
    (tester) async {
      tester.view.physicalSize = const Size(900, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = FloorPlanController(LayoutFixture.controller().api);
      final oldPlan = <String, dynamic>{
        'areas': [
          {
            'id': 'rear',
            'name': 'Rear shelf',
            'x': 0,
            'y': -30,
            'width': 100,
            'height': 30,
          },
        ],
        'equipment': <Map<String, dynamic>>[],
      };
      controller.plan = oldPlan;
      controller.state = {
        'draft': oldPlan,
        'instruments': [
          {'id': 'rotor', 'name': 'Test centrifuge', 'kind': 'centrifuge'},
        ],
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ListenableBuilder(
                listenable: controller,
                builder: (context, _) => FloorPlanEditor(
                  controller: controller,
                  deck: FloorPlanDeck([], const Size(1215, 497)),
                  onApplied: () async {},
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Set deck bounds'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Done'));
      await tester.pumpAndSettle();
      expect(controller.rows('areas').single['width'], 1215);
      expect(controller.rows('areas').single['y'], -149);
      await tester.tap(find.text('Deck level'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Below deck').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Add area'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Done'));
      await tester.pumpAndSettle();
      final lower = controller.rows('areas').last;
      expect(lower['level'], 'below');
      final area = find.byKey(ValueKey("floor-area-${lower['id']}"));
      expect(find.text('Test centrifuge'), findsNothing);
      await tester.tap(area);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Add instrument'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Test centrifuge'));
      await tester.pumpAndSettle();
      expect(find.text('Instrument placement'), findsOneWidget);
      for (final (label, value) in [
        ('Width (mm)', '200'),
        ('Depth (mm)', '180'),
      ]) {
        final field = find.widgetWithText(TextFormField, label);
        await tester.ensureVisible(field);
        await tester.enterText(field, value);
      }
      await tester.tap(find.text('Done'));
      await tester.pumpAndSettle();
      final item = controller.rows('equipment').single;
      expect(item['area_id'], lower['id']);
      expect(item['instrument'], 'rotor');
      expect(item['x'], closeTo(608, 2));
      expect(item['y'], closeTo(249, 2));
      expect(item['width'], 200);

      final tile = find.byKey(ValueKey("floor-instrument-${item['id']}"));
      final destination = tester.getTopLeft(area) + const Offset(70, 38);
      await tester.dragFrom(
        tester.getCenter(tile),
        destination - tester.getCenter(tile),
      );
      await tester.pumpAndSettle();
      final moved = controller.rows('equipment').single;
      expect(moved['id'], item['id']);
      expect(moved['instrument'], 'rotor');
      expect(moved['x'], lessThan(item['x'] as int));
      expect(moved['y'], lessThan(item['y'] as int));
      expect(moved['width'], 200);

      await tester.tap(area);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Add instrument'));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(SimpleDialog),
          matching: find.text('Test centrifuge'),
        ),
        findsNothing,
      );
      await tester.tap(find.text('Centrifuge'));
      await tester.pumpAndSettle();
      for (final label in ['Width (mm)', 'Depth (mm)']) {
        final field = find.widgetWithText(TextFormField, label);
        await tester.ensureVisible(field);
        await tester.enterText(field, '100');
      }
      await tester.tap(find.text('Done'));
      await tester.pumpAndSettle();
      final second = controller.rows('equipment').last;
      expect(second['kind'], 'centrifuge');
      expect(second['instrument'], isNull);
      expect(second['id'], isNot(moved['id']));

      expect(tester.takeException(), isNull);
    },
  );
}
