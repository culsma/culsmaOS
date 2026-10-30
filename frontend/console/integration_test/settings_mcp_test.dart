import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/console/interactor/renderer_interactor.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/recorded_deck.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'external MCP rack changes update the panel and retain unsaved human settings',
    (tester) async {
      final api = LocalConsoleApi(
        DesktopConnection(
          Uri.parse(Platform.environment['CULSMA_SETTINGS_TEST_ORIGIN']!),
          Platform.environment['CULSMA_SETTINGS_TEST_TOKEN']!,
        ),
      );
      final rendererApi = LocalConsoleApi(
        DesktopConnection(
          Uri.parse(Platform.environment['CULSMA_SETTINGS_TEST_ORIGIN']!),
          Platform.environment['CULSMA_SETTINGS_RENDERER_TOKEN']!,
        ),
      );
      final layout = LayoutController(api);
      final console = NativeConsoleInteractor(
        api,
        layout,
        initialView: 'settings',
      );
      final renderer = NativeRendererInteractor(rendererApi, console);
      try {
        await console.refresh();
        await layout.load();
        await layout.openDraft(
          Platform.environment['CULSMA_SETTINGS_BASE_DRAFT']!,
        );
        final originalFingerprint = layout.active!['active']['fingerprint'];
        layout.edit({...layout.proposal!, 'device_id': 'human-unsaved-device'});
        await tester.pumpWidget(
          CulsmaConsole(
            controller: layout,
            console: console,
            renderer: renderer,
          ),
        );
        await tester.pumpAndSettle();
        renderer.start();
        Map<String, dynamic>? finalStatus;
        for (var i = 0; i < 600; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
          if (!console.busy) await console.refresh();
          try {
            finalStatus = await api.command(
              '/api/v1/configuration/activation',
              {'action': 'status', 'request_id': 'mcp-vessel-remove'},
            );
            if (finalStatus['receipt']?['status'] == 'applied' &&
                finalStatus['host']?['status'] == 'ready')
              break;
          } on ConsoleApiError {
            /* The MCP client has not submitted the final operation yet. */
          }
        }
        expect(finalStatus?['receipt']?['status'], 'applied');
        await console.refresh();
        final active = console.station!['layout']['configuration_fingerprint'];
        expect(active, finalStatus!['active']['fingerprint']);
        expect(active, isNot(originalFingerprint));
        expect(layout.externalConfigurationChanged, isTrue);
        expect(layout.proposal!['device_id'], 'human-unsaved-device');
        expect(layout.canApply, isFalse);
        expect(layout.message, contains('unsaved layout is retained'));
        await tester.pumpAndSettle();
        var board = tester.widget<RecordedDeckBoard>(
          find.byType(RecordedDeckBoard),
        );
        expect(
          board.deck.carriers.firstWhere(
            (rack) => rack['id'] == 'PREVIEW_T37_38_4R200',
          )['model'],
          'RGT_CAR_5R60_A00',
        );
        // Explicitly discard the retained human proposal, then follow the latest saved active revision.
        layout.discard();
        await console.refresh();
        await tester.pumpAndSettle();
        expect(layout.externalConfigurationChanged, isFalse);
        expect(layout.dirty, isFalse);
        expect(
          layout.draft!['draft_id'],
          layout.active!['active']['origin']['draft_id'],
        );
        expect(find.text('Racks and carriers'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      } finally {
        await renderer.close();
        console.dispose();
        layout.dispose();
      }
    },
  );
}
