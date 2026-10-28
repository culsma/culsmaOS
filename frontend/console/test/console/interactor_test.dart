import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/repository/pending_request_repository.dart';
import 'package:culsma_console/features/console/model/console_model.dart';
import '../layout/fixture.dart';
import 'fixture.dart';

void main() {
  test(
    'fixed windows restore identities; run windows remain distinct and close without business calls',
    () {
      final layout = LayoutFixture.controller(),
          c = NativeConsoleInteractor(layout.api, layout);
      final first = c.open('workstation');
      c.minimize(first);
      expect(first.minimized, true);
      expect(identical(c.open('workstation'), first), true);
      expect(first.minimized, false);
      final a = c.open('experiment', 'run-a'),
          b = c.open('experiment', 'run-b');
      c.closeWindow(a);
      expect(c.windows.contains(b), true);
      expect((layout.api as FakeConsoleApi).calls, isEmpty);
      c.dispose();
      layout.dispose();
    },
  );
  test('unsaved settings cannot close or minimize but survive switching', () {
    final layout = LayoutFixture.controller(),
        c = NativeConsoleInteractor(layout.api, layout);
    final settings = c.open('settings');
    layout.proposal!['changed'] = true;
    c.closeWindow(settings);
    expect(c.windows.contains(settings), true);
    c.minimize(settings);
    expect(settings.minimized, false);
    c.open('system_info');
    c.open('settings');
    expect(layout.proposal!['changed'], true);
    c.dispose();
    layout.dispose();
  });
  test(
    'unknown start is retained across coordinator restart and never automatically resent',
    () async {
      final api = NativeConsoleFixtureApi()..unknownStart = true,
          layout = LayoutFixture.controller(),
          repo = MemoryPendingRequestRepository();
      var c = NativeConsoleInteractor(api, layout, requests: repo);
      await c.launch('transfer.culs');
      final request = Map.of(repo.value!);
      expect(api.startCount, 1);
      c.dispose();
      c = NativeConsoleInteractor(api, layout, requests: repo);
      await c.start();
      expect(api.startCount, 1);
      expect(c.pendingStart, request);
      api.unknownStart = false;
      await c.checkPendingStart();
      expect(api.startCount, 2);
      expect(
        api.calls
            .where((v) => v['action'] == 'start')
            .map((v) => v['request_id'])
            .toSet()
            .length,
        1,
      );
      expect(c.active?.entityId, 'run-one');
      expect(repo.value, isNull);
      c.dispose();
      layout.dispose();
    },
  );
  test(
    'pending request repository persists only the exact request and rejects replacement',
    () async {
      final dir = await Directory.systemTemp.createTemp('native-request-');
      try {
        final file = File('${dir.path}/pending.json'),
            repo = FilePendingRequestRepository(file);
        final request = {
          'action': 'start',
          'request_id': 'request',
          'program_id': 'protocol.culs',
          'snapshot_id': 'snapshot',
        };
        await repo.save(request);
        expect(await repo.read(), request);
        await expectLater(
          repo.save({...request, 'request_id': 'different'}),
          throwsFormatException,
        );
        await repo.clear();
        expect(await repo.read(), isNull);
      } finally {
        await dir.delete(recursive: true);
      }
    },
  );
  test('recorded deck rejects out of bounds geometry', () {
    final envelope = {
      'status': 'available',
      'layout': {
        'definition': {
          'diagram': {
            'scene': {
              'positions': [
                {'id': '1'},
              ],
              'carriers': [
                {
                  'start': 0,
                  'span': 2,
                  'sites': ['1'],
                  'placements': [],
                },
              ],
            },
          },
        },
      },
    };
    expect(RecordedDeck.fromLayout(envelope), isNull);
  });
}
