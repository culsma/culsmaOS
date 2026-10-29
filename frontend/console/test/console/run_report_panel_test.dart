import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/view/run_report_panel.dart';

void main() {
  setUpAll(() async {
    await (FontLoader(
      'Console',
    )..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))).load();
  });
  for (final width in [1100.0, 390.0]) {
    testWidgets('real report products and consumption golden $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final run = jsonDecode(
        File(
          'test/console/fixtures/standard_dilution_report.json',
        ).readAsStringSync(),
      );
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(fontFamily: 'Console'),
          home: RepaintBoundary(
            key: const Key('report-golden'),
            child: Scaffold(
              body: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: NativeRunReportPanel(run: run),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Final products'), findsOneWidget);
      expect(find.text('Dilution standards_A1'), findsOneWidget);
      expect(find.textContaining('__lw_'), findsNothing);
      expect(find.text('230 µL'), findsOneWidget);
      expect(find.textContaining('No duration estimate'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await expectLater(
        find.byKey(const Key('report-golden')),
        matchesGoldenFile(
          '../goldens/native-language-report-${width.toInt()}.png',
        ),
      );
      run['status'] = 'failed';
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: NativeRunReportPanel(run: run)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.text('Partial run report · the experiment did not complete.'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }
}
