import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import '../layout/fixture.dart';
import 'fixture.dart';
import 'mutation_fixture.dart';

void main() {
  setUpAll(() async {
    final font = FontLoader('Console')
      ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
      ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf'));
    await font.load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  for (final view in ['files', 'experiment', 'system_info']) {
    testWidgets('native migration golden $view', (tester) async {
      tester.view.physicalSize = const Size(1100, 850);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(
            NativeConsoleFixtureApi(),
            layout,
            mutations: MemoryConsoleMutationRepository(),
            initialView: view == 'experiment' ? 'files' : view,
          );
      await c.files.initialize();
      c.files.entries = [
        {
          'name': 'Experiments',
          'path': 'projects',
          'kind': 'directory',
          'openable': true,
          'extension': '',
        },
        {
          'name': 'Results',
          'path': 'results',
          'kind': 'directory',
          'openable': true,
          'extension': '',
        },
      ];
      c.files.total = c.files.entries.length;
      c.files.folders[c.files.key('installation', '')] = c.files.entries
          .where((r) => r['kind'] == 'directory')
          .toList();
      c.station = {
        'host': {'status': 'ready'},
        'layout': {
          'driver': 'opentrons-simulator',
          'configuration_fingerprint': 'recorded-host-identity',
        },
        'devices': {
          'registration': 'recorded',
          'resources': {
            'local_accounting': 'recorded',
            'station_accounting': 'recorded',
          },
          'devices': [],
        },
      };
      c.information.active = layout.active;
      c.information.record = layout.draft;
      if (view == 'experiment') {
        c.runs['running-example'] = {
          'run_id': 'running-example',
          'status': 'waiting',
          'pending_controls': [],
        };
        c.open('experiment', 'running-example');
      }
      await tester.pumpWidget(
        RepaintBoundary(
          key: const Key('migration-golden'),
          child: CulsmaConsole(controller: layout, console: c),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(
        find.byKey(const Key('migration-golden')),
        matchesGoldenFile('../goldens/native-$view-1100.png'),
      );
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    });
  }
}
