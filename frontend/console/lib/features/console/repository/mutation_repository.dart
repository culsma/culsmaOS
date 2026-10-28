import 'dart:convert';
import 'dart:io';

abstract interface class ConsoleMutationRepository {
  Future<Map<String, dynamic>?> read(String slot);
  Future<void> save(String slot, Map<String, dynamic> request);
  Future<void> clear(String slot);
}

/// Durable, credential-free request identities. A single writer serializes slots.
class FileConsoleMutationRepository implements ConsoleMutationRepository {
  final File file;
  Future<void> writes = Future.value();
  FileConsoleMutationRepository(this.file);

  Future<Map<String, dynamic>> readFile() async {
    if (!await file.exists()) return {};
    final value = jsonDecode(await file.readAsString());
    if (value is! Map<String, dynamic>) {
      throw const FormatException('CONSOLE_MUTATION_RECORD_INVALID');
    }
    for (final entry in value.entries) {
      validate(entry.key, Map<String, dynamic>.from(entry.value));
    }
    return value;
  }

  void validate(String slot, Map<String, dynamic> value) {
    if (slot.startsWith('control:')) {
      if (value.keys.any(
            (k) => !{'action', 'request_id', 'run_id'}.contains(k),
          ) ||
          !{'pause', 'resume', 'cancel'}.contains(value['action']) ||
          value['request_id'] is! String ||
          (value['request_id'] as String).isEmpty ||
          value['run_id'] is! String ||
          slot != 'control:${value['run_id']}')
        throw const FormatException('CONSOLE_MUTATION_RECORD_INVALID');
      return;
    }
    if (slot == 'supplies') {
      final keys = {
        'action',
        'request_id',
        'expected_revision',
        'resource_id',
        'positions',
        'simulation_acknowledged',
      };
      if (value.keys.any((key) => !keys.contains(key)) ||
          value['action'] != 'replace' ||
          value['request_id'] is! String ||
          value['expected_revision'] is! String ||
          value['resource_id'] is! String ||
          value['positions'] is! List ||
          (value['positions'] as List).any((p) => p is! String) ||
          value['simulation_acknowledged'] != true) {
        throw const FormatException('CONSOLE_MUTATION_RECORD_INVALID');
      }
      return;
    }
    final labware = slot == 'labware';
    final allowed = labware
        ? {
            'action',
            'request_id',
            'draft_id',
            'revision',
            'expected_fingerprint',
          }
        : {
            'action',
            'request_id',
            'run_id',
            'fingerprint',
            'preferences',
            'acknowledged',
          };
    if ((!labware && !slot.startsWith('setup:')) ||
        value.keys.any((key) => !allowed.contains(key)) ||
        value['request_id'] is! String ||
        (value['request_id'] as String).isEmpty ||
        (labware &&
            (value['action'] != 'apply' ||
                value['draft_id'] is! String ||
                value['revision'] is! int ||
                value['expected_fingerprint'] is! String)) ||
        (!labware &&
            (!{'begin', 'revise', 'confirm'}.contains(value['action']) ||
                slot != 'setup:${value['run_id']}' ||
                value['fingerprint'] is! String))) {
      throw const FormatException('CONSOLE_MUTATION_RECORD_INVALID');
    }
  }

  @override
  Future<Map<String, dynamic>?> read(String slot) async {
    await writes;
    final value = (await readFile())[slot];
    return value == null ? null : Map<String, dynamic>.from(value);
  }

  Future<void> writeSlot(String slot, Map<String, dynamic>? request) {
    final operation = writes.then((_) async {
      final values = await readFile();
      if (request != null) {
        validate(slot, request);
        if (values[slot] != null &&
            jsonEncode(values[slot]) != jsonEncode(request)) {
          throw const FormatException('CONSOLE_MUTATION_REQUIRES_REVIEW');
        }
        values[slot] = request;
      } else {
        values.remove(slot);
      }
      await file.parent.create(recursive: true);
      final temporary = File('${file.path}.new');
      await temporary.writeAsString(jsonEncode(values), flush: true);
      await temporary.rename(file.path);
    });
    writes = operation.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    return operation;
  }

  @override
  Future<void> save(String slot, Map<String, dynamic> request) =>
      writeSlot(slot, request);
  @override
  Future<void> clear(String slot) => writeSlot(slot, null);
}
