import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/model/run_progress.dart';
import 'package:culsma_console/features/console/view/run_progress_panel.dart';

// Record shape from installed Hamilton batch execution: one root attempt and
// later member receipts. Rendering needs no substitute HTTP or device backend.
const pendingBatch = <String, dynamic>{
  'status': 'waiting',
  'execution_evidence': {
    'attempts': [
      {
        'context': {
          'description': {'operation_kind': 'execution_batch'},
        },
        'evidence': null,
      },
    ],
  },
};
void main() {
  setUpAll(() async {
    await (FontLoader('Console')
          ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
          ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf')))
        .load();
  });
  test('queued, submitted and running states provide truthful progress', () {
    for (final status in ['ready', 'queued', 'preparing']) {
      expect(
        NativeRunProgress.fromRun({'status': status})!.title,
        'Preparing the experiment…',
      );
    }
    expect(
      NativeRunProgress.fromRun(pendingBatch)!.title,
      'Waiting for execution to finish',
    );
    expect(
      NativeRunProgress.fromRun({'status': 'running'})!.title,
      'Experiment in progress…',
    );
    expect(
      NativeRunProgress.fromRun({'status': 'waiting'})!.title,
      'Experiment in progress…',
    );
  });
  test(
    'stopped, loading and uncertain runs never display ongoing progress',
    () {
      for (final status in [
        'completed',
        'failed',
        'rejected',
        'cancelled',
        'paused',
        'awaiting_setup',
        'needs_reconciliation',
        'reconciliation_required',
        'unknown',
      ]) {
        expect(
          NativeRunProgress.fromRun({...pendingBatch, 'status': status}),
          isNull,
          reason: status,
        );
      }
    },
  );
  testWidgets(
    'batch progress is indeterminate and disappears when result arrives',
    (tester) async {
      Future<void> show(Map run) => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: NativeRunProgressPanel(run: run)),
        ),
      );
      await show(pendingBatch);
      expect(find.text('Waiting for execution to finish'), findsOneWidget);
      expect(
        tester
            .widget<LinearProgressIndicator>(
              find.byType(LinearProgressIndicator),
            )
            .value,
        isNull,
      );
      await tester.pump(const Duration(seconds: 2));
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      await show({...pendingBatch, 'status': 'completed'});
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  for (final width in [390.0, 1100.0]) {
    testWidgets('progress golden $width', (tester) async {
      tester.view.physicalSize = Size(width, 260);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(fontFamily: 'Console'),
          home: Scaffold(
            body: RepaintBoundary(
              key: const Key('progress-golden'),
              child: const Padding(
                padding: EdgeInsets.all(12),
                child: NativeRunProgressPanel(run: pendingBatch),
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
      await expectLater(
        find.byKey(const Key('progress-golden')),
        matchesGoldenFile('../goldens/run-progress-${width.toInt()}.png'),
      );
      await tester.pumpWidget(const SizedBox());
    });
  }
}
