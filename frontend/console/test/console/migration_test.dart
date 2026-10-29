import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/system_information_interactor.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';
import 'package:culsma_console/features/console/view/system_information_view.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'fixture.dart';
import '../layout/fixture.dart';

class InfoApi extends NativeConsoleFixtureApi {
  bool mismatch = false, changed = false;
  int draftReads = 0;
  Map<String, dynamic> get active => {
    'host': {'status': 'ready'},
    'active': {
      'fingerprint': changed ? 'new' : 'host',
      'origin': {
        'draft_id': 'live',
        'revision': 2,
        'configuration_fingerprint': 'saved',
        'title': 'Live setup',
      },
    },
  };
  @override
  Future<Map<String, dynamic>> read(String path) async =>
      path.endsWith('/active') ? active : super.read(path);
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path.endsWith('/drafts')) {
      draftReads++;
      return {
        'draft': {
          'draft_id': 'live',
          'revision': 2,
          'fingerprint': mismatch ? 'wrong' : 'saved',
          'driver': 'test',
          'configuration': {'model': 'ACTIVE', 'mode': 'simulation'},
        },
      };
    }
    return super.command(path, body);
  }
}

void main() {
  test(
    'information uses exact saved active origin and clears mismatched facts',
    () async {
      final api = InfoApi(),
          c = NativeSystemInformationInteractor(api),
          profiles = <Map<String, dynamic>>[
            {
              'driver': 'test',
              'fields': [
                {
                  'section': 'platform',
                  'label': 'Model',
                  'path': ['model'],
                },
                {
                  'section': 'transfer',
                  'label': 'Flow',
                  'path': ['flow'],
                },
              ],
            },
          ];
      await c.observe({
        'layout': {'configuration_fingerprint': 'host'},
      });
      expect(c.equipment(profiles), [
        ['Model', 'ACTIVE'],
      ]);
      expect(api.draftReads, 1);
      await c.observe({
        'layout': {'configuration_fingerprint': 'host'},
      });
      expect(api.draftReads, 1);
      api.changed = true;
      await c.observe({
        'layout': {'configuration_fingerprint': 'host'},
      });
      expect(c.record, isNull);
      expect(c.error, isNotNull);
      api.changed = false;
      api.mismatch = true;
      await c.observe(null);
      expect(c.record, isNull);
      expect(c.error, contains('does not match'));
      c.dispose();
    },
  );
  test(
    'nested layout objects resolve to a deck position, never an internal site',
    () {
      final profile = LayoutFixture.profile(),
          configuration = LayoutData.copy(profile['template']);
      configuration['modules'] = {
        'heater': {'model': 'heaterShakerModuleV1', 'slot': '3'},
      };
      configuration['labware']['on_module'] = {
        'load_name': 'plate-model',
        'module': 'heater',
        'slot': 'A1',
      };
      final definition = LayoutDefinition(profile['layout'], configuration);
      expect(definition.presentationPosition(configuration, 'on_module'), '3');
      expect(definition.presentationPosition(configuration, 'missing'), isNull);
    },
  );
  testWidgets(
    'system view shows unavailable quantities as unknown and preserves ownership records',
    (tester) async {
      tester.view.physicalSize = const Size(1600, 2200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(NativeConsoleFixtureApi(), layout);
      c.station = {
        'host': {'status': 'ready'},
        'devices': {
          'registration': 'recorded',
          'resources': {
            'station_accounting': 'unresolved_supply',
            'local_accounting': 'recorded',
            'station_locks': [
              {'resource_id': 'device-lock', 'run_id': 'run-held'},
            ],
            'station_reservations': [
              {'run_id': 'run-held', 'owner_id': 'owner', 'status': 'active'},
            ],
          },
          'devices': [
            {
              'device_id': 'robot',
              'mode': 'simulation',
              'positions': {'status': 'unknown', 'current': null},
              'consumables': {
                'tips': {'known_consumed': 12, 'available_from_records': null},
              },
            },
          ],
        },
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: NativeSystemInformationView(console: c)),
        ),
      );
      await tester.tap(find.text('Device state and consumables'));
      await tester.pumpAndSettle();
      expect(find.text('Unknown'), findsOneWidget);
      await tester.tap(find.text('Resource accounting and ownership'));
      await tester.pumpAndSettle();
      expect(find.text('unresolved_supply'), findsOneWidget);
      expect(find.text('device-lock'), findsOneWidget);
      expect(find.text('owner'), findsOneWidget);
      expect(tester.takeException(), isNull);
      c.dispose();
      layout.dispose();
    },
  );
}
