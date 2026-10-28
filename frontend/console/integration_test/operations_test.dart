import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';
import 'console_test.dart' show until;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('native rack editing and explicit loading use real OS owners', (
    tester,
  ) async {
    const origin = String.fromEnvironment('E2E_ORIGIN');
    expect(origin, isNotEmpty);
    final directory = await Directory.systemTemp.createTemp(
      'native-operations-',
    );
    final api = LocalConsoleApi(
      DesktopConnection(Uri.parse(origin), 'native-operations-fixture-only'),
    );
    final layout = LayoutController(api),
        c = NativeConsoleInteractor(
          api,
          layout,
          initialView: 'workstation',
          mutations: FileConsoleMutationRepository(
            File('${directory.path}/pending.json'),
          ),
        );
    try {
      await layout.load();
      await c.start();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      await tester.tap(find.text('HT_L_0003'));
      await until(tester, () => !c.labware.busy);
      expect(c.labware.error, isNull);
      expect(c.labware.target?['reason'], isNull);
      await tester.pumpAndSettle();
      expect(find.text('Edit rack position'), findsOneWidget);
      final category = find.byWidgetPredicate(
        (w) =>
            w is DropdownButtonFormField<String> &&
            (w.key as ValueKey?)?.value.toString().startsWith(
                  'labware-category-',
                ) ==
                true,
      );
      await tester.tap(category);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Empty position').last);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await until(
        tester,
        () =>
            !c.labware.editing &&
            c.labware.pending == null &&
            find.text('Edit rack position').evaluate().isEmpty,
      );
      await tester.pumpAndSettle();
      expect(find.text('HT_L_0003'), findsNothing);
      await tester.tap(
        find.byKey(const ValueKey('layout-site:CAR_5TIP_0001/2')),
      );
      await until(tester, () => !c.labware.busy);
      expect(c.labware.error, isNull);
      await tester.pumpAndSettle();
      await tester.tap(category);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tip rack').last);
      await tester.pumpAndSettle();
      if (c.labware.model.isEmpty) {
        final model = find.byWidgetPredicate(
          (w) =>
              w is DropdownButtonFormField<String> &&
              (w.key as ValueKey?)?.value.toString().startsWith(
                    'labware-model-',
                  ) ==
                  true,
        );
        await tester.tap(model);
        await tester.pumpAndSettle();
        final label =
            c.labware.models.firstWhere((m) => m['category'] == 'tips')['label']
                as String;
        await tester.tap(find.text(label).last);
        await tester.pumpAndSettle();
      }
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await until(
        tester,
        () =>
            !c.labware.editing &&
            c.labware.pending == null &&
            find.text('Edit rack position').evaluate().isEmpty,
      );
      await tester.pumpAndSettle();
      final inspected = await api.command('/api/v1/programs', {
        'action': 'inspect',
        'program_id': 'transfer.culs',
      });
      final admitted = await api.command('/api/v1/programs', {
        'action': 'submit',
        'program_id': 'transfer.culs',
        'snapshot_id': inspected['snapshot_id'],
        'request_id': 'native-manual-loading',
      });
      final id = admitted['run']['run_id'] as String;
      c.open('experiment', id);
      await until(
        tester,
        () =>
            c.setup.plans[id]?['phase'] == 'planned' ||
            {'failed', 'rejected'}.contains(c.runs[id]?['status']),
      );
      expect(
        c.setup.plans[id]?['phase'],
        'planned',
        reason:
            '${c.runs[id]?["error"]} ${c.setup.errors[id]} ${c.setup.plans[id]?["error"]}',
      );
      await tester.pumpAndSettle();
      final begin = find.widgetWithText(FilledButton, 'Start loading');
      await tester.ensureVisible(begin);
      await tester.pumpAndSettle();
      await tester.tap(begin);
      await until(
        tester,
        () =>
            c.setup.plans[id]?['phase'] == 'loading' &&
            c.setup.pending[id] == null,
      );
      await tester.pumpAndSettle();
      final confirm = find.widgetWithText(
        FilledButton,
        'Confirm loading and run',
      );
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      await tester.ensureVisible(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.ensureVisible(confirm);
      await tester.pumpAndSettle();
      await tester.tap(confirm);
      await until(
        tester,
        () =>
            {'completed', 'failed', 'rejected'}.contains(c.runs[id]?['status']),
      );
      expect(
        c.runs[id]?['status'],
        'completed',
        reason: c.runs[id]?['error']?.toString(),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining(RegExp(r'100(?:\.0)? µL')), findsWidgets);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    } finally {
      c.dispose();
      layout.dispose();
      await directory.delete(recursive: true);
    }
  });
}
