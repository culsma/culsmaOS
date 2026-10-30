import 'dart:convert';
import 'dart:io';
import 'dart:ffi';
import 'package:desktop_drop/desktop_drop.dart';
import '../model/file_drop_model.dart';

/// Reads source-provider bytes while its drop access is alive; never moves originals.
class NativeDropInteractor {
  static bool get available {
    try {
      final library = Platform.isWindows
          ? DynamicLibrary.open('desktop_drop_plugin.dll')
          : Platform.isLinux
          ? DynamicLibrary.open('libdesktop_drop_plugin.so')
          : DynamicLibrary.process();
      return library.providesSymbol('dd_rpc_open');
    } catch (_) {
      return false;
    }
  }

  Future<List<Map<String, String>>> collect(List<DropItem> items) async {
    final package = DroppedFilePackage();
    for (final item in items) {
      final bookmark = switch (item) {
        DropFileItem x => x.appleBookmark,
        DropDirectoryItem x => x.appleBookmark,
        _ => null,
      };
      bool access = false;
      try {
        if (bookmark != null)
          access = await DesktopDrop.instance
              .startAccessingSecurityScopedResource(bookmark: bookmark);
        if (item is DropFileItem)
          await collectEntity(item.file, item.name, 0, package);
        if (item is DropDirectoryItem)
          await collectEntity(item.directory, item.name, 0, package);
      } finally {
        if (access && bookmark != null)
          await DesktopDrop.instance.stopAccessingSecurityScopedResource(
            bookmark: bookmark,
          );
      }
    }
    if (package.entries.isEmpty)
      throw const FormatException('No files were supplied.');
    return package.entries;
  }

  Future<void> collectEntity(
    XEntity entity,
    String relative,
    int depth,
    DroppedFilePackage package,
  ) async {
    if (relative.split('/').any((s) => s.startsWith('.'))) return;
    if (depth > 12) {
      throw const FormatException(
        'Hidden files and folders deeper than 12 levels cannot be copied.',
      );
    }
    final uri = Uri.parse(entity.uri);
    if (uri.scheme == 'file' &&
        await FileSystemEntity.type(uri.toFilePath(), followLinks: false) ==
            FileSystemEntityType.link)
      throw const FormatException('Symbolic links cannot be copied.');
    if (entity is XDirectory) {
      await for (final child in entity.list()) {
        await collectEntity(
          child,
          '$relative/${Uri.parse(child.uri).pathSegments.where((s) => s.isNotEmpty).last}',
          depth + 1,
          package,
        );
      }
    } else if (entity is XFile) {
      if (package.entries.length >= 200)
        throw const FormatException('Copy up to 200 files at a time.');
      final chunks = <int>[];
      await for (final chunk in entity.openRead()) {
        package.bytes += chunk.length;
        if (package.bytes > 4000000)
          throw const FormatException('Copy up to 4 MB at a time.');
        chunks.addAll(chunk);
      }
      final bytes = chunks;
      package.entries.add({'path': relative, 'data': base64Encode(bytes)});
    }
  }
}
