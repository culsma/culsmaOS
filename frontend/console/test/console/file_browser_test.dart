import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/interactor/file_browser_interactor.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/file_browser_view.dart';
import 'fixture.dart';
import '../layout/fixture.dart';

class FolderApi extends NativeConsoleFixtureApi {
  Completer<Map<String, dynamic>>? delayed;
  bool failRead = false;
  Map<String, dynamic> entry(String name, String kind, [String path = '']) => {
    'name': name,
    'path': path.isEmpty ? name : '$path/$name',
    'kind': kind,
    'extension': name.contains('.') ? '.${name.split('.').last}' : '',
    'openable': true,
    'size': kind == 'file' ? 18 : null,
  };
  @override
  Future<Map<String, dynamic>> command(
    String url,
    Map<String, dynamic> body,
  ) async {
    if (url != '/api/v1/files' || body['action'] == 'roots')
      return super.command(url, body);
    calls.add({'path': url, ...body});
    if (failRead) throw const ConsoleApiError('FILE_NOT_FOUND');
    if (body['action'] == 'preview') {
      if (body['path'] == 'slow.txt') return delayed!.future;
      return {'preview': 'text', 'content': 'Preview: ${body['path']}'};
    }
    final path = body['path'];
    return {
      'entries': path == ''
          ? [
              entry('folder', 'directory'),
              entry('notes.txt', 'file'),
              entry('slow.txt', 'file'),
            ]
          : [
              entry('run.culs', 'file', path)
                ..['program'] = {
                  'program_id': '$path/run.culs',
                  'source_scope': body['root'],
                },
            ],
      'total': path == '' ? 3 : 1,
      'next_offset': null,
    };
  }
}

void main() {
  test(
    'directory history, roots and refresh retain the current location without executing',
    () async {
      final api = FolderApi(), c = NativeFileBrowserInteractor(api);
      await c.initialize();
      expect(c.root, 'installation');
      expect(c.absolutePath, '/Culsma');
      await c.navigate('installation', 'folder');
      await c.refresh();
      expect(c.history.length, 2);
      expect(c.path, 'folder');
      await c.back();
      expect(c.path, '');
      await c.forward();
      expect(c.path, 'folder');
      await c.up();
      expect(c.path, '');
      expect(c.canForward, isFalse);
      await c.navigate('programs', '');
      expect(c.rootLabel, 'Experiments');
      expect(api.startCount, 0);
      c.dispose();
    },
  );
  test(
    'late preview never replaces another selection and directory failure retains location',
    () async {
      final api = FolderApi()..delayed = Completer(),
          c = NativeFileBrowserInteractor(api);
      await c.initialize();
      final delayed = c.select(c.entries.last);
      await c.select(c.entries[1]);
      api.delayed!.complete({'preview': 'text', 'content': 'late'});
      await delayed;
      expect(c.preview?['content'], 'Preview: notes.txt');
      api.failRead = true;
      await c.navigate('installation', 'missing');
      expect(c.path, '');
      expect(c.error, contains('FILE_NOT_FOUND'));
      expect(c.history.length, 1);
      c.dispose();
    },
  );
  testWidgets(
    'folders and preview are read-only; file run keeps installation source scope',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 700);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = FolderApi(), layout = LayoutFixture.controller();
      final c = NativeConsoleInteractor(
        api,
        layout,
        requests: MemoryPendingRequestRepository(),
      );
      await c.files.initialize();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AnimatedBuilder(
              animation: c,
              builder: (_, _) => NativeFileBrowserView(console: c),
            ),
          ),
        ),
      );
      await tester.tap(find.text('notes.txt'));
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();
      expect(find.text('Preview: notes.txt'), findsOneWidget);
      expect(api.startCount, 0);
      final folder = find.byKey(const Key('file-entry-installation-folder'));
      await tester.tap(folder);
      await tester.pump(const Duration(milliseconds: 60));
      await tester.tap(folder);
      await tester.pumpAndSettle();
      expect(c.files.path, 'folder');
      expect(api.startCount, 0);
      final file = find.byKey(
        const Key('file-entry-installation-folder/run.culs'),
      );
      await tester.tap(file);
      await tester.pump(const Duration(milliseconds: 60));
      await tester.tap(file);
      await tester.pumpAndSettle();
      expect(api.startCount, 0);
      await c.confirmLaunch();
      expect(api.startCount, 1);
      final start = api.calls.singleWhere((r) => r['action'] == 'start');
      expect(start['source_scope'], 'installation');
      expect(start['program_id'], 'folder/run.culs');
      expect(c.active?.view, 'experiment');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      layout.dispose();
    },
  );
  testWidgets('narrow window keeps navigation and root selection usable', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = FolderApi(),
        layout = LayoutFixture.controller(),
        c = NativeConsoleInteractor(api, layout);
    await c.files.initialize();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AnimatedBuilder(
            animation: c,
            builder: (_, _) => NativeFileBrowserView(console: c),
          ),
        ),
      ),
    );
    await tester.tap(find.text('notes.txt'));
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('files-up')), findsOneWidget);
    expect(find.byType(DropdownButton<String>), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    c.dispose();
    layout.dispose();
  });
}
