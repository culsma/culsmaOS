import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/interactor/renderer_interactor.dart';
import '../layout/fixture.dart';

class RendererFixtureApi extends FakeConsoleApi {
  String? outcome;
  final session = {
    'session_id': 'renderer',
    'epoch': 'generation',
    'revision': 0,
  };
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    calls.add(body);
    if (body['action'] == 'poll')
      return {
        'session': session,
        'requests': [
          {
            'request_id': 'request',
            'request': {'expected_revision': 0, 'view': 'system_info'},
          },
        ],
      };
    if (body['action'] == 'acknowledge') outcome = body['outcome'];
    return {'session': session};
  }
}

void main() {
  for (final blocked in ['dirty', 'hidden', 'labware edit', 'loading edit']) {
    test(
      'renderer defers $blocked presentation without issuing business commands',
      () async {
        final layout = LayoutFixture.controller(),
            c = NativeConsoleInteractor(layout.api, layout),
            api = RendererFixtureApi(),
            renderer = NativeRendererInteractor(api, c);
        if (blocked == 'dirty')
          layout.proposal!['unsaved'] = true;
        else if (blocked == 'labware edit')
          c.labware.editing = true;
        else if (blocked == 'loading edit')
          c.setup.edits['run'] = {'dirty': true};
        else
          renderer.visible = false;
        await renderer.poll();
        expect(api.outcome, 'deferred');
        expect(c.active?.view, 'files');
        expect(api.calls.map((v) => v['action']).toSet(), {
          'register',
          'poll',
          'acknowledge',
        });
        await renderer.close();
        c.dispose();
        layout.dispose();
      },
    );
  }
}
