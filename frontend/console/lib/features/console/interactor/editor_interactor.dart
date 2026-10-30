import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../model/protocol_document.dart';

/// Editable source only. Existing Program use cases own checks and execution snapshots.
class NativeEditorInteractor extends ChangeNotifier {
  final ConsoleApi api;
  final documents = <String, ProtocolDocument>{};
  bool disposed = false;
  NativeEditorInteractor(this.api);
  ProtocolDocument document(String path) =>
      documents.putIfAbsent(path, () => ProtocolDocument(path));
  bool get dirty => documents.values.any((d) => d.dirty);
  void changed() {
    if (!disposed) notifyListeners();
  }

  String explain(Object error) {
    final text = error.toString();
    if (text.contains('FILE_REVISION_CONFLICT'))
      return 'This file changed outside this editor. Your edits are retained. Save As a new file, or reload the saved version.';
    if (text.contains('FILE_ALREADY_EXISTS'))
      return 'A file already exists at that location. Choose another name.';
    if (text.contains('FILE_WORKSPACE_BUSY'))
      return 'Another file operation is finishing. Please try again.';
    return 'The file operation failed. Your edits are retained. Details: $text';
  }

  Future<Map<String, dynamic>> request(Map<String, dynamic> value) =>
      api.command('/api/v1/files/workspace', value);
  Future<void> load(String path, {bool discard = false}) async {
    final d = document(path);
    if (d.busy) return;
    d.busy = true;
    d.error = null;
    changed();
    try {
      final value = await request({'action': 'read', 'path': path});
      if (disposed) return;
      if (d.loaded && d.dirty && !discard) {
        d.externalChange = value['revision'] != d.revision;
        return;
      }
      d.text = d.savedText = value['content'];
      d.revision = value['revision'];
      d.loaded = true;
      d.externalChange = false;
      d.inspection = null;
    } catch (e) {
      d.error = explain(e);
    } finally {
      d.busy = false;
      changed();
    }
  }

  Future<void> refresh(String path) async {
    final d = document(path);
    if (d.busy || !d.loaded) return;
    final revision = d.revision;
    try {
      final value = await request({'action': 'read', 'path': path});
      if (disposed || d.busy || d.revision != revision) return;
      if (value['revision'] == revision) return;
      if (d.dirty) {
        if (!d.externalChange) {
          d.externalChange = true;
          changed();
        }
        return;
      }
      d.text = d.savedText = value['content'];
      d.revision = value['revision'];
      d.inspection = null;
      d.externalChange = false;
      changed();
    } catch (_) {
      /* Explicit load/save reports failures; background observation never changes the buffer. */
    }
  }

  void edit(String path, String text) {
    final d = document(path);
    d.text = text;
    d.inspection = null;
    changed();
  }

  Future<bool> save(String path) async {
    final d = document(path);
    if (d.busy || !d.loaded) return false;
    d.busy = true;
    d.error = null;
    changed();
    final content = d.text;
    try {
      final result = await request({
        'action': 'save',
        'path': path,
        'content': content,
        'expected_revision': d.revision,
      });
      d.savedText = content;
      d.revision = result['revision'];
      d.externalChange = false;
      return true;
    } catch (e) {
      d.error = explain(e);
      return false;
    } finally {
      d.busy = false;
      changed();
    }
  }

  Future<bool> create(String path, String content) async {
    try {
      await request({'action': 'create', 'path': path, 'content': content});
      await load(path);
      return document(path).loaded;
    } catch (e) {
      final d = document(path);
      d.error = explain(e);
      changed();
      return false;
    }
  }

  Future<void> check(String path) async {
    final d = document(path);
    if (d.busy || !d.loaded) return;
    if (d.dirty && !await save(path)) return;
    // Typing during the save leaves a newer unsaved buffer; it has not been checked.
    if (d.dirty) return;
    d.busy = true;
    d.error = null;
    changed();
    try {
      final content = d.text, revision = d.revision;
      final result = await api.command('/api/v1/programs', {
        'action': 'inspect',
        'program_id': path,
        'source_scope': 'programs',
      });
      if (!disposed && d.text == content && d.revision == revision) {
        d.inspection = result;
      }
    } catch (e) {
      d.error = explain(e);
    } finally {
      d.busy = false;
      changed();
    }
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}
