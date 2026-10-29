import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import '../layout/fixture.dart';
import 'mutation_fixture.dart';
import 'run_outcome_fixture.dart';

void main() {
  setUpAll(() async {
    await (FontLoader('Console')
          ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
          ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf')))
        .load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  for (final width in [1100.0, 390.0]) {
    testWidgets('actionable preparation golden $width', (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final layout = LayoutFixture.controller(), api = GuidanceStockApi();
      final c = NativeConsoleInteractor(
        api,
        layout,
        mutations: MemoryConsoleMutationRepository(),
      );
      c.open('experiment', 'empty-tips');
      c.active!.maximized = true;
      await c.refresh();
      await tester.pumpWidget(
        RepaintBoundary(
          key: const Key('preparation-golden'),
          child: CulsmaConsole(controller: layout, console: c),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(
        find.byKey(const Key('preparation-golden')),
        matchesGoldenFile('../goldens/native-preparation-${width.toInt()}.png'),
      );
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    });
  }
}
