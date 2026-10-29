import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import '../test/console/run_outcome_fixture.dart';
import '../test/console/mutation_fixture.dart';
import '../test/layout/fixture.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native supply modal keeps AX tree valid through repeated transitions',
    (tester) async {
      final layout = LayoutFixture.controller(installedProfile: profile),
          api = NativeStockApi();
      final c = NativeConsoleInteractor(
        api,
        layout,
        mutations: MemoryConsoleMutationRepository(),
      );
      c.open('experiment', 'empty-tips');
      await c.refresh();
      await tester.pumpWidget(CulsmaConsole(controller: layout, console: c));
      await tester.pumpAndSettle();
      for (var cycle = 0; cycle < 12; cycle++) {
        await tester.tap(find.byKey(const Key('run-replace-tips')));
        await tester.pumpAndSettle();
        await tester.tap(find.byType(CheckboxListTile));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
        await tester.pumpAndSettle();
        expect(api.replacements, 0);
      }
      await tester.tap(find.byKey(const Key('run-replace-tips')));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Register new box'));
      await tester.pumpAndSettle();
      expect(api.replacements, 1);
      expect(api.startCount, 0);
      expect(find.text('Current tip supply: 6 available'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
}

final profile =
    jsonDecode(
          utf8.decode(
            base64Decode(const String.fromEnvironment('E2E_PROFILE')),
          ),
        )
        as Map<String, dynamic>;

class NativeStockApi extends GuidanceStockApi {
  @override
  Future<Map<String, dynamic>> read(String path) async {
    if (path.endsWith('/profiles'))
      return {
        'profiles': [profile],
      };
    return super.read(path);
  }
}
