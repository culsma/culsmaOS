import 'dart:ui' show PointerDeviceKind;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'fixture.dart';
import '../layout/fixture.dart';

void main() {
  testWidgets(
    'hover and window transitions keep accessible controls without tooltip portals',
    (tester) async {
      final semantics = tester.ensureSemantics();
      final layout = LayoutFixture.controller(),
          api = NativeConsoleFixtureApi();
      final c = NativeConsoleInteractor(
        api,
        layout,
        requests: MemoryPendingRequestRepository(),
      );
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      await mouse.addPointer(
        location: tester.getCenter(find.byKey(const Key('files-refresh'))),
      );
      await tester.pump(const Duration(seconds: 1));
      expect(find.bySemanticsLabel('Refresh folder'), findsOneWidget);
      expect(find.byType(RawTooltip), findsNothing);
      await mouse.moveTo(
        tester.getCenter(find.byKey(const Key('launcher-workstation'))),
      );
      await tester.pump(const Duration(seconds: 1));
      expect(find.bySemanticsLabel('Workstation'), findsOneWidget);
      expect(find.byType(RawTooltip), findsNothing);
      await c.launch('transfer.culs');
      await tester.pumpAndSettle();
      expect(find.text('100 µL'), findsOneWidget);
      expect(
        find.bySemanticsLabel('Close Experiment · run-one'),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('close-run:run-one')));
      await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('Refresh folder'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await mouse.removePointer();
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
      semantics.dispose();
    },
  );
}
