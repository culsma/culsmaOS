import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/settings_view.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('workflow switch is available without a recorded deck', (
    tester,
  ) async {
    final api = LocalConsoleApi(
      DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
    );
    final layout = LayoutController(api);
    final console = NativeConsoleInteractor(api, layout);
    console.station = {
      'host': {
        'workflow_simulation': {'enabled': false, 'revision': 0},
      },
    };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: NativeSettingsView(console: console)),
      ),
    );
    final key = find.byKey(const Key('enable-workflow-simulation'));
    expect(tester.widget<SwitchListTile>(key).value, isFalse);
    expect(tester.widget<SwitchListTile>(key).onChanged, isNotNull);
    console.station!['host']['workflow_simulation'] = {
      'enabled': true,
      'revision': 1,
    };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: NativeSettingsView(console: console)),
      ),
    );
    expect(tester.widget<SwitchListTile>(key).value, isTrue);
    await tester.pumpWidget(const SizedBox());
    console.dispose();
    layout.dispose();
  });
}
