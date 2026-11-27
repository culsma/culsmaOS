import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/view/execution_settings.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../layout/fixture.dart';

class ExecutionApi extends FakeConsoleApi {
  Map<String, dynamic> record = {
    'draft_id': 'station',
    'revision': 1,
    'title': 'Hamilton setup',
    'driver': 'hamilton',
    'configuration': {'mode': 'simulation'},
  };
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (['execution_options', 'select_execution'].contains(body['action'])) {
      calls.add({'path': path, ...LayoutData.copy(body)});
      if (error != null) throw error!;
      if (body['action'] == 'execution_options')
        return {
          'selected':
              record['configuration']['execution_selection'] ??
              {'mode': 'simulation', 'simulator': 'venus'},
          'implementations': [
            {
              'mode': 'simulation',
              'simulator': 'venus',
              'label': 'Hamilton VENUS simulator',
            },
            {
              'mode': 'physical',
              'simulator': null,
              'label': 'Hamilton hardware',
            },
          ],
        };
      record = {
        ...record,
        'revision': record['revision'] + 1,
        'configuration': <String, dynamic>{
          ...record['configuration'],
          'execution_selection': body['configuration'],
        },
      };
      return {'draft': record};
    }
    return super.command(path, body);
  }
}

LayoutController executionController(ExecutionApi api) {
  final c = LayoutController(api, pollInterval: Duration.zero);
  c.active = {
    'host': {'status': 'ready'},
    'active': {'fingerprint': 'before'},
  };
  c.selectDraft(api.record);
  return c;
}

void main() {
  test(
    'OS selection saves one revision; existing activation remains explicit',
    () async {
      final api = ExecutionApi();
      final controller = executionController(api);
      expect(
        (await controller.executionOptions())['implementations'],
        hasLength(2),
      );
      await controller.selectExecution({'mode': 'physical', 'simulator': null});
      expect(controller.draft!['revision'], 2);
      expect(controller.proposal!['execution_selection']['mode'], 'physical');
      expect(controller.active!['active']['fingerprint'], 'before');
      expect(api.calls.where((r) => r['action'] == 'apply'), isEmpty);
      await controller.validate();
      controller.confirm(true);
      await controller.apply();
      expect(api.calls.where((r) => r['action'] == 'apply'), hasLength(1));
      expect(controller.pendingRequest, isNull);
      controller.dispose();
    },
  );

  test(
    'unsaved edits and unknown writes cannot be replaced by a mode change',
    () async {
      final api = ExecutionApi();
      final controller = executionController(api);
      controller.edit({'mode': 'simulation', 'edited': true});
      await controller.selectExecution({'mode': 'physical', 'simulator': null});
      expect(api.calls, isEmpty);
      expect(controller.proposal!['edited'], isTrue);
      expect(controller.executionOptions(), throwsFormatException);
      controller.proposal = LayoutData.copy(controller.draft!['configuration']);
      api.error = const ConsoleApiError('timeout', responseUnknown: true);
      await controller.selectExecution({'mode': 'physical', 'simulator': null});
      expect(controller.writeUncertain, isTrue);
      await controller.selectExecution({'mode': 'physical', 'simulator': null});
      expect(api.calls, hasLength(1));
      expect(controller.draft!['revision'], 1);
      controller.dispose();
    },
  );

  testWidgets(
    'desktop mode selector saves through OS and offers explicit apply',
    (tester) async {
      final api = ExecutionApi();
      final c = executionController(api);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ExecutionSettings(controller: c),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Hamilton hardware').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save execution choice'));
      await tester.pumpAndSettle();
      expect(c.draft!['revision'], 2);
      expect(api.calls.where((r) => r['action'] == 'apply'), isEmpty);
      await tester.tap(find.text('Check saved setup'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Apply saved setup'));
      await tester.pumpAndSettle();
      expect(api.calls.where((r) => r['action'] == 'apply'), hasLength(1));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
    },
  );
}
