import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'fixture.dart';
import 'run_outcome_fixture.dart';
import 'mutation_fixture.dart';
import '../layout/fixture.dart';

void main() {
  testWidgets(
    'tip shortage shows a remedy, keeps diagnostics collapsed and never auto-runs after replacement',
    (tester) async {
      tester.view.physicalSize = const Size(1100, 850);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final layout = LayoutFixture.controller(), api = GuidanceStockApi();
      final c = NativeConsoleInteractor(
        api,
        layout,
        mutations: MemoryConsoleMutationRepository(),
      );
      c.open('experiment', 'empty-tips');
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      expect(find.text('More tips are needed'), findsOneWidget);
      expect(find.text('Current tip supply: 0 available'), findsOneWidget);
      expect(find.text(diagnostic), findsNothing);
      expect(find.textContaining('10 / 13'), findsNothing);
      await tester.tap(find.byKey(const Key('run-replace-tips')));
      await tester.pumpAndSettle();
      expect(find.text('Replace simulated tip box'), findsOneWidget);
      expect(api.replacements, 0);
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Register new box'));
      await tester.pumpAndSettle();
      expect(find.text('Current tip supply: 6 available'), findsOneWidget);
      expect(api.replacements, 1);
      expect(api.startCount, 0);
      expect(c.runs['empty-tips']?['status'], 'failed');
      await tester.tap(find.text('Technical details'));
      await tester.pumpAndSettle();
      expect(find.text(diagnostic), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  testWidgets(
    'uncertain outcomes offer review without a restart or simulated refill',
    (tester) async {
      final layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(NativeConsoleFixtureApi(), layout);
      c.runs['uncertain'] = {
        'run_id': 'uncertain',
        'status': 'reconciliation_required',
        'error': 'INTERNAL_UNCERTAINTY',
        'user_guidance': {
          'kind': 'attention',
          'title': 'Check the station before continuing',
          'message': 'The outcome of an operation is uncertain.',
          'actions': ['open_workstation'],
          'next_steps': [],
        },
      };
      c.open('experiment', 'uncertain');
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      expect(find.text('Check the station before continuing'), findsOneWidget);
      expect(find.byKey(const Key('run-open-files')), findsNothing);
      expect(find.byKey(const Key('run-replace-tips')), findsNothing);
      expect(find.text('INTERNAL_UNCERTAINTY'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  testWidgets(
    'physical loading is directed to the workstation rather than a simulated refill',
    (tester) async {
      final layout = LayoutFixture.controller(),
          api = GuidanceStockApi()..mode = 'physical';
      final c = NativeConsoleInteractor(api, layout);
      c.open('experiment', 'empty-tips');
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      expect(find.text('Review workstation'), findsOneWidget);
      expect(find.byKey(const Key('run-replace-tips')), findsNothing);
      expect(api.replacements, 0);
      expect(api.startCount, 0);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
}
