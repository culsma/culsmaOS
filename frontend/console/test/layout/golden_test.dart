import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'fixture.dart';

void main() {
  setUpAll(() async {
    final font = FontLoader('Console');
    font.addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'));
    font.addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf'));
    await font.load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  for (final size in [const Size(1100, 800), const Size(390, 844)]) {
    testWidgets('layout golden ${size.width.toInt()}', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final c = LayoutFixture.controller();
      c.selectPosition('1');
      await tester.pumpWidget(
        RepaintBoundary(
          key: const Key('golden-root'),
          child: CulsmaConsole(controller: c),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(
        find.byKey(const Key('golden-root')),
        matchesGoldenFile('../goldens/layout-${size.width.toInt()}.png'),
      );
    });
  }
  testWidgets('Hamilton track layout golden', (tester) async {
    tester.view.physicalSize = const Size(1400, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final c = LayoutFixture.controller(
      installedProfile: LayoutFixture.hamiltonProfile(),
    );
    c.selectPosition('1');
    await tester.pumpWidget(
      RepaintBoundary(
        key: const Key('hamilton-golden'),
        child: CulsmaConsole(controller: c),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('hamilton-golden')),
      matchesGoldenFile('../goldens/hamilton-1400.png'),
    );
  });
}
