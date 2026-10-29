import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/developer_interactor.dart';
import 'package:culsma_console/features/console/view/developer_view.dart';

void main() {
  setUpAll(() async {
    await (FontLoader(
      'Console',
    )..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  final cases =
      jsonDecode(
            File(
              'test/console/fixtures/developer_fault_results.json',
            ).readAsStringSync(),
          )
          as List;
  for (final result in cases) {
    testWidgets('real diagnostic result ${result['scenario']}', (tester) async {
      tester.view.physicalSize = const Size(1100, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = LocalConsoleApi(
        DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
      );
      final c = NativeDeveloperInteractor(api)
        ..result = Map<String, dynamic>.from(result);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(fontFamily: 'Console'),
          home: Scaffold(body: NativeDeveloperView(controller: c)),
        ),
      );
      expect(find.text('INJECTED TEST RESULT'), findsOneWidget);
      expect(find.text(result['guidance']['title']), findsOneWidget);
      expect(find.text('Register new box'), findsNothing);
      expect(find.text('Resume'), findsNothing);
      expect(find.textContaining('Device stop status:'), findsOneWidget);
      expect(find.textContaining('Affected location:'), findsOneWidget);
      expect(
        find.textContaining(
          'Not supplied by the driver; no position is inferred.',
        ),
        findsOneWidget,
      );
      await expectLater(
        find.byType(Scaffold),
        matchesGoldenFile('goldens/developer-${result['scenario']}.png'),
      );
      await tester.scrollUntilVisible(find.text('Processing flow'), 250);
      expect(find.text('Processing flow'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('Clear test result'), -250);
      await tester.tap(find.text('Clear test result'));
      await tester.pump();
      expect(c.result, isNull);
      expect(find.text('INJECTED TEST RESULT'), findsNothing);
      c.dispose();
      api.close();
    });
  }
}
