import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/interactor/renderer_interactor.dart';
import 'package:culsma_console/features/console/repository/pending_request_repository.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';

Future<void> until(WidgetTester tester, bool Function() ready) async {
  for (var i = 0; i < 200; i++) {
    await tester.pump(const Duration(milliseconds: 100));
    if (ready()) return;
    await Future<void>.delayed(const Duration(milliseconds: 50));
  }
  fail('Native console did not reach the expected state');
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native files launch through the OS and MCP selects the same native windows',
    (tester) async {
      const origin = String.fromEnvironment('E2E_ORIGIN');
      expect(origin, isNotEmpty);
      final directory = await Directory.systemTemp.createTemp(
        'native-shell-e2e-',
      );
      final api = LocalConsoleApi(
        DesktopConnection(
          Uri.parse(origin),
          'native-shell-console-fixture-only',
        ),
      );
      final layout = LayoutController(api);
      final c = NativeConsoleInteractor(
        api,
        layout,
        mutations: FileConsoleMutationRepository(
          File('${directory.path}/mutations.json'),
        ),
        requests: FilePendingRequestRepository(
          File('${directory.path}/pending.json'),
        ),
      );
      final renderer = NativeRendererInteractor(
        LocalConsoleApi(
          DesktopConnection(
            Uri.parse(origin),
            'native-shell-renderer-fixture-only',
          ),
        ),
        c,
      );
      try {
        await layout.load();
        await c.start();
        await tester.pumpWidget(
          CulsmaConsole(controller: layout, console: c, renderer: renderer),
        );
        await tester.pumpAndSettle();
        expect(find.text('examples'), findsOneWidget);
        final file = find.text('transfer.culs');
        await tester.tap(file);
        await tester.pump(const Duration(milliseconds: 70));
        await tester.tap(file);
        await until(
          tester,
          () =>
              c.active?.view == 'experiment' &&
              {
                'running',
                'waiting',
              }.contains(c.runs[c.active?.entityId]?['status']),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Pause run'));
        await until(
          tester,
          () =>
              c.runs[c.active?.entityId]?['status'] == 'paused' &&
              c.controls.receipts[c.active?.entityId]?['status'] == 'applied',
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Resume run'));
        await until(
          tester,
          () =>
              c.runs[c.active?.entityId]?['status'] == 'completed' &&
              c.controls.receipts[c.active?.entityId]?['status'] == 'applied',
        );
        await tester.pumpAndSettle();
        expect(find.textContaining(RegExp(r'100(?:\.0)? µL')), findsWidgets);
        final runId = c.active!.entityId!, runWindow = c.active!;
        await tester.tap(find.byKey(ValueKey('minimize-${runWindow.id}')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(ValueKey('task-run:$runId')));
        await tester.pumpAndSettle();
        expect(c.active?.entityId, runId);
        await tester.tap(find.byKey(const ValueKey('launcher-files')));
        await tester.pumpAndSettle();
        await tester.tap(file);
        await tester.pump(const Duration(milliseconds: 70));
        await tester.tap(file);
        await until(
          tester,
          () =>
              c.active?.entityId != runId &&
              {
                'running',
                'waiting',
              }.contains(c.runs[c.active?.entityId]?['status']),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Cancel run'));
        await until(
          tester,
          () =>
              c.runs[c.active?.entityId]?['status'] == 'cancelled' &&
              c.controls.receipts[c.active?.entityId]?['status'] == 'applied',
        );
        await tester.pumpAndSettle();
        renderer.start();
        // The Python harness now sends open_view through a real MCP subprocess.
        await until(tester, () => c.active?.view == 'system_info');
        await tester.pumpAndSettle();
        expect(
          find.text(
            'Read-only OS records and declared configuration. Hardware presence and physical contents are not detected.',
          ),
          findsOneWidget,
        );
        expect(c.information.error, isNull);
        expect(tester.takeException(), isNull);
        await renderer.close();
        await tester.pumpWidget(const SizedBox());
      } catch (error) {
        // Non-sensitive test diagnostics only; never log connection credentials.
        print(
          'Native E2E state: view=${c.active?.view}, message=${c.message}, runs=${c.runs.map((id, row) => MapEntry(id, {'status': row['status'], 'error': row['error']}))}',
        );
        rethrow;
      } finally {
        c.dispose();
        layout.dispose();
        await directory.delete(recursive: true);
      }
    },
  );
}
