import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/labware_interactor.dart';
import 'package:culsma_console/features/console/interactor/setup_interactor.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';
import 'mutation_fixture.dart';

void main() {
  test(
    'rack replacement is a separate settings selection; site editing never selects a rack',
    () async {
      final api = MutationFixtureApi(),
          c = NativeLabwareInteractor(api, MemoryConsoleMutationRepository());
      await c.observe(envelope());
      await c.edit({'item': 'rack', 'model': 'old-rack'});
      expect(c.target, isNull);
      await c.edit({'carrier': 'rack', 'model': 'old-rack'});
      expect(c.editingCarrier, isTrue);
      c.chooseModel('new-rack');
      expect(c.canSave, isTrue);
      c.chooseCategory('empty');
      expect(c.canSave, isFalse);
      c.chooseCategory('carrier');
      await c.save();
      expect(api.calls.firstWhere((r) => r['action'] == 'prepare')['change'], {
        'action': 'replace-carrier',
        'target': 'carrier:rack',
        'model': 'new-rack',
      });
      c.dispose();
    },
  );

  test(
    'remove unknown occupant; wait for observed active layout before closing',
    () async {
      final api = MutationFixtureApi(),
          store = MemoryConsoleMutationRepository(),
          c = NativeLabwareInteractor(api, store);
      await c.observe(envelope());
      await c.edit({'item': 'sample-plate', 'model': 'old-model'});
      c.chooseCategory('empty');
      await c.save();
      expect(c.pending, isNotNull);
      expect(c.editing, isTrue);
      expect(api.calls.firstWhere((r) => r['action'] == 'prepare')['change'], {
        'action': 'remove',
        'target': 'occupied',
      });
      api.applied = true;
      await c.checkStatus();
      expect(c.pending, isNotNull);
      await c.observe(envelope(updatedFingerprint));
      expect(c.pending, isNull);
      expect(c.editing, isFalse);
      expect(store.values, isEmpty);
      c.dispose();
    },
  );
  test(
    'empty site gets driver choices; save prepares and applies exactly once',
    () async {
      final api = MutationFixtureApi(),
          c = NativeLabwareInteractor(api, MemoryConsoleMutationRepository());
      await c.observe(envelope());
      await c.edit({'parent': 'rack', 'site': '2'});
      c.chooseCategory('reservoir');
      await c.save();
      expect(api.calls.firstWhere((r) => r['action'] == 'prepare')['change'], {
        'action': 'place',
        'target': 'vacant',
        'model': 'reservoir-model',
        'name': 'new-plate',
      });
      await c.save();
      await c.checkStatus();
      expect(api.calls.where((r) => r['action'] == 'apply').length, 1);
      c.dispose();
    },
  );
  test('stale station and failed durable storage prevent dispatch', () async {
    final api = MutationFixtureApi(),
        store = MemoryConsoleMutationRepository(),
        c = NativeLabwareInteractor(api, store);
    await c.observe(envelope());
    await c.edit({'parent': 'rack', 'site': '2'});
    c.chooseCategory('plate');
    await c.observe(envelope(updatedFingerprint));
    await c.save();
    expect(api.calls.where((r) => r['action'] == 'prepare'), isEmpty);
    await c.observe(envelope());
    store.failSave = true;
    await c.save();
    expect(api.calls.where((r) => r['action'] == 'apply'), isEmpty);
    expect(c.error, contains('disk unavailable'));
    c.dispose();
  });
  test(
    'lost layout response survives restart; observation does not resend',
    () async {
      final api = MutationFixtureApi()..lostApply = true,
          store = MemoryConsoleMutationRepository();
      final c = NativeLabwareInteractor(api, store);
      await c.observe(envelope());
      await c.edit({'item': 'sample-plate', 'model': 'old-model'});
      c.chooseCategory('empty');
      await c.save();
      final id = c.pending!['request_id'];
      c.dispose();
      final restored = NativeLabwareInteractor(api, store);
      await restored.restore();
      api.applied = true;
      await restored.observe(envelope(updatedFingerprint));
      expect(restored.pending, isNull);
      expect(api.calls.where((r) => r['action'] == 'apply').length, 1);
      expect(
        api.calls
            .where((r) => r['action'] == 'status')
            .every((r) => r['request_id'] == id),
        isTrue,
      );
      restored.dispose();
    },
  );
  test(
    'confirmation is explicit and invalidated when shared plan changes',
    () async {
      final api = MutationFixtureApi(),
          c = NativeSetupInteractor(api, MemoryConsoleMutationRepository());
      final run = {'run_id': 'loading-run', 'status': 'awaiting_setup'};
      await c.observe(run);
      await c.command('loading-run', 'confirm');
      expect(api.setupRequests, isEmpty);
      await c.command('loading-run', 'begin');
      await c.observe(run);
      await c.command('loading-run', 'confirm');
      expect(api.setupRequests.length, 1);
      c.acknowledge('loading-run', true);
      expect(c.dirty, isTrue);
      api.fingerprint = updatedFingerprint;
      await c.observe(run);
      expect(c.acknowledged('loading-run'), isFalse);
      await c.command('loading-run', 'confirm');
      expect(api.setupRequests.length, 1);
      c.acknowledge('loading-run', true);
      await c.command('loading-run', 'confirm');
      expect(api.calls.last['path'], '/api/v1/setup/confirmation');
      expect(api.setupRequests.last['acknowledged'], isTrue);
      c.dispose();
    },
  );
  test(
    'setup unknown response requires explicit retry with same identity',
    () async {
      final api = MutationFixtureApi()..lostSetup = true,
          c = NativeSetupInteractor(api, MemoryConsoleMutationRepository());
      final run = {'run_id': 'loading-run', 'status': 'awaiting_setup'};
      await c.observe(run);
      await c.command('loading-run', 'begin');
      final retained = c.pending['loading-run']!;
      await c.retry('loading-run');
      expect(api.setupRequests.length, 2);
      expect(api.setupRequests.last, retained);
      await c.observe(run);
      expect(c.pending, isEmpty);
      expect(api.setupRequests.length, 2);
      c.dispose();
    },
  );
  test(
    'stale preference edits survive refresh and cannot overwrite shared plan',
    () async {
      final api = MutationFixtureApi(),
          c = NativeSetupInteractor(api, MemoryConsoleMutationRepository());
      final run = {'run_id': 'loading-run', 'status': 'awaiting_setup'};
      await c.observe(run);
      c.setPreference('loading-run', 'allocation', 'fixed', {
        'labware': 'sample-plate',
        'well': 'A1',
      });
      api.fingerprint = updatedFingerprint;
      await c.observe(run);
      await c.command('loading-run', 'revise');
      expect(c.edits['loading-run']!['dirty'], isTrue);
      expect(api.setupRequests, isEmpty);
      c.reloadPreferences('loading-run');
      expect(c.dirty, isFalse);
      c.dispose();
    },
  );
  test(
    'durable slots serialize writes, survive reopen and reject credentials',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'native-mutation-test-',
      );
      try {
        final file = File('${directory.path}/pending.json'),
            store = FileConsoleMutationRepository(file);
        final layout = {
          'action': 'apply',
          'request_id': 'layout',
          'draft_id': 'draft',
          'revision': 1,
          'expected_fingerprint': originalFingerprint,
        };
        final setup = {
          'action': 'begin',
          'request_id': 'setup',
          'run_id': 'run',
          'fingerprint': originalFingerprint,
        };
        await Future.wait([
          store.save('labware', layout),
          store.save('setup:run', setup),
        ]);
        final restored = FileConsoleMutationRepository(file);
        expect(await restored.read('labware'), layout);
        expect(await restored.read('setup:run'), setup);
        await expectLater(
          restored.save('labware', {...layout, 'access_token': 'forbidden'}),
          throwsFormatException,
        );
        await restored.clear('labware');
        expect(await restored.read('setup:run'), setup);
        await file.writeAsString(
          jsonEncode({
            'labware': {'request_id': 1},
          }),
        );
        await expectLater(restored.read('labware'), throwsFormatException);
      } finally {
        await directory.delete(recursive: true);
      }
    },
  );
}
