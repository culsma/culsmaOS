import 'dart:io';
import 'package:flutter/material.dart';
import 'package:culsma_console/features/layout/repository/layout_archive_repository.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native UI applies a real layout and executes transfer on official simulator',
    (tester) async {
      const origin = String.fromEnvironment('E2E_ORIGIN');
      expect(origin, isNotEmpty, reason: 'Run through tools/test_desktop.py');
      // Explicit fixture credential, valid only in the isolated test server.
      final api = LocalConsoleApi(
        DesktopConnection(Uri.parse(origin), 'native-e2e-fixture-only'),
      );
      final controller = LayoutController(api);
      await controller.load();
      expect(controller.message, isNull);
      await tester.pumpWidget(CulsmaConsole(controller: controller));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const ValueKey('position-1')));
      await tester.tap(find.byKey(const ValueKey('position-1')));
      await tester.pumpAndSettle();
      final move = find.byType(DropdownButtonFormField<String>).last;
      await tester.ensureVisible(move);
      await tester.tap(move);
      await tester.pumpAndSettle();
      await tester.tap(find.text('3').last);
      await tester.pumpAndSettle();
      expect(controller.proposal!['labware']['tubes']['slot'], '3');
      await tester.ensureVisible(find.byKey(const ValueKey('position-4')));
      await tester.tap(find.byKey(const ValueKey('position-4')));
      await tester.pumpAndSettle();
      final catalogue = find.byType(DropdownButtonFormField<String>).last;
      await tester.ensureVisible(catalogue);
      await tester.tap(catalogue);
      await tester.pumpAndSettle();
      await tester.tap(find.text('96-well plate · Corning 360 uL').last);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('add-labware')));
      await tester.tap(find.byKey(const Key('add-labware')));
      await tester.pumpAndSettle();
      expect(controller.proposal!['labware']['labware_1']['slot'], '4');
      await tester.ensureVisible(find.byKey(const Key('save-layout')));
      await tester.tap(find.byKey(const Key('save-layout')));
      await waitIdle(tester, controller);
      expect(controller.dirty, isFalse);
      expect(controller.draft!['revision'], 2);
      await tester.ensureVisible(find.byKey(const Key('check-layout')));
      await tester.tap(find.byKey(const Key('check-layout')));
      await waitIdle(tester, controller);
      expect(controller.valid, isTrue, reason: controller.message);
      await tester.ensureVisible(find.byType(CheckboxListTile));
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      expect(controller.canApply, isTrue);
      await tester.ensureVisible(find.byKey(const Key('apply-layout')));
      await tester.tap(find.byKey(const Key('apply-layout')));
      await waitIdle(tester, controller);
      expect(controller.message, 'Layout applied. Station ready.');
      final current = await api.read('/api/v1/configuration/active');
      expect(current['active']['origin']['revision'], 2);
      final saved = await api.command('/api/v1/configuration/drafts', {
        'action': 'get',
        'draft_id': current['active']['origin']['draft_id'],
        'revision': 2,
      });
      expect(saved['draft']['configuration']['labware']['tubes']['slot'], '3');
      final inspected = await api.command('/api/v1/programs', {
        'action': 'inspect',
        'program_id': 'transfer.culs',
      });
      expect(inspected['valid'], isTrue);
      final submitted = await api.command('/api/v1/programs', {
        'action': 'submit',
        'program_id': 'transfer.culs',
        'snapshot_id': inspected['snapshot_id'],
        'request_id': 'native-e2e-transfer',
        'configuration_fingerprint': current['active']['fingerprint'],
      });
      final runId = submitted['run']['run_id'];
      Map<String, dynamic> result = {};
      for (var i = 0; i < 100; i++) {
        result = await api.read('/api/v1/runs/$runId');
        if ([
          'completed',
          'failed',
          'needs_reconciliation',
        ].contains(result['status']))
          break;
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
      expect(result['status'], 'completed');
      final containers =
          result['result']['os']['registered_material']['state']['containers']
              as Map;
      expect(
        containers.values.map((value) => value['volume_uL']).toList(),
        everyElement(100),
      );
      expect(containers.length, 2);
      final attempts = result['execution_evidence']['attempts'] as List;
      expect(attempts, isNotEmpty);
      expect(
        attempts.every(
          (a) =>
              a['evidence']['outcome'] == 'completed' &&
              a['registration']['status'] == 'registered',
        ),
        isTrue,
      );
      controller.dispose();
    },
  );
  testWidgets(
    'Hamilton proposal saves and validates without changing the active station',
    (tester) async {
      const origin = String.fromEnvironment('E2E_ORIGIN');
      final api = LocalConsoleApi(
        DesktopConnection(Uri.parse(origin), 'native-e2e-fixture-only'),
      );
      final controller = LayoutController(
        api,
        archives: FileLayoutArchiveRepository(),
      );
      await controller.load();
      final before = await api.read('/api/v1/configuration/active');
      expect(
        controller.profiles.any((p) => p['driver'] == 'hamilton-layout'),
        isTrue,
        reason:
            'Install the optional Hamilton configuration plugin before this cross-platform E2E',
      );
      await tester.pumpWidget(CulsmaConsole(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Open station setup'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('New: Hamilton · offline layout planning'));
      await waitIdle(tester, controller);
      expect(controller.profile!['driver'], 'hamilton-layout');
      await tester.ensureVisible(find.byKey(const ValueKey('position-1')));
      await tester.tap(find.byKey(const ValueKey('position-1')));
      await tester.pumpAndSettle();
      final carrier = find.widgetWithText(
        DropdownButtonFormField<String>,
        'Choose carrier',
      );
      await tester.ensureVisible(carrier);
      await tester.tap(carrier);
      await tester.pumpAndSettle();
      await tester.tap(
        find.text('5-site deep-well plate carrier · 6 tracks').last,
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('labware-name')), 'plates');
      await tester.ensureVisible(find.byKey(const Key('add-labware')));
      await tester.tap(find.byKey(const Key('add-labware')));
      await tester.pumpAndSettle();
      final site = find.widgetWithText(
        DropdownButtonFormField<String>,
        'Empty carrier site',
      );
      await tester.ensureVisible(site);
      await tester.tap(site);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Site 1').last);
      await tester.pumpAndSettle();
      final model = find.widgetWithText(
        DropdownButtonFormField<String>,
        'Compatible labware',
      );
      await tester.ensureVisible(model);
      await tester.tap(model);
      await tester.pumpAndSettle();
      await tester.tap(find.text('96-position deep-well plate').last);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('site-labware-name')),
        'source',
      );
      await tester.ensureVisible(find.byKey(const Key('place-site-labware')));
      await tester.tap(find.byKey(const Key('place-site-labware')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Edit placement'));
      await tester.tap(find.text('Edit placement'));
      await tester.pumpAndSettle();
      final replacement = find.byKey(
        const ValueKey('replace-carriers/plates-CAR_5DWP'),
      );
      await tester.ensureVisible(replacement);
      await tester.tap(replacement);
      await tester.pumpAndSettle();
      await tester.tap(find.text('5-site plate carrier · 7 tracks').last);
      await tester.pumpAndSettle();
      final relocated = find.byKey(
        const ValueKey('relocate-labware/source-plates-1'),
      );
      await tester.ensureVisible(relocated);
      await tester.tap(relocated);
      await tester.pumpAndSettle();
      await tester.tap(find.text('plates · Site 5').last);
      await tester.pumpAndSettle();
      expect(
        controller.proposal!['carriers']['plates']['model'],
        'PLT_CAR_L5FLEX_MD_A00',
      );
      expect(controller.proposal!['labware']['source']['site'], '5');
      await tester.ensureVisible(find.byKey(const Key('save-layout')));
      await tester.tap(find.byKey(const Key('save-layout')));
      await waitIdle(tester, controller);
      await tester.ensureVisible(find.byKey(const Key('check-layout')));
      await tester.tap(find.byKey(const Key('check-layout')));
      await waitIdle(tester, controller);
      expect(controller.valid, isTrue, reason: controller.message);
      expect(controller.canApply, isFalse);
      await expectLater(
        api.command('/api/v1/configuration/activation', {
          'action': 'apply',
          'draft_id': controller.draft!['draft_id'],
          'revision': controller.draft!['revision'],
          'expected_fingerprint': before['active']['fingerprint'],
          'request_id': 'offline-proposal-must-not-apply',
        }),
        throwsA(
          isA<ConsoleApiError>().having(
            (e) => e.code,
            'code',
            'CONFIGURATION_OFFLINE_ONLY',
          ),
        ),
      );
      final after = await api.read('/api/v1/configuration/active');
      expect(after['active']['fingerprint'], before['active']['fingerprint']);
      expect(controller.proposal!['labware']['source']['site'], '5');
      expect(
        controller.profile!['layout_export_supported'],
        isTrue,
        reason: 'Set CULSMA_HAMILTON_LABWARE_ROOT for native export E2E',
      );
      await tester.ensureVisible(find.byKey(const Key('export-native-layout')));
      await tester.tap(find.byKey(const Key('export-native-layout')));
      await waitIdle(tester, controller);
      expect(controller.exportedLayout, isNotNull, reason: controller.message);
      final archive = File(controller.exportedLayout!);
      final bytes = await archive.readAsBytes();
      expect(bytes.take(2).toList(), [80, 75]);
      expect(
        (await api.read(
          '/api/v1/configuration/active',
        ))['active']['fingerprint'],
        before['active']['fingerprint'],
      );
      await archive.parent.delete(recursive: true);
      controller.dispose();
    },
    skip: !const bool.fromEnvironment('E2E_HAMILTON'),
  );
}

Future<void> waitIdle(WidgetTester tester, LayoutController controller) async {
  for (var i = 0; i < 300 && controller.busy; i++) {
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
  await tester.pumpAndSettle();
  expect(controller.busy, isFalse);
}
