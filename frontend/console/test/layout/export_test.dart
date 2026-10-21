import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/layout/repository/layout_archive_repository.dart';
import 'fixture.dart';

class ArchiveFixture implements LayoutArchiveRepository {
  final saved = <String>[];
  @override
  Future<String> save(String name, Uint8List content) async {
    saved.add(name);
    expect(content, [80, 75]);
    return '/temporary/layout.zip';
  }
}

class ExportApi extends FakeConsoleApi {
  String fingerprint = 'saved-fingerprint';
  bool corrupt = false;
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (body['action'] != 'export_layout') return super.command(path, body);
    calls.add({'path': path, ...body});
    return {
      'fingerprint': fingerprint,
      'layout_artifact': {
        'name': 'layout.zip',
        'encoding': 'base64',
        'media_type': 'application/zip',
        'content': base64Encode(corrupt ? [80, 76] : [80, 75]),
        'sha256': sha256.convert([80, 75]).toString(),
        'configuration_sha256': fingerprint,
      },
    };
  }
}

LayoutController controller(ExportApi api, ArchiveFixture archives) {
  final c = LayoutController(api, archives: archives);
  final existing = LayoutFixture.controller();
  c.profiles = existing.profiles;
  c.selectDraft(existing.draft!);
  c.profile = {...c.profile!, 'layout_export_supported': true};
  c.valid = true;
  return c;
}

void main() {
  test('export uses saved identity and never applies a station', () async {
    final api = ExportApi(), archives = ArchiveFixture();
    final c = controller(api, archives);
    expect(c.canExportLayout, isTrue);
    await c.exportLayout();
    expect(c.exportedLayout, '/temporary/layout.zip');
    expect(archives.saved, ['layout.zip']);
    expect(api.calls.single['action'], 'export_layout');
  });
  test('dirty layout and mismatched response cannot be exported', () async {
    final api = ExportApi(), archives = ArchiveFixture();
    final c = controller(api, archives);
    c.edit({...c.proposal!, 'edited': true});
    await c.exportLayout();
    expect(api.calls, isEmpty);
    c.discard();
    c.valid = true;
    api.fingerprint = 'wrong';
    await c.exportLayout();
    expect(archives.saved, isEmpty);
    expect(c.message, 'LAYOUT_EXPORT_IDENTITY_INVALID');
  });
  test('archive hash mismatch never writes a local file', () async {
    final api = ExportApi()..corrupt = true;
    final archives = ArchiveFixture();
    final c = controller(api, archives);
    await c.exportLayout();
    expect(archives.saved, isEmpty);
    expect(c.message, 'LAYOUT_EXPORT_HASH_INVALID');
  });
  test('archive persistence isolates exports and rejects traversal', () async {
    final directory = await Directory.systemTemp.createTemp('archive-test-');
    try {
      final repository = FileLayoutArchiveRepository(parent: directory);
      final first = await repository.save(
        'layout.zip',
        Uint8List.fromList([1, 2]),
      );
      final second = await repository.save(
        'layout.zip',
        Uint8List.fromList([3]),
      );
      expect(first, isNot(second));
      expect(await File(first).readAsBytes(), [1, 2]);
      await expectLater(
        repository.save('../escape.zip', Uint8List(0)),
        throwsFormatException,
      );
    } finally {
      await directory.delete(recursive: true);
    }
  });
}
