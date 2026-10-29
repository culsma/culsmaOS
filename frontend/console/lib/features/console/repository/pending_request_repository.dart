import 'dart:convert';
import 'dart:io';

abstract interface class PendingRequestRepository {
  Future<Map<String, dynamic>?> read();
  Future<void> save(Map<String, dynamic> request);
  Future<void> clear();
}

/// Stores one unresolved request identity, never a credential or source contents.
class FilePendingRequestRepository implements PendingRequestRepository {
  final File file;
  FilePendingRequestRepository(this.file);
  @override
  Future<Map<String, dynamic>?> read() async {
    if (!await file.exists()) return null;
    final value = jsonDecode(await file.readAsString());
    if (value is! Map<String, dynamic> ||
        value['action'] != 'start' ||
        (value.containsKey('source_scope') &&
            !{'installation', 'programs'}.contains(value['source_scope'])) ||
        ![
          'request_id',
          'program_id',
          'snapshot_id',
        ].every((key) => value[key] is String)) {
      throw const FormatException('PENDING_RUN_REQUEST_INVALID');
    }
    return value;
  }

  @override
  Future<void> save(Map<String, dynamic> request) async {
    await file.parent.create(recursive: true);
    final retained = await read();
    if (retained != null && jsonEncode(retained) != jsonEncode(request)) {
      throw const FormatException('PENDING_RUN_REQUEST_REQUIRES_REVIEW');
    }
    final temporary = File('${file.path}.new');
    await temporary.writeAsString(jsonEncode(request), flush: true);
    await temporary.rename(file.path);
  }

  @override
  Future<void> clear() async {
    if (await file.exists()) await file.delete();
  }
}
