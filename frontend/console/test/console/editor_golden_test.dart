import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/console/interactor/console_interactor.dart';
import 'package:culsma_console/features/console/view/protocol_editor_view.dart';

void main() {
  setUpAll(() async {
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
    await (FontLoader(
      'Code',
    )..addFont(rootBundle.load('assets/fonts/RobotoMono.ttf'))).load();
    await (FontLoader('Console')
          ..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))
          ..addFont(rootBundle.load('assets/fonts/Roboto-Medium.ttf')))
        .load();
  });
  testWidgets('native editor with original grammar and file commands', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1100, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = LocalConsoleApi(
      DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
    );
    final layout = LayoutController(api);
    final console = NativeConsoleInteractor(api, layout);
    final document = console.editor.document('standard-dilution.culs');
    document.text = document.savedText =
        '// Prepare a source and an empty destination.\nlet source=tube(capacity=2000uL,\n  load=[content(kind=formulation,type=buffer,code="BUFFER"):200uL]);\nlet destination=tube(capacity=2000uL);\ndestination << [source:100uL];\nreturn destination;';
    document.loaded = true;
    document.revision = '0' * 64;
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          fontFamily: 'Console',
          colorSchemeSeed: const Color(0xff193c61),
          brightness: Brightness.light,
        ),
        home: Scaffold(
          body: NativeProtocolEditorView(console: console, path: document.path),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('editor-save')), findsOneWidget);
    expect(find.byKey(const Key('editor-check')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/protocol-editor.png'),
    );
    await tester.pumpWidget(const SizedBox());
    console.dispose();
    layout.dispose();
    api.close();
  });
  testWidgets('narrow editor shows readable conflicts and source diagnostics', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(650, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = LocalConsoleApi(
      DesktopConnection(Uri.parse('http://127.0.0.1:1'), 'unused'),
    );
    final layout = LayoutController(api);
    final console = NativeConsoleInteractor(api, layout);
    final doc = console.editor.document('assay.culs');
    doc.text = '// An incomplete expression.\nlet sample = ;';
    doc.savedText =
        '// An incomplete expression.\nlet sample = tube(capacity=200uL);';
    doc.loaded = true;
    doc.revision = '0' * 64;
    doc.externalChange = true;
    doc.error = console.editor.explain(
      const ConsoleApiError('FILE_REVISION_CONFLICT'),
    );
    doc.inspection = {
      'valid': false,
      'diagnostics': [
        {
          'message': 'Expected an expression',
          'span': {'line': 2, 'col': 14},
        },
      ],
    };
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          fontFamily: 'Console',
          colorSchemeSeed: const Color(0xff193c61),
          brightness: Brightness.light,
        ),
        home: Scaffold(
          body: NativeProtocolEditorView(console: console, path: doc.path),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('Your edits are retained'), findsWidgets);
    expect(
      find.text('Line 2, column 14: Expected an expression'),
      findsOneWidget,
    );
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/protocol-editor-conflict.png'),
    );
    await tester.tap(find.text('Line 2, column 14: Expected an expression'));
    await tester.pump();
    final field = tester.widget<TextField>(
      find.byKey(const Key('protocol-editor')),
    );
    expect(field.controller!.selection.baseOffset, doc.text.indexOf(';'));
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    console.dispose();
    layout.dispose();
    api.close();
  });
}
