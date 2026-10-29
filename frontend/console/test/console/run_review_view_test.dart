import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/run_review_view.dart';

void main() {
  testWidgets(
    'background reads do not change a checked review or its geometry',
    (tester) async {
      // Real production presentation models; no network calls or mocked methods.
      final api = LocalConsoleApi(
        DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
      );
      final layout = LayoutController(api);
      final c = NativeConsoleInteractor(api, layout);
      c.selectedFile = 'standard_dilution.culs';
      c.station = {
        'devices': {
          'devices': [
            {'mode': 'simulation'},
          ],
        },
      };
      c.inspection = jsonDecode(
        File(
          'test/console/fixtures/standard_dilution_review.json',
        ).readAsStringSync(),
      );
      c.launchReview = {'program_id': 'standard_dilution.culs'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AnimatedBuilder(
              animation: c,
              builder: (_, _) => NativeRunReviewView(console: c),
            ),
          ),
        ),
      );
      expect(find.text('Run simulation'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('hardware-run')))
            .onPressed,
        isNull,
      );
      expect(find.text('Track 36 · Position 2'), findsOneWidget);
      expect(find.textContaining('__lw_plate'), findsNothing);
      final button = find.byKey(const Key('confirm-run'));
      final bounds = tester.getRect(button);
      for (final busy in [true, false, true, false]) {
        c.busy = busy;
        c.notifyViewChanged();
        await tester.pump();
        expect(find.text('Ready to confirm'), findsOneWidget);
        expect(find.byType(LinearProgressIndicator), findsNothing);
        expect(tester.getRect(button), bounds);
        expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
      }
      c.checkingRun = true;
      c.notifyViewChanged();
      await tester.pump();
      expect(find.text('Checking the experiment…'), findsOneWidget);
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      c.checkingRun = false;
      c.submittingRun = true;
      c.notifyViewChanged();
      await tester.pump();
      expect(find.text('Starting the simulation…'), findsOneWidget);
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
      api.close();
    },
  );
}
