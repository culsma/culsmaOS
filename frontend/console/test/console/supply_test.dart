import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/supply_interactor.dart';
import 'package:culsma_console/features/console/view/supply_panel.dart';
import 'fixture.dart';
import 'mutation_fixture.dart';

class SupplyApi extends NativeConsoleFixtureApi {
  bool lost = false, applied = false;
  String revision = originalFingerprint;
  Map<String, dynamic>? request;
  int replacements = 0;
  Map<String, dynamic> get stock => {
    'supported': true,
    'revision': revision,
    'resource_id': 'tips',
    'position_choices': ['1', '2'],
    'stock': {
      'ready': true,
      'used': ['1', '2'],
      'available': [],
      'load_id': 'initial',
    },
    'pending': [],
    'history': [],
    'current_load': applied ? {'request_id': request!['request_id']} : null,
  };
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (body['action'] == 'show') return stock;
    if (body['action'] == 'replace') {
      replacements++;
      request = Map.of(body);
      if (lost) throw ConsoleApiError('UNKNOWN', responseUnknown: true);
      applied = true;
    }
    return {
      'request_id': request!['request_id'],
      'status': applied ? 'applied' : 'applying',
    };
  }
}

void main() {
  test(
    'acknowledgment, durable storage and current revision are required',
    () async {
      final api = SupplyApi(),
          store = MemoryConsoleMutationRepository(),
          c = NativeSupplyInteractor(api, store);
      await c.refresh();
      c.open();
      await c.apply();
      expect(api.replacements, 0);
      c.acknowledge(true);
      store.failSave = true;
      await c.apply();
      expect(api.replacements, 0);
      store.failSave = false;
      api.revision = updatedFingerprint;
      await c.refresh();
      await c.apply();
      expect(api.replacements, 0);
      c.close();
      c.open();
      c.acknowledge(true);
      await c.apply();
      expect(api.replacements, 1);
      expect(c.pending, isNull);
      expect(c.editing, false);
      expect(store.values, isEmpty);
      c.dispose();
    },
  );
  test(
    'lost response survives restart and status never resends replacement',
    () async {
      final api = SupplyApi()..lost = true,
          store = MemoryConsoleMutationRepository();
      final c = NativeSupplyInteractor(api, store);
      await c.refresh();
      c.open();
      c.acknowledge(true);
      await c.apply();
      expect(c.pending, isNotNull);
      c.dispose();
      api.applied = true;
      final restored = NativeSupplyInteractor(api, store);
      await restored.restore();
      await restored.refresh();
      expect(restored.pending, isNull);
      expect(api.replacements, 1);
      expect(store.values, isEmpty);
      restored.dispose();
    },
  );
  testWidgets(
    'dialog makes simulated box declaration explicit before registration',
    (tester) async {
      final c = NativeSupplyInteractor(
        SupplyApi(),
        MemoryConsoleMutationRepository(),
      );
      await c.refresh();
      c.open();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: NativeSupplyDialog(controller: c)),
        ),
      );
      expect(find.text('Replace simulated tip box'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Register new box'),
            )
            .onPressed,
        isNull,
      );
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Register new box'),
            )
            .onPressed,
        isNotNull,
      );
      await tester.tap(find.widgetWithText(FilterChip, '2'));
      await tester.pump();
      expect(c.acknowledged, false);
      c.dispose();
    },
  );
}
