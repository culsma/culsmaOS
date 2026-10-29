import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/run_review_interactor.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/api/console_api.dart';

void main() {
  final review = NativeRunReviewInteractor();
  final fixture = jsonDecode(
    File(
      'test/console/fixtures/standard_dilution_review.json',
    ).readAsStringSync(),
  );
  final plan = fixture['preparation']['plan'];
  test(
    'real resident loading plan presents locations, quantities and empty wells',
    () {
      final loadout = plan['loadout'];
      expect(review.location(loadout[0]['placement']), 'Track 36 · Position 2');
      expect(
        review.containerInstruction(loadout[0]['containers'][0]),
        'standard · position 1 — load 1000 µL',
      );
      expect(review.location(loadout[1]['placement']), 'Track 36 · Position 1');
      expect(review.location(loadout[2]['placement']), 'Track 29 · Position 4');
      expect(
        review.containerInstruction(loadout[2]['containers'][0]),
        'Well A1 — leave empty',
      );
      expect(
        review.tipInstruction(plan['supplies'][0]),
        contains('12 configured tip positions'),
      );
      expect(
        review.tipInstruction(plan['supplies'][0]),
        contains('checked before execution'),
      );
    },
  );
  test(
    'missing locations and stock are not invented, fractional amounts survive',
    () {
      expect(review.location(null), 'Location not supplied by the driver');
      expect(review.location({'slot': 'D2'}), 'Slot D2');
      expect(review.location({'carrier': 'Rack A'}), 'Carrier Rack A');
      expect(review.volume(73.2), '73.2 µL');
      expect(review.volume(null), 'Amount not specified');
      expect(
        review.tipInstruction({}),
        contains('Tip positions not specified'),
      );
      expect(
        review.tipInstruction({'required': 6}),
        contains('6 tips required'),
      );
    },
  );
  test(
    'simulation is opt-in and never inferred from unknown or physical devices',
    () async {
      for (final modes in [
        [],
        ['physical'],
        ['simulation', 'physical'],
      ]) {
        final station = {
          'devices': {
            'devices': [
              for (final mode in modes) {'mode': mode},
            ],
          },
        };
        expect(review.simulationAvailable(station), false);
        final api = LocalConsoleApi(
          DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
        );
        final layout = LayoutController(api);
        final c = NativeConsoleInteractor(api, layout)..station = station;
        c.launchReview = {'program_id': 'standard_dilution.culs'};
        await c.runSimulation();
        expect(c.pendingStart, isNull);
        expect(c.launchReview, isNotNull);
        expect(c.message, contains('No simulation workstation'));
        c.dispose();
        layout.dispose();
        api.close();
      }
      expect(review.simulationAvailable(null), false);
      expect(
        review.simulationAvailable(null, {
          'preparation': {
            'execution_options': {'simulation': true, 'hardware': false},
          },
        }),
        true,
      );
      expect(
        review.simulationAvailable(
          {
            'devices': {
              'devices': [
                {'mode': 'simulation'},
              ],
            },
          },
          {
            'preparation': {
              'execution_options': {'simulation': false, 'hardware': false},
            },
          },
        ),
        false,
      );
      expect(
        review.simulationAvailable({
          'devices': {
            'devices': [
              {'mode': 'simulation'},
            ],
          },
        }),
        true,
      );
    },
  );
}
