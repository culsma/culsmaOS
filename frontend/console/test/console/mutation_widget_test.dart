import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/setup_panel.dart';
import '../layout/fixture.dart';
import 'mutation_fixture.dart';
import 'package:culsma_console/features/console/view/evidence_panel.dart';

void main() {
  testWidgets(
    'evidence summary distinguishes receipt from material registration',
    (tester) async {
      final run = <String, dynamic>{
        'result': {'headline': 'Completed locally'},
        'execution_evidence': {
          'attempts': [
            {
              'step_id': 'transfer',
              'device_id': 'fixture',
              'mode': 'simulation',
              'evidence_status': 'recorded',
              'evidence': {'outcome': 'completed'},
              'registration': {'status': 'registered'},
            },
          ],
          'logical_completions': [],
        },
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: NativeEvidencePanel(run: run)),
          ),
        ),
      );
      await tester.tap(find.text('Recorded evidence and report'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Evidence: completed · Material: registered'),
        findsOneWidget,
      );
      expect(find.text('No logical completions recorded.'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final status in ['failed', 'completed']) {
    testWidgets('$status outcome stays above collapsed loading history', (
      tester,
    ) async {
      final api = MutationFixtureApi(),
          layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(api, layout);
      c.runs['loading-run'] = {
        'run_id': 'loading-run',
        'status': status,
        'error': status == 'failed' ? 'No tips available' : null,
        'result': {
          'execution': {
            'completed_steps': status == 'failed' ? 10 : 13,
            'total_steps': 13,
          },
          'os': {
            'registered_material': {
              'state': {
                'containers': {
                  'target': {'volume_uL': 100},
                },
              },
            },
          },
        },
      };
      c.setup.plans['loading-run'] = {...api.plan, 'phase': 'confirmed'};
      c.open('experiment', 'loading-run');
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      expect(
        find.text(
          status == 'completed'
              ? 'Experiment complete'
              : 'The experiment stopped',
        ),
        findsOneWidget,
      );
      expect(find.text('100 µL'), findsOneWidget);
      expect(find.text('Test track deck'), findsNothing);
      expect(find.text('Recorded loading plan'), findsNothing);
      await tester.ensureVisible(find.text('Technical details'));
      await tester.tap(find.text('Technical details'));
      await tester.pumpAndSettle();
      final history = find.text('Recorded loading plan');
      await tester.ensureVisible(history);
      await tester.pumpAndSettle();
      await tester.tap(history);
      await tester.pumpAndSettle();
      expect(find.text('Preparation status: confirmed'), findsOneWidget);
      expect(
        find.textContaining('does not mean execution succeeded'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    });
  }
  setUpAll(() async {
    final font = FontLoader('Console')
      ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
      ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf'));
    await font.load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  testWidgets(
    'direct occupied and empty diagram clicks open the same native editor',
    (tester) async {
      final api = MutationFixtureApi(),
          layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(
            api,
            layout,
            mutations: MemoryConsoleMutationRepository(),
            initialView: 'workstation',
          );
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      await tester.tap(find.text('sample-plate'));
      await tester.pumpAndSettle();
      expect(find.text('Edit rack position'), findsOneWidget);
      expect(c.labware.target?['id'], 'occupied');
      expect(c.dirty, isTrue);
      expect(
        find.text('This object is outside the editable driver catalogue.'),
        findsNothing,
      );
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.add));
      await tester.pumpAndSettle();
      expect(c.labware.target?['id'], 'vacant');
      expect(find.text('Empty position'), findsOneWidget);
      expect(api.calls.where((r) => r['action'] == 'apply'), isEmpty);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  testWidgets(
    'confirmed save removes its modal and allows the next position click',
    (tester) async {
      final api = MutationFixtureApi(),
          layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(
            api,
            layout,
            mutations: MemoryConsoleMutationRepository(),
            initialView: 'workstation',
          );
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      await tester.tap(find.text('sample-plate'));
      await tester.pumpAndSettle();
      c.labware.chooseCategory('empty');
      await c.labware.save();
      api.applied = true;
      await c.labware.observe(envelope(updatedFingerprint));
      await tester.pumpAndSettle();
      expect(find.text('Edit rack position'), findsNothing);
      await tester.tap(find.byIcon(Icons.add));
      await tester.pumpAndSettle();
      expect(c.labware.editing, isTrue);
      expect(c.labware.target?['id'], 'vacant');
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  testWidgets(
    'rack replacement is visible in Settings without scrolling the deck',
    (tester) async {
      final api = MutationFixtureApi(),
          layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(
            api,
            layout,
            mutations: MemoryConsoleMutationRepository(),
            initialView: 'settings',
          );
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Replace rack…'));
      await tester.pumpAndSettle();
      expect(find.text('Replace rack'), findsOneWidget);
      expect(find.text('Empty position'), findsNothing);
      expect(c.labware.target?['id'], 'carrier:rack');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  for (final width in [1100.0, 390.0]) {
    testWidgets('native labware dialog golden $width', (tester) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = MutationFixtureApi(),
          layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(
            api,
            layout,
            mutations: MemoryConsoleMutationRepository(),
            initialView: 'workstation',
          );
      await c.refresh();
      await tester.pumpWidget(
        RepaintBoundary(
          key: const Key('native-mutation-golden'),
          child: CulsmaConsole(controller: layout, console: c),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('sample-plate'));
      await tester.pumpAndSettle();
      c.labware.chooseCategory('reservoir');
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(
        find.byKey(const Key('native-mutation-golden')),
        matchesGoldenFile('../goldens/native-position-${width.toInt()}.png'),
      );
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    });
  }
  testWidgets('loading checkbox is necessary for operator confirmation', (
    tester,
  ) async {
    final api = MutationFixtureApi()..phase = 'loading',
        layout = LayoutFixture.controller(),
        c = NativeConsoleInteractor(
          api,
          layout,
          mutations: MemoryConsoleMutationRepository(),
        );
    final run = <String, dynamic>{
      'run_id': 'loading-run',
      'status': 'awaiting_setup',
    };
    await c.setup.observe(run);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: AnimatedBuilder(
              animation: c.setup,
              builder: (_, __) =>
                  NativeSetupPanel(controller: c.setup, run: run),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final confirm = find.widgetWithText(
      FilledButton,
      'Confirm loading and run',
    );
    expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
    await tester.ensureVisible(find.byType(CheckboxListTile));
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(confirm).onPressed, isNotNull);
    await tester.ensureVisible(confirm);
    await tester.tap(confirm);
    await tester.pumpAndSettle();
    expect(api.setupRequests.single['action'], 'confirm');
    expect(api.calls.last['path'], '/api/v1/setup/confirmation');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    c.dispose();
    layout.dispose();
  });
}
