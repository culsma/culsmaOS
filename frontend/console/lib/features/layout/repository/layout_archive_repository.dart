import 'dart:io';
import 'dart:typed_data';

abstract interface class LayoutArchiveRepository {
  Future<String> save(String name, Uint8List content);
}

/// Each export owns a new temporary directory. Existing user files are never replaced.
class FileLayoutArchiveRepository implements LayoutArchiveRepository {
  final Directory? parent;
  FileLayoutArchiveRepository({this.parent});

  @override
  Future<String> save(String name, Uint8List content) async {
    if (!RegExp(r'^[A-Za-z0-9_-]+\.zip$').hasMatch(name)) {
      throw const FormatException('LAYOUT_EXPORT_FILENAME_INVALID');
    }
    final directory = await (parent ?? Directory.systemTemp).createTemp(
      'culsma-layout-',
    );
    final file = File('${directory.path}${Platform.pathSeparator}$name');
    await file.writeAsBytes(content, flush: true);
    return file.absolute.path;
  }
}
