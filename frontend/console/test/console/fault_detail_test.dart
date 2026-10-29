import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/view/fault_context.dart';

void main() {
  setUpAll(() async {
    await (FontLoader('Console')
          ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
          ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf')))
        .load();
  });
  testWidgets('shows each channel, planned location and actionable check', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: ThemeData(fontFamily: 'Console'),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeFaultContext(
              guidance: {
                'context': {
                  'execution': 'Unknown',
                  'device_stop': 'Not confirmed',
                },
                'fault_details': [
                  {
                    'title': 'Tip pickup failed',
                    'operation': 'step-3',
                    'basis': 'device_feedback',
                    'basis_label': 'Device feedback',
                    'facts': {'Channel': '1', 'Planned position': 'B / 4'},
                    'check':
                        'Check whether the indicated tip is present and seated correctly.',
                  },
                  {
                    'title': 'The device reported a problem',
                    'basis': 'device_feedback',
                    'basis_label': 'Device feedback',
                    'facts': {'Channel': '2'},
                    'check': 'No specific remedy is established.',
                  },
                ],
              },
            ),
          ),
        ),
      ),
    );
    expect(find.text('Tip pickup failed'), findsOneWidget);
    expect(find.text('Planned position: B / 4'), findsOneWidget);
    expect(find.text('Channel: 2'), findsOneWidget);
    expect(find.text('No specific remedy is established.'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/fault-detail.png'),
    );
  });
}
