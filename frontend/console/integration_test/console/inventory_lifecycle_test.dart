import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/view/run_outcome_view.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/repository/pending_request_repository.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'real native workstation survives repeated runs, refills and exhausted liquid',
    (tester) async {
      final connection = jsonDecode(
        utf8.decode(
          base64Decode(const String.fromEnvironment('E2E_CONNECTION')),
        ),
      );
      final api = LocalConsoleApi(
        DesktopConnection(Uri.parse(connection['origin']), connection['token']),
      );
      final directory = await Directory.systemTemp.createTemp(
        'real-inventory-ui-',
      );
      final layout = LayoutController(api);
      final c = NativeConsoleInteractor(
        api,
        layout,
        requests: FilePendingRequestRepository(
          File('${directory.path}/pending.json'),
        ),
        mutations: FileConsoleMutationRepository(
          File('${directory.path}/mutations.json'),
        ),
      );
      Future<void> settle() async {
        for (var i = 0; i < 200; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
          if (!c.busy) await c.refresh();
          final status = c.runs[c.active?.entityId]?['status'];
          if (['completed', 'failed', 'needs_reconciliation'].contains(status))
            break;
        }
        await tester.pumpAndSettle();
      }

      Future<void> reconnectAccessibility() async {
        const bridge = MethodChannel('culsma/test/accessibility');
        await bridge.invokeMethod('setEnabled', false);
        await tester.pumpAndSettle();
        await bridge.invokeMethod('setEnabled', true);
        await tester.pumpAndSettle();
      }

      var cancellationChecked = false;
      Future<void> run(String expected) async {
        await reconnectAccessibility();
        c.open('files');
        await c.files.navigate('programs', '');
        await tester.pumpAndSettle();
        final entry = find.byKey(
          const ValueKey('file-entry-programs-standard_dilution.culs'),
        );
        await tester.tap(entry);
        await tester.pump(const Duration(milliseconds: 60));
        await tester.tap(entry);
        for (var i = 0; i < 100 && c.busy; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        await tester.pumpAndSettle();
        final before = (await api.read('/api/v1/station'))['runs'];
        expect(c.launchReview, isNotNull, reason: c.message);
        expect(c.pendingStart, isNull);
        await Future<void>.delayed(const Duration(milliseconds: 300));
        expect((await api.read('/api/v1/station'))['runs'], before);
        if (!cancellationChecked) {
          c.closeWindow(c.active!);
          await c.confirmLaunch();
          expect((await api.read('/api/v1/station'))['runs'], before);
          expect(c.launchReview, isNull);
          cancellationChecked = true;
          await c.launch('standard_dilution.culs');
          await tester.pumpAndSettle();
        }
        expect(find.text('Run simulation'), findsOneWidget);
        expect(
          tester
              .widget<FilledButton>(find.byKey(const Key('hardware-run')))
              .onPressed,
          isNull,
        );
        expect(c.inspection?['preparation']?['plan']?['loadout'], isNotEmpty);
        final button = find.byKey(const Key('confirm-run')).hitTestable();
        final beforePolling = tester.getRect(button);
        for (var poll = 0; poll < 3; poll++) {
          final refresh = c.refresh();
          expect(c.reviewBusy, isFalse);
          await tester.pump();
          expect(find.text('Ready to confirm'), findsOneWidget);
          expect(find.text('Checking the experiment…'), findsNothing);
          expect(find.byType(LinearProgressIndicator), findsNothing);
          expect(tester.getRect(button), beforePolling);
          expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
          await refresh;
          await tester.pumpAndSettle();
        }
        // Click while a real station read is pending, rather than dropping it.
        final refresh = c.refresh();
        await tester.tap(button);
        await refresh;
        await settle();
        expect(
          c.runs[c.active?.entityId]?['status'],
          expected,
          reason: c.message,
        );
        if (expected == 'completed') {
          final activeResult = find.byWidgetPredicate(
            (w) =>
                w is NativeRunOutcomeView &&
                w.run['run_id'] == c.active?.entityId,
          );
          Finder text(String value) =>
              find.descendant(of: activeResult, matching: find.text(value));
          expect(text('Simulation completed'), findsOneWidget);
          expect(text('Final products'), findsOneWidget);
          expect(text('Dilution standards_A1'), findsOneWidget);
          expect(text('Reagents used'), findsOneWidget);
          expect(text('230 µL'), findsOneWidget);
          expect(
            find.descendant(
              of: activeResult,
              matching: find.textContaining('__lw_plate'),
            ),
            findsNothing,
          );
        }
      }

      Future<void> refill() async {
        await tester.tap(
          find.byKey(const Key('run-replace-tips')).hitTestable(),
        );
        for (var i = 0; i < 50 && !c.supplies.editing; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        await tester.pumpAndSettle();
        await reconnectAccessibility();
        await tester.tap(find.byType(CheckboxListTile));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(FilledButton, 'Register new box'));
        for (var i = 0; i < 100 && c.supplies.editing; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        await tester.pumpAndSettle();
        expect(c.supplies.editing, isFalse);
        expect((c.supplies.data!['stock']['available'] as List).length, 12);
      }

      try {
        await layout.load();
        await c.refresh();
        await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
        await tester.pumpAndSettle();
        if (const bool.fromEnvironment('INDEPENDENT_SIMULATION')) {
          c.open('workstation');
          await tester.pumpAndSettle();
          expect(find.text('Replace tip box…'), findsNothing);
          for (var trial = 0; trial < 6; trial++) {
            await run('completed');
          }
          expect(c.supplies.supported, isFalse);
          expect(find.text('Replace tip box…'), findsNothing);
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox());
          return;
        }
        await run('completed');
        await run('completed');
        await run('failed');
        expect(find.text('More tips are needed'), findsOneWidget);
        await refill();
        await run('completed');
        await run('completed');
        await run('failed');
        await refill();
        await run('failed');
        expect(
          find.text('The simulated liquid supply is insufficient'),
          findsOneWidget,
        );
        expect(find.textContaining('Checking the experiment'), findsNothing);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      } finally {
        c.dispose();
        layout.dispose();
        await directory.delete(recursive: true);
      }
    },
    semanticsEnabled: false, // Let the real native bridge drive the lifecycle.
  );
}
