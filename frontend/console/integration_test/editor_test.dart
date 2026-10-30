import 'dart:io';
import 'console/interactor/drop_interactor_cases.dart';
import 'package:culsma_console/features/console/interactor/renderer_interactor.dart';
import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/app.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native drop provider -> actual files -> editor -> save -> language check',
    (tester) async {
      final origin = Platform.environment['CULSMA_EDITOR_TEST_ORIGIN']!;
      final token = Platform.environment['CULSMA_EDITOR_TEST_TOKEN']!;
      final inputs = await Directory.systemTemp.createTemp(
        'culsma-editor-input-',
      );
      final source = '${inputs.path}/protocol.culs';
      await File(
        source,
      ).writeAsString('let sample=tube(capacity=200uL);return sample;');
      final api = LocalConsoleApi(DesktopConnection(Uri.parse(origin), token));
      final layout = LayoutController(api);
      final console = NativeConsoleInteractor(api, layout);
      try {
        await console.files.initialize();
        await tester.pumpWidget(
          CulsmaConsole(controller: layout, console: console),
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        debugPrint('EDITOR_E2E: native drop');
        final target = tester.widget<DropTarget>(
          find.byKey(const Key('experiment-file-drop')),
        );
        await target.onDrop(
          DropDetails(
            items: [DropFileItem.fromPath(source)],
            localPosition: Offset.zero,
            globalPosition: Offset.zero,
            operation: DropOperation.copy,
          ),
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        expect(console.files.error, isNull, reason: console.files.error);
        expect(
          (await api.command('/api/v1/files/workspace', {
            'action': 'read',
            'path': 'protocol.culs',
          }))['content'],
          contains('200uL'),
        );
        expect(console.runs, isEmpty);
        await tester.tap(
          find.byKey(const ValueKey('file-entry-programs-protocol.culs')),
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        await tester.pump(const Duration(milliseconds: 400));
        expect(console.files.selected?['program'], isNotNull);
        expect(find.byKey(const Key('files-edit')), findsOneWidget);
        debugPrint('EDITOR_E2E: before context menu');
        // Exercise the actual secondary-click gesture and menu, not just the toolbar callback.
        await tester.tap(
          find.byKey(const ValueKey('file-entry-programs-protocol.culs')),
          buttons: kSecondaryMouseButton,
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        debugPrint('EDITOR_E2E: context menu opened');
        expect(find.byType(PopupMenuItem<String>), findsNWidgets(2));
        await tester.tap(find.widgetWithText(PopupMenuItem<String>, 'Edit'));
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        debugPrint('EDITOR_E2E: editor opened');
        expect(console.active!.view, 'editor');
        for (
          var i = 0;
          i < 100 && !console.editor.document('protocol.culs').loaded;
          i++
        ) {
          await tester.pump(const Duration(milliseconds: 50));
          await Future<void>.delayed(const Duration(milliseconds: 20));
        }
        await tester.enterText(
          find.byKey(const Key('protocol-editor')),
          'let sample=tube(capacity=300uL);return sample;',
        );
        await tester.pump();
        expect(console.editor.document('protocol.culs').dirty, isTrue);
        await tester.tap(find.byKey(const Key('editor-save')));
        for (
          var i = 0;
          i < 100 && console.editor.document('protocol.culs').busy;
          i++
        ) {
          await tester.pump(const Duration(milliseconds: 50));
          await Future<void>.delayed(const Duration(milliseconds: 20));
        }
        expect(console.editor.document('protocol.culs').error, isNull);
        expect(
          (await api.command('/api/v1/files/workspace', {
            'action': 'read',
            'path': 'protocol.culs',
          }))['content'],
          contains('300uL'),
        );
        await tester.tap(find.byKey(const Key('editor-check')));
        for (
          var i = 0;
          i < 100 && console.editor.document('protocol.culs').busy;
          i++
        ) {
          await tester.pump(const Duration(milliseconds: 50));
          await Future<void>.delayed(const Duration(milliseconds: 20));
        }
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        expect(
          console.editor.document('protocol.culs').inspection?['valid'],
          isTrue,
        );
        expect(find.text('Checks passed'), findsOneWidget);
        // Real external writer: an unsaved editor must preserve its buffer and surface a conflict.
        await tester.tap(find.byKey(const Key('protocol-editor')));
        await tester.pump(const Duration(milliseconds: 200));
        await tester.enterText(
          find.byKey(const Key('protocol-editor')),
          'let sample=tube(capacity=400uL);return sample;',
        );
        expect(
          console.editor.document('protocol.culs').text,
          contains('400uL'),
        );
        final other = await api.command('/api/v1/files/workspace', {
          'action': 'read',
          'path': 'protocol.culs',
        });
        await api.command('/api/v1/files/workspace', {
          'action': 'save',
          'path': 'protocol.culs',
          'content': 'let sample=tube(capacity=500uL);return sample;',
          'expected_revision': other['revision'],
        });
        expect(await console.editor.save('protocol.culs'), isFalse);
        await tester.pump();
        expect(
          console.editor.document('protocol.culs').text,
          contains('400uL'),
        );
        expect(
          console.editor.document('protocol.culs').error,
          contains('changed outside'),
        );
        expect(
          (await api.command('/api/v1/files/workspace', {
            'action': 'read',
            'path': 'protocol.culs',
          }))['content'],
          contains('500uL'),
        );
        expect(console.runs, isEmpty);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      } finally {
        console.dispose();
        layout.dispose();
        api.close();
        await inputs.delete(recursive: true);
      }
    },
  );
  testWidgets(
    'real editor state: background refresh, stale checks, reload and close protection',
    (tester) async {
      final api = LocalConsoleApi(
        DesktopConnection(
          Uri.parse(Platform.environment['CULSMA_EDITOR_TEST_ORIGIN']!),
          Platform.environment['CULSMA_EDITOR_TEST_TOKEN']!,
        ),
      );
      final layout = LayoutController(api);
      final console = NativeConsoleInteractor(api, layout);
      final editor = console.editor;
      const path = 'state-protocol.culs';
      try {
        expect(
          await editor.create(
            path,
            'let sample=tube(capacity=200uL);return sample;',
          ),
          isTrue,
        );
        final doc = editor.document(path);
        editor.edit(path, 'let sample=tube(capacity=250uL);return sample;');
        final checkingDuringSave = editor.check(path);
        editor.edit(path, 'let sample=tube(capacity=275uL);return sample;');
        await checkingDuringSave;
        expect(doc.dirty, isTrue);
        expect(
          doc.inspection,
          isNull,
          reason:
              'A check must never describe an unsaved buffer edited during its initial save.',
        );
        await editor.check(path);
        expect(doc.inspection?['valid'], isTrue);
        final inspection = doc.inspection;
        var notifications = 0;
        void observed() => notifications++;
        editor.addListener(observed);
        await editor.refresh(path);
        expect(
          notifications,
          0,
          reason: 'Unchanged background reads must not rebuild the page.',
        );
        expect(identical(doc.inspection, inspection), isTrue);
        // The actual HTTP request is in flight when the user types; its old check must be ignored.
        final checking = editor.check(path);
        editor.edit(path, 'let sample = ;');
        await checking;
        expect(doc.inspection, isNull);
        await editor.check(path);
        expect(doc.inspection?['valid'], isFalse);
        expect(doc.inspection?['diagnostics'][0]['span'], {
          'line': 1,
          'col': 14,
        });
        expect(
          doc.dirty,
          isFalse,
          reason: 'Check saves the actual edited source first.',
        );
        editor.edit(path, 'let sample=tube(capacity=300uL);return sample;');
        final window = console.open('editor', path);
        console.closeWindow(window);
        expect(console.windows, contains(window));
        expect(console.message, contains('Save your edits'));
        final external = await api.command('/api/v1/files/workspace', {
          'action': 'save',
          'path': path,
          'content': 'let sample=tube(capacity=500uL);return sample;',
          'expected_revision': doc.revision,
        });
        await editor.refresh(path);
        expect(doc.externalChange, isTrue);
        expect(doc.text, contains('300uL'));
        notifications = 0;
        await editor.refresh(path);
        expect(notifications, 0);
        await editor.load(path);
        expect(
          doc.text,
          contains('300uL'),
          reason: 'Explicit reload without discard must also preserve edits.',
        );
        await editor.load(path, discard: true);
        expect(doc.text, contains('500uL'));
        expect(doc.revision, external['revision']);
        expect(doc.dirty, isFalse);
        expect(doc.externalChange, isFalse);
        // A clean buffer follows external changes; a stale language result is removed.
        await editor.check(path);
        await api.command('/api/v1/files/workspace', {
          'action': 'save',
          'path': path,
          'content': 'let sample=tube(capacity=600uL);return sample;',
          'expected_revision': doc.revision,
        });
        await editor.refresh(path);
        expect(doc.text, contains('600uL'));
        expect(doc.inspection, isNull);
        console.closeWindow(window);
        expect(console.windows, isNot(contains(window)));
        expect(await editor.create(path, 'must not replace'), isFalse);
        expect(doc.text, contains('600uL'));
        expect(doc.error, contains('already exists'));
        expect(await editor.create('bad-name.txt', 'wrong type'), isFalse);
        await editor.load('missing.culs');
        expect(editor.document('missing.culs').loaded, isFalse);
        expect(editor.document('missing.culs').error, isNotNull);
        editor.removeListener(observed);
        expect(console.runs, isEmpty);
      } finally {
        console.dispose();
        layout.dispose();
        api.close();
      }
    },
  );

  testWidgets(
    'native New protocol and Save As dialogs preserve data across repeated cancellation',
    (tester) async {
      final api = LocalConsoleApi(
        DesktopConnection(
          Uri.parse(Platform.environment['CULSMA_EDITOR_TEST_ORIGIN']!),
          Platform.environment['CULSMA_EDITOR_TEST_TOKEN']!,
        ),
      );
      final layout = LayoutController(api),
          console = NativeConsoleInteractor(api, layout);
      try {
        await console.files.initialize();
        await console.files.navigate('programs', '');
        await tester.pumpWidget(
          CulsmaConsole(controller: layout, console: console),
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        for (var i = 0; i < 3; i++) {
          await tester.tap(find.byKey(const Key('files-new-protocol')));
          await tester.pumpAndSettle(
            const Duration(milliseconds: 100),
            EnginePhase.sendSemanticsUpdate,
            const Duration(seconds: 5),
          );
          await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
          await tester.pumpAndSettle(
            const Duration(milliseconds: 100),
            EnginePhase.sendSemanticsUpdate,
            const Duration(seconds: 5),
          );
          expect(tester.takeException(), isNull);
        }
        await tester.tap(find.byKey(const Key('files-new-protocol')));
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        await tester.enterText(
          find.byKey(const Key('new-protocol-name')),
          'created-in-app.culs',
        );
        await tester.tap(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.widgetWithText(FilledButton, 'Save'),
          ),
        );
        await waitForEditor(tester, console, 'created-in-app.culs');
        expect(console.active?.view, 'editor');
        await tester.tap(find.byKey(const Key('protocol-editor')));
        await tester.enterText(
          find.byKey(const Key('protocol-editor')),
          'let x=tube(capacity=250uL);return x;',
        );
        await tester.pump();
        for (var i = 0; i < 3; i++) {
          await tester.tap(find.widgetWithText(OutlinedButton, 'Save As'));
          await tester.pumpAndSettle(
            const Duration(milliseconds: 100),
            EnginePhase.sendSemanticsUpdate,
            const Duration(seconds: 5),
          );
          await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
          await tester.pumpAndSettle(
            const Duration(milliseconds: 100),
            EnginePhase.sendSemanticsUpdate,
            const Duration(seconds: 5),
          );
          expect(console.editor.document('created-in-app.culs').dirty, isTrue);
          expect(tester.takeException(), isNull);
        }
        await tester.tap(find.widgetWithText(OutlinedButton, 'Save As'));
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        await tester.enterText(
          find.byKey(const Key('new-protocol-name')),
          'saved-copy.culs',
        );
        await tester.tap(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.widgetWithText(FilledButton, 'Save'),
          ),
        );
        await waitForEditor(tester, console, 'saved-copy.culs');
        expect(console.active?.entityId, 'saved-copy.culs');
        expect(
          console.editor.document('saved-copy.culs').text,
          contains('250uL'),
        );
        expect(console.editor.document('created-in-app.culs').dirty, isTrue);
        final original = await api.command('/api/v1/files/workspace', {
          'action': 'read',
          'path': 'created-in-app.culs',
        });
        expect(original['content'], isNot(contains('250uL')));
        // Reload confirmation: cancel preserves edits; explicit discard restores the saved copy.
        await tester.tap(
          find.descendant(
            of: find.byKey(const ValueKey('view-editor:saved-copy.culs')),
            matching: find.byKey(const Key('protocol-editor')),
          ),
        );
        await tester.enterText(
          find.descendant(
            of: find.byKey(const ValueKey('view-editor:saved-copy.culs')),
            matching: find.byKey(const Key('protocol-editor')),
          ),
          'unsaved',
        );
        await tester.tap(
          find.descendant(
            of: find.byKey(const ValueKey('view-editor:saved-copy.culs')),
            matching: find.widgetWithText(OutlinedButton, 'Reload'),
          ),
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        await tester.tap(find.text('Keep editing'));
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        expect(console.editor.document('saved-copy.culs').text, 'unsaved');
        await tester.tap(
          find.descendant(
            of: find.byKey(const ValueKey('view-editor:saved-copy.culs')),
            matching: find.widgetWithText(OutlinedButton, 'Reload'),
          ),
        );
        await tester.pumpAndSettle(
          const Duration(milliseconds: 100),
          EnginePhase.sendSemanticsUpdate,
          const Duration(seconds: 5),
        );
        await tester.tap(find.text('Discard and reload'));
        await waitForEditor(tester, console, 'saved-copy.culs');
        expect(
          console.editor.document('saved-copy.culs').text,
          contains('250uL'),
        );
        expect(console.runs, isEmpty);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      } finally {
        console.dispose();
        layout.dispose();
        api.close();
      }
    },
  );
  testWidgets(
    'official external MCP edits source and presents native editor while preserving human edits',
    (tester) async {
      final origin = Uri.parse(
        Platform.environment['CULSMA_EDITOR_TEST_ORIGIN']!,
      );
      final api = LocalConsoleApi(
        DesktopConnection(
          origin,
          Platform.environment['CULSMA_EDITOR_TEST_TOKEN']!,
        ),
      );
      final rendererApi = LocalConsoleApi(
        DesktopConnection(
          origin,
          Platform.environment['CULSMA_EDITOR_RENDERER_TOKEN']!,
        ),
      );
      final layout = LayoutController(api);
      final console = NativeConsoleInteractor(api, layout);
      final renderer = NativeRendererInteractor(rendererApi, console);
      try {
        await console.files.initialize();
        await tester.pumpWidget(
          CulsmaConsole(
            controller: layout,
            console: console,
            renderer: renderer,
          ),
        );
        renderer.start();
        for (var i = 0; i < 400; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
          if (console.active?.view == 'editor' &&
              console.editor.document('from-ai.culs').text.contains('350uL'))
            break;
        }
        expect(console.active?.entityId, 'from-ai.culs');
        final doc = console.editor.document('from-ai.culs');
        expect(doc.text, contains('350uL'));
        expect(
          console.activity.any(
            (v) => v['action'] == 'file.save' && v['phase'] == 'returned',
          ),
          isTrue,
        );
        expect(find.textContaining('Console activity'), findsOneWidget);
        await tester.tap(find.byKey(const Key('protocol-editor')));
        await tester.enterText(
          find.byKey(const Key('protocol-editor')),
          doc.text.replaceFirst('350uL', '375uL'),
        );
        for (
          var i = 0;
          i < 300 && !renderer.completed.containsKey('mcp-preserve-edit');
          i++
        ) {
          await tester.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        expect(renderer.completed['mcp-preserve-edit']?['outcome'], 'deferred');
        expect(console.active?.view, 'editor');
        expect(doc.text, contains('375uL'));
        expect(doc.dirty, isTrue);
        expect(console.runs, isEmpty);
        expect(tester.takeException(), isNull);
        // Leave the renderer alive until the MCP client receives its final durable receipt.
        await Future<void>.delayed(const Duration(milliseconds: 500));
        await tester.pumpWidget(const SizedBox());
      } finally {
        await renderer.close();
        console.dispose();
        layout.dispose();

        api.close();
      }
    },
    skip: Platform.environment['CULSMA_EDITOR_MCP_TEST'] != '1',
  );
  group("native drop provider limits", registerDropInteractorTests);
}

Future<void> waitForEditor(
  WidgetTester tester,
  NativeConsoleInteractor console,
  String path,
) async {
  for (var i = 0; i < 150; i++) {
    await tester.pump(const Duration(milliseconds: 50));
    await Future<void>.delayed(const Duration(milliseconds: 20));
    final doc = console.editor.document(path);
    if (doc.loaded && !doc.busy && console.active?.entityId == path) {
      await tester.pumpAndSettle(
        const Duration(milliseconds: 100),
        EnginePhase.sendSemanticsUpdate,
        const Duration(seconds: 5),
      );
      return;
    }
  }
  fail(
    'Editor did not finish loading $path: ${console.editor.document(path).error}',
  );
}
