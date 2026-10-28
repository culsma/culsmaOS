import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/run_control_interactor.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';
import 'package:culsma_console/features/console/view/run_control_panel.dart';
import 'fixture.dart';
import 'mutation_fixture.dart';

class ControlApi extends NativeConsoleFixtureApi {
  String status = 'pending';
  bool lost = false, mismatch = false;
  int writes = 0, reads = 0;
  Map<String, dynamic>? payload;
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (body['action'] == 'control-status')
      reads++;
    else {
      writes++;
      payload = Map.of(body);
      if (lost) throw const ConsoleApiError('LOST', responseUnknown: true);
    }
    return {
      'acknowledgement': {
        ...payload!,
        'request_id': mismatch ? 'other' : payload!['request_id'],
        'status': status,
      },
    };
  }
}

const running = {'run_id': 'run', 'status': 'running'};
void main() {
  test(
    'acknowledged control is pending until matching worker receipt; no automatic replay',
    () async {
      final api = ControlApi(),
          repo = MemoryConsoleMutationRepository(),
          c = NativeRunControlInteractor(api, repo);
      await c.observe(running);
      await c.command(running, 'pause');
      expect(c.pending['run'], isNotNull);
      expect(c.receipts['run']!['status'], 'pending');
      expect(c.actions(running), isEmpty);
      await c.observe(running);
      expect(api.writes, 1);
      expect(api.reads, 1);
      api.status = 'applied';
      await c.observe({'run_id': 'run', 'status': 'paused'});
      expect(c.pending, isEmpty);
      expect(repo.values, isEmpty);
      expect(c.actions({'run_id': 'run', 'status': 'paused'}), [
        'resume',
        'cancel',
      ]);
      c.dispose();
    },
  );
  test(
    'lost response persists across restart; explicit retry uses exact identity',
    () async {
      final api = ControlApi()..lost = true,
          repo = MemoryConsoleMutationRepository();
      var c = NativeRunControlInteractor(api, repo);
      await c.command(running, 'cancel');
      final saved = Map.of(repo.values['control:run']!);
      c.dispose();
      c = NativeRunControlInteractor(api, repo);
      await c.observe(running);
      expect(api.writes, 1);
      expect(c.pending['run'], saved);
      api.lost = false;
      await c.retry('run');
      expect(api.writes, 2);
      expect(api.payload, saved);
      api.status = 'rejected';
      await c.check('run');
      expect(c.pending, isEmpty);
      expect(c.receipts['run']!['status'], 'rejected');
      c.dispose();
    },
  );
  test(
    'failed durable save, mismatched receipt and unknown execution do not enable unsafe control',
    () async {
      final api = ControlApi(),
          repo = MemoryConsoleMutationRepository()..failSave = true,
          c = NativeRunControlInteractor(api, repo);
      await c.command(running, 'pause');
      expect(api.writes, 0);
      repo.failSave = false;
      api.mismatch = true;
      await c.command(running, 'pause');
      expect(c.pending['run'], isNotNull);
      expect(c.errors['run'], contains('does not match'));
      expect(
        c.actions({'run_id': 'other', 'status': 'needs_reconciliation'}),
        isEmpty,
      );
      c.dispose();
    },
  );
  test(
    'file store retains controls without credentials and rejects identity replacement',
    () async {
      final dir = await Directory.systemTemp.createTemp('native-controls-');
      try {
        final store = FileConsoleMutationRepository(
          File('${dir.path}/pending.json'),
        );
        final value = {'action': 'pause', 'run_id': 'run', 'request_id': 'one'};
        await store.save('control:run', value);
        expect(await store.read('control:run'), value);
        await expectLater(
          store.save('control:run', {...value, 'request_id': 'two'}),
          throwsFormatException,
        );
        await expectLater(
          store.save('control:other', value),
          throwsFormatException,
        );
        await store.clear('control:run');
        expect(await store.read('control:run'), isNull);
      } finally {
        await dir.delete(recursive: true);
      }
    },
  );
  testWidgets(
    'run controls follow state and never imply immediate hardware interruption',
    (tester) async {
      final c = NativeRunControlInteractor(
        ControlApi(),
        MemoryConsoleMutationRepository(),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: NativeRunControlPanel(controller: c, run: running),
          ),
        ),
      );
      expect(find.text('Pause run'), findsOneWidget);
      expect(find.text('Resume run'), findsNothing);
      await tester.tap(find.text('Pause run'));
      await tester.pumpAndSettle();
      expect(find.textContaining('request retained'), findsOneWidget);
      expect(find.text('Check control status'), findsOneWidget);
      expect(find.text('Pause run'), findsNothing);
      c.dispose();
    },
  );
}
