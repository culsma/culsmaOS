import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'fixture.dart';

void main() {
  test(
    'first setup is explicitly created without changing active station',
    () async {
      final c = LayoutController(FakeConsoleApi());
      c.profiles = [LayoutFixture.profile()];
      await c.createSetup(c.profiles.single);
      expect(c.draft!['draft_id'], 'new-setup');
      expect(c.active, isNull);
      expect(c.canApply, isFalse);
      expect(c.valid, isFalse);
    },
  );
  test(
    'unknown application keeps identity; status inspection never reissues apply',
    () async {
      final c = LayoutFixture.controller();
      final api = c.api as FakeConsoleApi;
      await c.validate();
      c.confirm(true);
      api.error = const ConsoleApiError('timeout', responseUnknown: true);
      await c.apply();
      final request = c.pendingRequest;
      expect(request, isNotNull);
      expect(c.writeUncertain, isTrue);
      await c.apply();
      api.error = null;
      await c.inspectPending();
      expect(api.calls.where((call) => call['action'] == 'apply').length, 1);
      expect(api.calls.last['request_id'], request);
      expect(c.pendingRequest, isNull);
      expect(c.writeUncertain, isFalse);
    },
  );
  test(
    'known application rejection clears pending identity and retains saved setup',
    () async {
      final c = LayoutFixture.controller();
      final api = c.api as FakeConsoleApi;
      await c.validate();
      c.confirm(true);
      api.error = const ConsoleApiError(
        'HOST_CONFIGURATION_STALE',
        status: 409,
      );
      await c.apply();
      expect(c.pendingRequest, isNull);
      expect(c.writeUncertain, isFalse);
      expect(c.draft!['revision'], 1);
      expect(c.message, 'HOST_CONFIGURATION_STALE');
    },
  );
  test(
    'edits are local; save validate and apply dispatch once in order',
    () async {
      final c = LayoutFixture.controller();
      final api = c.api as FakeConsoleApi;
      c.move(
        c.definition!.items(c.proposal!).firstWhere((i) => i.name == 'tubes'),
        '3',
      );
      expect(c.dirty, isTrue);
      expect(api.calls, isEmpty);
      expect(c.canApply, isFalse);
      await c.save();
      expect(c.dirty, isFalse);
      expect(c.draft!['revision'], 2);
      await c.validate();
      c.confirm(true);
      expect(c.canApply, isTrue);
      await c.apply();
      expect(api.calls.where((e) => e['action'] == 'apply').length, 1);
      expect(c.pendingRequest, isNull);
      expect(c.message, 'Layout applied. Station ready.');
      expect(c.active!['active']['origin']['revision'], 2);
    },
  );
  test('unknown save is blocked and never retried automatically', () async {
    final c = LayoutFixture.controller();
    final api = c.api as FakeConsoleApi;
    c.move(c.definition!.items(c.proposal!).first, '3');
    api.error = const ConsoleApiError('timeout', responseUnknown: true);
    await c.save();
    await c.save();
    expect(c.writeUncertain, isTrue);
    expect(c.dirty, isTrue);
    expect(api.calls.where((e) => e['action'] == 'save').length, 1);
    expect(c.canApply, isFalse);
  });
  test('revision conflict preserves edits and does not report saved', () async {
    final c = LayoutFixture.controller();
    final api = c.api as FakeConsoleApi;
    c.move(c.definition!.items(c.proposal!).first, '3');
    api.error = const ConsoleApiError(
      'CONFIGURATION_REVISION_CONFLICT',
      status: 409,
    );
    await c.save();
    expect(c.dirty, isTrue);
    expect(c.draft!['revision'], 1);
    expect(c.message, 'CONFIGURATION_REVISION_CONFLICT');
  });
  test(
    'refresh preserves unsaved proposal and exact origin mismatch rejects',
    () async {
      final c = LayoutFixture.controller();
      c.move(c.definition!.items(c.proposal!).first, '3');
      final before = LayoutData.canonical(c.proposal);
      await c.load();
      expect(LayoutData.canonical(c.proposal), before);
      c.proposal = null;
      (c.api as FakeConsoleApi).getRecord = {
        'draft_id': 'station',
        'revision': 2,
        'fingerprint': 'wrong',
      };
      await c.load();
      expect(c.proposal, isNull);
      expect(c.message, 'CURRENT_CONFIGURATION_IDENTITY_MISMATCH');
    },
  );
  test(
    'discard restores saved state; system status never becomes proposed layout',
    () {
      final c = LayoutFixture.controller();
      final before = LayoutData.canonical(c.active);
      c.move(c.definition!.items(c.proposal!).first, '3');
      c.discard();
      expect(c.dirty, isFalse);
      expect(LayoutData.canonical(c.active), before);
      c.dispose();
      expect((c.api as FakeConsoleApi).closed, isTrue);
    },
  );
  test('native connection rejects remote hosts and embedded credentials', () {
    for (final uri in [
      'https://127.0.0.1:2',
      'http://example.com',
      'http://x:y@127.0.0.1',
      'http://127.0.0.1/a',
    ]) {
      expect(
        () => DesktopConnection.fromJson({
          'schema': 'culsma_desktop_v1',
          'origin': uri,
          'access_token': 'x',
        }),
        throwsFormatException,
      );
    }
  });
}
