import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/view/system_information_view.dart';

void main() {
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
      expect(find.text('120'), scope == 'station' ? findsNWidgets(2) : findsOneWidget);
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
