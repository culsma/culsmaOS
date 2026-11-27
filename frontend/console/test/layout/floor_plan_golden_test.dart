import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/layout/interactor/floor_plan_controller.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/layout/view/floor_plan_board.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../console/mutation_fixture.dart';
import 'fixture.dart';

class _FloorPlanGoldenApi extends MutationFixtureApi {
  static const floorPlan = {
    'deck': {'width': 1215, 'height': 497},
    'areas': [
      {
        'id': 'rear',
        'name': 'Rear extension',
        'x': 0,
        'y': -400,
        'width': 1215,
        'height': 400,
        'level': 'deck',
      },
      {
        'id': 'left',
        'name': 'Left planning area',
        'x': -360,
        'y': 0,
        'width': 360,
        'height': 497,
        'level': 'deck',
      },
      {
        'id': 'right',
        'name': 'Right extension',
        'x': 1215,
        'y': 0,
        'width': 450,
        'height': 497,
        'level': 'deck',
      },
    ],
    'equipment': [
      {
        'id': 'wash',
        'name': 'BioTek washer',
        'kind': 'washer',
        'area_id': 'rear',
        'x': 65,
        'y': 35,
        'width': 265,
        'height': 320,
        'instrument': null,
        'handoff': 'WA',
      },
      {
        'id': 'spin',
        'name': 'HiG centrifuge',
        'kind': 'centrifuge',
        'area_id': 'rear',
        'x': 400,
        'y': 45,
        'width': 300,
        'height': 305,
        'instrument': 'hig',
        'handoff': 'CE',
      },
      {
        'id': 'hold',
        'name': 'Cytomat incubator',
        'kind': 'incubator',
        'area_id': 'right',
        'x': 36,
        'y': 36,
        'width': 360,
        'height': 348,
        'instrument': 'cytomat',
        'handoff': 'CY',
      },
    ],
  };

  @override
  Future<Map<String, dynamic>> read(String path) async {
    if (path != '/api/v1/station') return super.read(path);
    const tracks = [
      (3, 6, 5),
      (9, 6, 5),
      (15, 6, 5),
      (21, 7, 4),
      (28, 7, 4),
      (35, 1, 5),
      (36, 2, 4),
      (38, 1, 1),
      (39, 1, 1),
      (40, 1, 1),
      (41, 6, 5),
      (47, 6, 5),
    ];
    return {
      'host': {'status': 'ready'},
      'runs': [],
      'layout': {
        'status': 'available',
        'configuration_fingerprint': originalFingerprint,
        'floor_plan': floorPlan,
        'layout': {
          'definition': {
            'schema': 'culsma_layout_instances_v1',
            'objects': [
              for (final (start, span, _) in tracks)
                {
                  'id': 'carrier-$start',
                  'dimensions_mm': [22.5 * span, 497],
                },
            ],
            'diagram': {
              'scene': {
                'label': 'STAR-54 track deck',
                'positions': List.generate(
                  54,
                  (i) => {'id': '${i + 1}', 'label': '${i + 1}'},
                ),
                'carriers': [
                  for (final (start, span, sites) in tracks)
                    {
                      'id': 'carrier-$start',
                      'model': 'Rack $span T',
                      'start': start,
                      'span': span,
                      'sites': List.generate(sites, (i) => '${i + 1}'),
                      'placements': [],
                    },
                ],
              },
            },
          },
          'configuration': {},
        },
      },
    };
  }

  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path == LayoutController.instrumentSettings &&
        body['action'] == 'read') {
      return {
        'configuration_fingerprint': originalFingerprint,
        'instruments': [
          {
            'id': 'pipettor',
            'name': 'Pipettor',
            'kind': 'pipetting',
            'mount': {'kind': 'gantry'},
            'fields': [
              {
                'id': 'aspiration_height_mm',
                'label': 'Aspiration height',
                'unit': 'mm',
                'min': 0,
                'value': 2.5,
              },
            ],
          },
          {
            'id': 'magnet',
            'name': 'Magnetic rack',
            'kind': 'magnet',
            'mount': {
              'kind': 'deck_site',
              'carrier': 'carrier-28',
              'site': '4',
            },
            'details': {
              'Type': 'Passive magnetic rack',
              'Aspiration height (mm)': '2.5',
            },
          },
          {
            'id': 'shaker',
            'name': 'Heater shaker',
            'kind': 'shaker',
            'mount': {
              'kind': 'deck_site',
              'carrier': 'carrier-28',
              'site': '4',
            },
          },

          {
            'id': 'cytomat',
            'name': 'Cytomat incubator',
            'kind': 'incubator',
            'note':
                'The experiment sets the temperature and duration and can override these environment defaults.',
            'fields': [
              for (final (id, label, value) in [
                ('humidity_percent', 'Humidity', 90),
                ('co2_percent', 'CO₂', 5),
                ('o2_percent', 'O₂', 20),
              ])
                {
                  'id': id,
                  'label': label,
                  'unit': '%',
                  'min': 0,
                  'max': 100,
                  'value': value,
                },
            ],
          },
        ],
      };
    }
    if (path != FloorPlanController.endpoint || body['action'] != 'read') {
      return super.command(path, body);
    }
    return {
      'revision': 1,
      'configuration_fingerprint': originalFingerprint,
      'draft': floorPlan,
      'instruments': [
        {'id': 'cytomat', 'name': 'Cytomat incubator', 'kind': 'incubator'},
        {'id': 'hig', 'name': 'HiG centrifuge', 'kind': 'centrifuge'},
        {'id': 'shaker', 'name': 'Heater shaker', 'kind': 'shaker'},
        {'id': 'magnet', 'name': 'Magnetic rack', 'kind': 'magnet'},
        {'id': 'tubes', 'name': 'Tube incubator', 'kind': 'incubator'},
      ],
    };
  }
}

void main() {
  setUpAll(() async {
    await (FontLoader('Console')
          ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
          ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf')))
        .load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });

  for (final size in [const Size(1100, 844), const Size(390, 760)]) {
    final width = size.width.toInt();
    testWidgets('floor plan page and dialogs at ${width}px', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final layout = LayoutFixture.controller();
      final console = NativeConsoleInteractor(
        _FloorPlanGoldenApi(),
        layout,
        mutations: MemoryConsoleMutationRepository(),
        initialView: 'settings',
      );
      const root = Key('floor-plan-golden');
      await console.refresh();
      await tester.pumpWidget(
        RepaintBoundary(
          key: root,
          child: CulsmaConsole(controller: layout, console: console),
        ),
      );
      await tester.pumpAndSettle();

      Future<void> capture(String name) async {
        expect(tester.takeException(), isNull);
        await expectLater(
          find.byKey(root),
          matchesGoldenFile('../goldens/floor-plan-$name-$width.png'),
        );
      }

      Future<void> open(Finder control) async {
        expect(control, findsOneWidget);
        await tester.ensureVisible(control);
        await tester.pumpAndSettle();
        await tester.tapAt(tester.getCenter(control));
        await tester.pumpAndSettle();
        expect(find.byType(AlertDialog), findsOneWidget);
        expect(
          find.widgetWithText(FilledButton, 'Done').hitTestable(),
          findsOneWidget,
        );
      }

      Future<void> close() async {
        await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
        await tester.pumpAndSettle();
        expect(find.byType(AlertDialog), findsNothing);
      }

      await capture('settings');
      final board = find.byType(FloorPlanBoard);
      expect(find.text('Devices'), findsNothing);
      expect(
        find.widgetWithText(ActionChip, 'Cytomat incubator'),
        findsNothing,
      );
      expect(find.widgetWithText(ActionChip, 'Magnetic rack'), findsNothing);
      expect(find.text('Tube incubator'), findsNothing);

      Future<void> tapOnBoard(String key) async {
        final target = find.descendant(
          of: board,
          matching: find.byKey(ValueKey(key)),
        );
        await tester.ensureVisible(target);
        await tester.pumpAndSettle();
        expect(target.hitTestable(), findsOneWidget);
        await tester.tap(target);
        await tester.pumpAndSettle();
      }

      await tapOnBoard('mounted-instrument-pipettor');
      expect(
        find.widgetWithText(TextFormField, 'Aspiration height (mm)'),
        findsOneWidget,
      );
      await close();

      await tapOnBoard('mounted-instrument-magnet');
      expect(find.text('Type · Passive magnetic rack'), findsOneWidget);
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();

      await tapOnBoard('floor-instrument-hold');
      expect(
        find.widgetWithText(TextFormField, 'Humidity (%)'),
        findsOneWidget,
      );
      await capture('device-settings');
      await tester.enterText(
        find.byKey(const ValueKey('humidity_percent')),
        '101',
      );
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Apply settings'));
      await tester.pumpAndSettle();
      expect(find.text('Enter a value from 0 to 100.'), findsOneWidget);
      await close();

      await open(find.textContaining('mm · Deck bounds'));
      await capture('deck-bounds');
      await close();

      await tapOnBoard('floor-area-left');
      await tester.tap(find.text('Add instrument'));
      await tester.pumpAndSettle();
      expect(find.text('Tube incubator'), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(SimpleDialog),
          matching: find.text('HiG centrifuge'),
        ),
        findsNothing,
      );
      expect(find.text('Centrifuge'), findsOneWidget);
      Navigator.pop(tester.element(find.byType(SimpleDialog)));
      await tester.pumpAndSettle();

      await tapOnBoard('floor-area-left');
      await open(find.text('Edit area'));
      await capture('expansion-area');
      await close();

      await tapOnBoard('floor-instrument-hold');
      await tester.tap(find.text('Edit placement'));
      await tester.pumpAndSettle();
      expect(find.byType(DropdownButtonFormField<String>), findsOneWidget);
      expect(find.text('Remove from layout'), findsOneWidget);
      await close();

      final unbound = find.descendant(
        of: find.byType(FloorPlanBoard),
        matching: find.byIcon(Icons.water_drop_outlined),
      );
      await tester.ensureVisible(unbound);
      await tester.pumpAndSettle();
      await tester.tap(unbound);
      await tester.pumpAndSettle();
      expect(find.text('Workstation area · Rear extension'), findsOneWidget);
      expect(find.text('Handoff label · WA'), findsOneWidget);
      expect(find.text('Link instrument'), findsNothing);
      await tester.tap(find.text('Edit placement'));
      await tester.pumpAndSettle();
      expect(find.text('Station control'), findsNothing);
      expect(
        find.widgetWithText(FilledButton, 'Done').hitTestable(),
        findsOneWidget,
      );
      await capture('instrument-placement');
      final handoff = find.widgetWithText(
        TextFormField,
        'Handoff label (optional)',
      );
      await tester.ensureVisible(handoff);
      await tester.pumpAndSettle();
      expect(handoff.hitTestable(), findsOneWidget);
      if (width == 390) await capture('instrument-placement-end');
      await close();

      console.open('workstation');
      await tester.pumpAndSettle();
      await capture('workstation');

      await tester.pumpWidget(const SizedBox());
      console.dispose();
      layout.dispose();
    });
  }
}
