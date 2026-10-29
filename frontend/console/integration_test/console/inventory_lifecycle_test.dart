import 'dart:convert';
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

      Future<void> run(String expected) async {
        c.open('files');
        await c.files.navigate('programs', '');
        await tester.pumpAndSettle();
        final entry = find.byKey(
          const ValueKey('file-entry-programs-standard_dilution.culs'),
        );
        await tester.tap(entry);
        await tester.pump(const Duration(milliseconds: 60));
        await tester.tap(entry);
        await settle();
        expect(
          c.runs[c.active?.entityId]?['status'],
          expected,
          reason: c.message,
        );
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
        expect(find.text('The setup needs attention'), findsOneWidget);
        expect(find.textContaining('Checking the experiment'), findsNothing);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      } finally {
        c.dispose();
        layout.dispose();
        await directory.delete(recursive: true);
      }
    },
  );
}
