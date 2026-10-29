import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/repository/pending_request_repository.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('native installation file navigation, preview and execution', (
    tester,
  ) async {
    final temporary = await Directory.systemTemp.createTemp(
      'files-e2e-records-',
    );
    final api = LocalConsoleApi(
      DesktopConnection(
        Uri.parse(const String.fromEnvironment('E2E_ORIGIN')),
        'native-files-fixture-only',
      ),
    );
    final layout = LayoutController(api);
    final c = NativeConsoleInteractor(
      api,
      layout,
      requests: FilePendingRequestRepository(
        File('${temporary.path}/pending.json'),
      ),
      mutations: FileConsoleMutationRepository(
        File('${temporary.path}/mutation.json'),
      ),
    );
    try {
      await c.refresh();
      expect(c.files.root, 'installation');
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      await tester.tap(find.text('README.txt'));
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();
      expect(find.text('Native installation preview'), findsOneWidget);
      expect(c.runs, isEmpty);
      final folder = find.byKey(
        const ValueKey('file-entry-installation-examples'),
      );
      await tester.tap(folder);
      await tester.pump(const Duration(milliseconds: 60));
      await tester.tap(folder);
      await tester.pumpAndSettle();
      expect(c.files.path, 'examples');
      final file = find.byKey(
        const ValueKey('file-entry-installation-examples/transfer.culs'),
      );
      await tester.tap(file);
      await tester.pump(const Duration(milliseconds: 60));
      await tester.tap(file);
      for (var i = 0; i < 100; i++) {
        await tester.pump(const Duration(milliseconds: 100));
        await Future<void>.delayed(const Duration(milliseconds: 50));
        if (!c.busy) await c.refresh();
        if (c.runs[c.active?.entityId]?['status'] == 'completed') break;
      }
      await tester.pumpAndSettle();
      expect(c.active?.view, 'experiment');
      expect(
        c.runs[c.active?.entityId]?['status'],
        'completed',
        reason: c.message,
      );
      expect(find.textContaining(RegExp(r'100(?:\.0)? µL')), findsWidgets);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    } finally {
      c.dispose();
      layout.dispose();
      await temporary.delete(recursive: true);
    }
  });
}
