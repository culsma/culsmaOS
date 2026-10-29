import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import '../layout/fixture.dart';
import 'fixture.dart';

void main() {
  testWidgets(
    'single workbar opens restores and closes native widget windows',
    (tester) async {
      final layout = LayoutFixture.controller(),
          api = NativeConsoleFixtureApi(),
          c = NativeConsoleInteractor(api, layout);
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('launcher-system_info')));
      await tester.pumpAndSettle();
      expect(c.windows.length, 2);
      expect(find.text('Show System Info'), findsNothing);
      await tester.tap(find.byKey(const ValueKey('minimize-system_info')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('launcher-system_info')));
      await tester.pumpAndSettle();
      expect(c.windows.length, 2);
      expect(c.active?.view, 'system_info');
      await tester.tap(find.byKey(const ValueKey('close-system_info')));
      await tester.pumpAndSettle();
      expect(c.windows.length, 1);
      expect(api.startCount, 0);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  testWidgets(
    'double click checks and confirmation starts once in a result window',
    (tester) async {
      final layout = LayoutFixture.controller(),
          api = NativeConsoleFixtureApi(),
          c = NativeConsoleInteractor(
            api,
            layout,
            requests: MemoryPendingRequestRepository(),
          );
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      final file = find.text('transfer.culs');
      await tester.tap(file);
      await tester.pump(const Duration(milliseconds: 60));
      await tester.tap(file);
      await tester.pumpAndSettle();
      expect(api.startCount, 0);
      await tester.tap(find.byKey(const Key('confirm-run')));
      await tester.pumpAndSettle();
      expect(api.startCount, 1);
      expect(c.active?.entityId, 'run-one');
      expect(find.text('100 µL'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('close-run:run-one')));
      await tester.pumpAndSettle();
      c.open('experiment', 'run-one');
      await c.refresh();
      await tester.pumpAndSettle();
      expect(api.startCount, 1);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
}
