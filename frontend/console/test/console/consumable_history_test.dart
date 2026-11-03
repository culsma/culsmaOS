import 'package:flutter/material.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/setup_interactor.dart';
import 'package:culsma_console/features/console/view/setup_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/view/system_information_view.dart';

void main() {
  testWidgets('MCP conflict appears above retained loading plan', (
    tester,
  ) async {
    final api = LocalConsoleApi(
      DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused-render-only'),
    );
    final controller = NativeSetupInteractor(api, null);
    const message =
        'SETUP_NO_FEASIBLE_LAYOUT: standard, diluent are fixed to WATER_T36_REAR_SITE1 / 1. Choose different positions or change a fixed placement to automatic.';
    controller.acceptPlan('run', {
      'fingerprint': 'retained',
      'phase': 'planned',
      'activity': [
        {
          'action': 'revise',
          'status': 'failed',
          'error': message,
          'origin': 'local-mcp-process',
          'request_id': 'conflict',
        },
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeSetupPanel(
              controller: controller,
              run: const {'run_id': 'run', 'status': 'awaiting_setup'},
            ),
          ),
        ),
      ),
    );
    expect(
      find.textContaining('The previous plan is retained.'),
      findsOneWidget,
    );
    expect(find.textContaining('standard, diluent'), findsOneWidget);
    expect(tester.takeException(), isNull);
    controller.dispose();
    api.close();
  });
  for (final scope in ['run', 'unknown', 'station']) {
    testWidgets('consumable table respects $scope accounting scope', (
      tester,
    ) async {
      final device = {
        'mode': 'simulation',
        'simulation_scope': scope,
        'consumables': {
          'tips': {
            'known_consumed': 120,
            'configured_capacity': 12,
            'current_load_consumed': 120,
            'available_from_records': 0,
          },
        },
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: NativeConsumableTable(device: device)),
        ),
      );
      expect(
        find.text('120'),
        scope == 'station' ? findsNWidgets(2) : findsOneWidget,
      );
      expect(
        find.text('Available from records'),
        scope == 'station' ? findsOneWidget : findsNothing,
      );
      expect(
        find.text('Historical use across experiments'),
        scope == 'station' ? findsNothing : findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }
}
