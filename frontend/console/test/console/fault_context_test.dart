import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/fault_context.dart';
import 'package:culsma_console/features/console/view/run_outcome_view.dart';

void main() {
  testWidgets(
    'experiment outcome uses the same fault facts as diagnostic guidance',
    (tester) async {
      tester.view.physicalSize = const Size(1100, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final records =
          jsonDecode(
                File(
                  'test/console/fixtures/developer_fault_results.json',
                ).readAsStringSync(),
              )
              as List;
      final guidance = records.last['guidance'];
      final api = LocalConsoleApi(
        DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
      );
      final layout = LayoutController(api);
      final console = NativeConsoleInteractor(api, layout);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: NativeRunOutcomeView(
              console: console,
              run: {
                'run_id': 'recorded-unknown',
                'status': 'needs_reconciliation',
                'result': {
                  'os': {'mode': 'simulation'},
                },
                'user_guidance': guidance,
              },
            ),
          ),
        ),
      );
      expect(find.byType(NativeFaultContext), findsOneWidget);
      expect(find.textContaining('Affected location:'), findsOneWidget);
      expect(find.textContaining('no position is inferred'), findsOneWidget);
      expect(find.textContaining('Recovery availability:'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Resume run'), findsNothing);
      expect(find.text('Register new box'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      console.dispose();
      layout.dispose();
      api.close();
    },
  );
}
