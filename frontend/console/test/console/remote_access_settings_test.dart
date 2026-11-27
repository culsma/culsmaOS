import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/remote_access_interactor.dart';
import 'package:culsma_console/features/console/view/remote_access_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class RemoteSettingsApi implements ConsoleApi {
  bool enabled = false;
  final pairings = <Map<String, dynamic>>[];

  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    expect(path, '/api/v1/remote-access');
    switch (body['action']) {
      case 'enable':
        enabled = true;
      case 'disable':
        enabled = false;
      case 'pair':
        pairings.add({'id': 'pair-1', 'name': body['name']});
      case 'unpair':
        expect(body['id'], 'pair-1');
        pairings.clear();
    }
    return {
      'enabled': enabled,
      'port': 8768,
      'pairings': pairings.toList(),
      if (body['action'] == 'pair') 'token': 'test-only-credential',
    };
  }

  @override
  Future<Map<String, dynamic>> read(String path) => throw UnimplementedError();

  @override
  void close() {}
}

void main() {
  test(
    'remote controller forwards actions and pairing details without retaining credentials',
    () async {
      final api = RemoteSettingsApi();
      final controller = RemoteAccessInteractor(api);
      expect((await controller.execute('status'))['enabled'], false);
      final paired = await controller.execute('pair', {
        'name': 'Test station',
        'action': 'disable',
      });
      expect(paired['token'], 'test-only-credential');
      expect((await controller.execute('status')).containsKey('token'), false);
      expect((await controller.execute('enable'))['enabled'], true);
      expect((await controller.execute('disable'))['enabled'], false);
      expect(
        (await controller.execute('unpair', {'id': 'pair-1'}))['pairings'],
        isEmpty,
      );
    },
  );

  testWidgets('operator can pair, enable, disable, and revoke', (tester) async {
    final api = RemoteSettingsApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: RemoteAccessSettings(controller: RemoteAccessInteractor(api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
      false,
    );

    await tester.tap(find.text('Pair a device'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Yang-Mac');
    await tester.tap(find.text('Pair'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.text('test-only-credential'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(find.text('test-only-credential'), findsNothing);
    expect(find.text('Yang-Mac'), findsOneWidget);

    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    expect(api.enabled, true);
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    expect(api.enabled, false);
    expect(find.text('Yang-Mac'), findsOneWidget);

    await tester.tap(find.text('Revoke'));
    await tester.pumpAndSettle();
    expect(find.text('Yang-Mac'), findsNothing);
  });
}
