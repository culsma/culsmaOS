import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';

void main() {
  test(
    'native requests keep Origin, credential and exact UTF-8 body length',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final origin = Uri.parse('http://127.0.0.1:${server.port}');
      final api = LocalConsoleApi(DesktopConnection(origin, 'fixture-token'));
      final received = server.first.then((request) async {
        expect(request.headers.value('Origin'), origin.toString());
        expect(request.headers.value('Authorization'), 'Bearer fixture-token');
        final bytes = await request.fold<List<int>>(
          [],
          (all, part) => all..addAll(part),
        );
        expect(request.contentLength, bytes.length);
        expect(jsonDecode(utf8.decode(bytes))['title'], 'Setup µL');
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'data': {'saved': true},
          }),
        );
        await request.response.close();
      });
      expect(
        await api.command('/api/v1/configuration/drafts', {
          'title': 'Setup µL',
        }),
        {'saved': true},
      );
      await received;
      api.close();
      await server.close(force: true);
    },
  );
  test(
    'write errors distinguish known rejection from uncertain outcome',
    () async {
      for (final status in [401, 409, 503]) {
        final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
        final api = LocalConsoleApi(
          DesktopConnection(
            Uri.parse('http://127.0.0.1:${server.port}'),
            'fixture',
          ),
        );
        final received = server.first.then((request) async {
          await request.drain<void>();
          request.response.statusCode = status;
          request.response.write('{"error":{"code":"TEST_FAILURE"}}');
          await request.response.close();
        });
        await expectLater(
          api.command('/api/v1/configuration/drafts', {}),
          throwsA(
            isA<ConsoleApiError>().having(
              (e) => e.responseUnknown,
              'uncertainty',
              status >= 500,
            ),
          ),
        );
        await received;
        api.close();
        await server.close(force: true);
      }
    },
  );
}
