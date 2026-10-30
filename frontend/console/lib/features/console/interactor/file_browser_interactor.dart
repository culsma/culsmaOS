import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';

/// Read-only navigation. Only the existing Program Interactor can start a run.
class NativeFileBrowserInteractor extends ChangeNotifier {
  final ConsoleApi api;
  NativeFileBrowserInteractor(this.api);
  List<Map<String, dynamic>> roots = [], entries = [];
  final folders = <String, List<Map<String, dynamic>>>{};
  final expanded = <String>{};
  final history = <({String root, String path})>[];
  int historyIndex = -1, navigationVersion = 0, previewVersion = 0;
  String root = 'installation', path = '';
  String? error;
  Map<String, dynamic>? selected, preview;
  bool initialized = false,
      loading = false,
      previewLoading = false,
      disposed = false;
  int total = 0;
  int? nextOffset;
  String key(String root, String path) => '$root:$path';
  bool get canBack => historyIndex > 0;
  bool get canForward => historyIndex + 1 < history.length;
  String get rootLabel =>
      roots.where((r) => r['id'] == root).firstOrNull?['label'] ?? root;
  String get absolutePath {
    final base = roots.where((r) => r['id'] == root).firstOrNull?['path'] ?? '';
    return path.isEmpty ? base : '$base/$path';
  }

  String breadcrumbLabel(int index) {
    final parts = path.split('/');
    final parent = parts.take(index).join('/');
    final target = parts.take(index + 1).join('/');
    return folders[key(root, parent)]
            ?.where((row) => row['path'] == target)
            .firstOrNull?['name'] ??
        parts[index];
  }

  bool receiving = false;
  String? notice;
  String get experimentDirectory {
    final base =
        roots.where((r) => r['id'] == 'programs').firstOrNull?['path']
            as String?;
    if (root == 'programs') return path;
    if (base != null && absolutePath.startsWith('$base/'))
      return absolutePath.substring(base.length + 1);
    return '';
  }

  Future<void> receive(
    List<Map<String, String>> entries, {
    String? directory,
  }) async {
    if (receiving) return;
    final destination = directory ?? experimentDirectory;
    receiving = true;
    error = null;
    notice = null;
    changed();
    try {
      final result = await api.command('/api/v1/files/workspace', {
        'action': 'receive',
        'path': destination,
        'entries': entries,
      });
      notice =
          '${result['count']} files copied to Experiments${destination.isEmpty ? '' : '/$destination'}. Nothing was executed.';
      await navigate('programs', destination);
    } catch (e) {
      error = e.toString().contains('FILE_ALREADY_EXISTS')
          ? 'A file already exists. Nothing was overwritten. Rename the incoming file or choose another experiment folder.'
          : 'Files could not be copied: $e';
    } finally {
      receiving = false;
      changed();
    }
  }

  void changed() {
    if (!disposed) notifyListeners();
  }

  Future<Map<String, dynamic>> read(
    String action,
    String root,
    String path, [
    int offset = 0,
  ]) => api.command('/api/v1/files', {
    'action': action,
    'root': root,
    'path': path,
    'offset': offset,
  });
  Future<void> initialize() async {
    if (initialized || loading) return;
    loading = true;
    changed();
    try {
      final result = await read('roots', 'installation', '');
      if (disposed) return;
      roots = [
        for (final row in result['roots']) Map<String, dynamic>.from(row),
      ];
      initialized = true;
      loading = false;
      await navigate(result['default_root'] ?? 'installation', '');
    } catch (e) {
      error = e.toString();
    } finally {
      loading = false;
      changed();
    }
  }

  Future<void> navigate(
    String targetRoot,
    String targetPath, {
    int? historyTarget,
  }) async {
    final version = ++navigationVersion;
    ++previewVersion;
    loading = true;
    error = null;
    selected = preview = null;
    previewLoading = false;
    changed();
    try {
      final result = await read('list', targetRoot, targetPath);
      if (disposed || version != navigationVersion) return;
      root = targetRoot;
      path = targetPath;
      entries = [
        for (final row in result['entries']) Map<String, dynamic>.from(row),
      ];
      total = result['total'];
      nextOffset = result['next_offset'];
      folders[key(root, path)] = entries
          .where((r) => r['kind'] == 'directory')
          .toList();
      expanded.add(key(root, ''));
      var parent = path;
      while (parent.contains('/')) {
        parent = parent.substring(0, parent.lastIndexOf('/'));
        expanded.add(key(root, parent));
      }
      if (historyTarget != null)
        historyIndex = historyTarget;
      else if (historyIndex < 0 ||
          history[historyIndex] != (root: root, path: path)) {
        history.removeRange(historyIndex + 1, history.length);
        history.add((root: root, path: path));
        historyIndex = history.length - 1;
      }
    } catch (e) {
      if (version == navigationVersion) error = e.toString();
    } finally {
      if (version == navigationVersion) {
        loading = false;
        changed();
      }
    }
  }

  Future<void> refresh() => initialized
      ? navigate(root, path, historyTarget: historyIndex)
      : initialize();
  Future<void> back() async {
    if (canBack) {
      final i = historyIndex - 1, location = history[i];
      await navigate(location.root, location.path, historyTarget: i);
    }
  }

  Future<void> forward() async {
    if (canForward) {
      final i = historyIndex + 1, location = history[i];
      await navigate(location.root, location.path, historyTarget: i);
    }
  }

  Future<void> up() async {
    if (path.isNotEmpty)
      await navigate(
        root,
        path.contains('/') ? path.substring(0, path.lastIndexOf('/')) : '',
      );
  }

  Future<void> more() async {
    if (loading || nextOffset == null) return;
    final version = navigationVersion;
    loading = true;
    error = null;
    changed();
    try {
      final result = await read('list', root, path, nextOffset!);
      if (disposed || version != navigationVersion) return;
      entries = [
        ...entries,
        for (final row in result['entries']) Map<String, dynamic>.from(row),
      ];
      total = result['total'];
      nextOffset = result['next_offset'];
      folders[key(root, path)] = entries
          .where((r) => r['kind'] == 'directory')
          .toList();
    } catch (e) {
      if (version == navigationVersion) error = e.toString();
    } finally {
      if (version == navigationVersion) {
        loading = false;
        changed();
      }
    }
  }

  Future<void> toggleFolder(String selectedRoot, String selectedPath) async {
    final id = key(selectedRoot, selectedPath);
    if (expanded.remove(id)) {
      changed();
      return;
    }
    try {
      final result = await read('list', selectedRoot, selectedPath);
      if (disposed) return;
      folders[id] = [
        for (final row in result['entries'])
          if (row['kind'] == 'directory') Map<String, dynamic>.from(row),
      ];
      expanded.add(id);
      error = null;
    } catch (e) {
      error = e.toString();
    }
    changed();
  }

  Future<void> select(Map<String, dynamic> entry) async {
    final version = ++previewVersion;
    selected = entry;
    preview = null;
    error = null;
    previewLoading = entry['kind'] == 'file';
    changed();
    if (!previewLoading) return;
    try {
      final result = await read('preview', root, entry['path']);
      if (!disposed && version == previewVersion) preview = result;
    } catch (e) {
      if (version == previewVersion) error = e.toString();
    } finally {
      if (version == previewVersion) {
        previewLoading = false;
        changed();
      }
    }
  }

  @override
  void dispose() {
    disposed = true;
    ++navigationVersion;
    ++previewVersion;
    super.dispose();
  }
}
