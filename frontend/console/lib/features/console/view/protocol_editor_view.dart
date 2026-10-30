import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:syntax_highlight/syntax_highlight.dart';
import 'protocol_name_dialog.dart';
import '../interactor/console_interactor.dart';
import '../interactor/editor_interactor.dart';
import '../model/protocol_document.dart';

class CulsmaEditingController extends TextEditingController {
  Highlighter? highlighter;
  void setHighlighter(Highlighter value) {
    highlighter = value;
    notifyListeners();
  }

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    if (highlighter == null ||
        (withComposing &&
            value.composing.isValid &&
            !value.composing.isCollapsed)) {
      return super.buildTextSpan(
        context: context,
        style: style,
        withComposing: withComposing,
      );
    }
    return TextSpan(style: style, children: [highlighter!.highlight(text)]);
  }
}

class NativeProtocolEditorView extends StatefulWidget {
  final NativeConsoleInteractor console;
  final String path;
  const NativeProtocolEditorView({
    super.key,
    required this.console,
    required this.path,
  });
  @override
  State<NativeProtocolEditorView> createState() =>
      _NativeProtocolEditorViewState();
}

class _NativeProtocolEditorViewState extends State<NativeProtocolEditorView> {
  final text = CulsmaEditingController();
  Timer? refresh;
  bool synchronizing = false;
  final editorFocus = FocusNode();
  NativeEditorInteractor get editor => widget.console.editor;
  ProtocolDocument get doc => editor.document(widget.path);
  @override
  void initState() {
    super.initState();
    editor.addListener(update);
    text.text = doc.text;
    text.addListener(textChanged);
    initialize();
    refresh = Timer.periodic(const Duration(seconds: 3), (_) {
      if (!doc.busy) editor.refresh(widget.path);
    });
  }

  Future<void> initialize() async {
    try {
      Highlighter.addLanguage(
        'culsma',
        await rootBundle.loadString('assets/syntax/culsma.tmLanguage.json'),
      );
      final theme = await HighlighterTheme.loadLightTheme();
      if (!mounted) return;
      text.setHighlighter(Highlighter(language: 'culsma', theme: theme));
      if (!doc.loaded) await editor.load(widget.path);
    } catch (e) {
      if (mounted) {
        doc.error = 'Unable to open the editor: $e';
        update();
      }
    }
  }

  void textChanged() {
    if (!synchronizing && doc.loaded && doc.text != text.text)
      editor.edit(widget.path, text.text);
  }

  void update() {
    if (!mounted) return;
    if (text.text != doc.text) {
      final offset = text.selection.baseOffset.clamp(0, doc.text.length);
      synchronizing = true;
      text.value = TextEditingValue(
        text: doc.text,
        selection: TextSelection.collapsed(offset: offset),
      );
      synchronizing = false;
    }
    setState(() {});
  }

  Future<void> saveAs() async {
    final path = await promptProtocolName(
      context,
      'Save As',
      widget.path.replaceFirst(RegExp(r'\.culs$'), '-copy.culs'),
    );
    if (path != null) {
      if (await editor.create(path, doc.text)) {
        if (mounted) widget.console.openEditor(path);
      } else {
        doc.error = editor.document(path).error;
        editor.changed();
      }
    }
  }

  Future<void> reload() async {
    if (doc.dirty) {
      final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Discard unsaved edits?'),
          content: const Text(
            'Reload the latest saved file. Your unsaved edits will be discarded.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Keep editing'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Discard and reload'),
            ),
          ],
        ),
      );
      if (yes != true) return;
    }
    await editor.load(widget.path, discard: true);
  }

  void revealDiagnostic(Map diagnostic) {
    final span = diagnostic['span'];
    if (span is! Map) return;
    final line = span['line'];
    final col = span['col'];
    if (line is! int || col is! int) return;
    final lines = text.text.split('\n');
    if (line < 1 || line > lines.length) return;
    final offset =
        lines.take(line - 1).fold<int>(0, (sum, s) => sum + s.length + 1) +
        (col - 1).clamp(0, lines[line - 1].length);
    text.selection = TextSelection.collapsed(offset: offset);
    editorFocus.requestFocus();
  }

  String diagnosticText(Map diagnostic) {
    final span = diagnostic['span'];
    final position = span is Map && span['line'] != null
        ? 'Line ${span['line']}, column ${span['col'] ?? 1}: '
        : '';
    return '$position${diagnostic['message'] ?? diagnostic['code'] ?? 'Program check failed'}';
  }

  Future<void> run() async {
    if (doc.dirty && !await editor.save(widget.path)) return;
    if (doc.dirty) return;
    await widget.console.launch(widget.path, sourceScope: 'programs');
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Padding(
        padding: const EdgeInsets.all(12),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text('${widget.path}${doc.dirty ? ' • Unsaved' : ''}'),
            FilledButton.icon(
              key: const Key('editor-save'),
              onPressed: doc.busy || !doc.loaded
                  ? null
                  : () => editor.save(widget.path),
              icon: const Icon(Icons.save_outlined),
              label: const Text('Save'),
            ),
            OutlinedButton(
              onPressed: doc.busy || !doc.loaded ? null : saveAs,
              child: const Text('Save As'),
            ),
            OutlinedButton(
              key: const Key('editor-check'),
              onPressed: doc.busy || !doc.loaded
                  ? null
                  : () => editor.check(widget.path),
              child: const Text('Check'),
            ),
            OutlinedButton(
              onPressed: doc.busy ? null : reload,
              child: const Text('Reload'),
            ),
            FilledButton.icon(
              key: const Key('editor-run'),
              onPressed: doc.busy || !doc.loaded ? null : run,
              icon: const Icon(Icons.play_arrow),
              label: const Text('Run'),
            ),
          ],
        ),
      ),
      if (doc.busy && !doc.loaded) const LinearProgressIndicator(),
      if (doc.externalChange)
        const Padding(
          padding: EdgeInsets.all(12),
          child: Text(
            'The saved file changed while you were editing. Your edits are retained; use Save As or reload.',
          ),
        ),
      if (doc.error != null)
        Padding(
          padding: const EdgeInsets.all(12),
          child: SelectableText(
            doc.error!,
            style: const TextStyle(color: Colors.brown),
          ),
        ),
      Expanded(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              width: 52,
              color: const Color(0xffedf2f7),
              child: SingleChildScrollView(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    List.generate(
                      text.text.split('\n').length,
                      (i) => '${i + 1}',
                    ).join('\n'),
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontFamily: 'Code',
                      fontSize: 14,
                      height: 1.5,
                    ),
                  ),
                ),
              ),
            ),
            Expanded(
              child: TextField(
                key: const Key('protocol-editor'),
                controller: text,
                focusNode: editorFocus,
                readOnly: !doc.loaded,
                keyboardType: TextInputType.multiline,
                maxLines: null,
                minLines: null,
                expands: true,
                autocorrect: false,
                enableSuggestions: false,
                style: const TextStyle(
                  fontFamily: 'Code',
                  fontSize: 14,
                  height: 1.5,
                ),
                decoration: const InputDecoration(
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.all(16),
                ),
              ),
            ),
          ],
        ),
      ),
      if (doc.inspection != null)
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 150),
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    doc.inspection!['valid'] == true
                        ? 'Checks passed'
                        : 'Check the errors below',
                  ),
                  for (final diagnostic
                      in doc.inspection!['diagnostics'] as List? ?? [])
                    TextButton(
                      onPressed: () => revealDiagnostic(diagnostic as Map),
                      child: Text(diagnosticText(diagnostic)),
                    ),
                ],
              ),
            ),
          ),
        ),
    ],
  );
  @override
  void dispose() {
    refresh?.cancel();
    editor.removeListener(update);
    editorFocus.dispose();
    text.removeListener(textChanged);
    text.dispose();
    super.dispose();
  }
}
