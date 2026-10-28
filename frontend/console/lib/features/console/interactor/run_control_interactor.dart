import 'dart:math';
import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../repository/mutation_repository.dart';

/// Presents existing Program Manager controls; no worker or execution policy lives here.
class NativeRunControlInteractor extends ChangeNotifier {
  final ConsoleApi api;
  final ConsoleMutationRepository? repository;
  final pending = <String, Map<String, dynamic>>{};
  final receipts = <String, Map<String, dynamic>>{};
  final errors = <String, String>{};
  final restored = <String>{}, busy = <String>{}, blocked = <String>{};
  bool disposed = false;
  NativeRunControlInteractor(this.api, this.repository);
  void emit() {
    if (!disposed) notifyListeners();
  }

  String requestId() => List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();
  List<String> actions(Map<String, dynamic> run) {
    final id = run['run_id'];
    if (repository == null ||
        pending.containsKey(id) ||
        busy.contains(id) ||
        blocked.contains(id))
      return [];
    return switch (run['status']) {
      'awaiting_setup' => ['cancel'],
      'paused' => ['resume', 'cancel'],
      'ready' || 'running' || 'waiting' || 'finalizing' => ['pause', 'cancel'],
      _ => [],
    };
  }

  Future<void> restore(String id) async {
    if (restored.contains(id)) return;
    restored.add(id);
    try {
      final value = await repository?.read('control:$id');
      if (value != null) pending[id] = value;
    } catch (_) {
      blocked.add(id);
      errors[id] =
          'Saved control request cannot be read. Controls are disabled for this experiment.';
    }
  }

  Future<void> observe(Map<String, dynamic> run) async {
    final id = run['run_id'] as String;
    if (busy.contains(id)) return;
    busy.add(id);
    try {
      await restore(id);
      if (pending.containsKey(id)) await readStatus(id);
    } finally {
      busy.remove(id);
      emit();
    }
  }

  Future<void> command(Map<String, dynamic> run, String action) async {
    final id = run['run_id'] as String;
    if (!actions(run).contains(action)) return;
    busy.add(id);
    errors.remove(id);
    emit();
    final payload = <String, dynamic>{
      'action': action,
      'run_id': id,
      'request_id': requestId(),
    };
    try {
      await repository!.save('control:$id', payload);
      pending[id] = payload;
      await send(id);
    } catch (e) {
      errors[id] = e.toString();
    } finally {
      busy.remove(id);
      emit();
    }
  }

  Future<void> send(String id) async {
    try {
      final result = await api.command('/api/v1/programs', pending[id]!);
      await accept(id, result['acknowledgement']);
    } on ConsoleApiError catch (e) {
      if (e.status != null && e.status! < 500) {
        await repository!.clear('control:$id');
        pending.remove(id);
      }
      errors[id] = e.responseUnknown
          ? 'Control response unknown. The original request is retained; it is not sent automatically.'
          : e.code;
    }
  }

  Future<void> accept(String id, dynamic receipt) async {
    final request = pending[id];
    if (request == null ||
        receipt is! Map ||
        receipt['request_id'] != request['request_id'] ||
        receipt['run_id'] != id ||
        receipt['action'] != request['action'] ||
        !{'pending', 'applied', 'rejected'}.contains(receipt['status'])) {
      errors[id] = 'Control receipt does not match the retained request.';
      return;
    }
    receipts[id] = Map<String, dynamic>.from(receipt);
    errors.remove(id);
    if ({'applied', 'rejected'}.contains(receipt['status'])) {
      await repository!.clear('control:$id');
      pending.remove(id);
    }
  }

  Future<void> readStatus(String id) async {
    try {
      final value = await api.command('/api/v1/programs', {
        'action': 'control-status',
        'run_id': id,
        'request_id': pending[id]!['request_id'],
      });
      await accept(id, value['acknowledgement']);
    } catch (e) {
      errors[id] =
          'Control receipt unavailable: $e. The original request remains retained.';
    }
  }

  Future<void> check(String id) async {
    if (busy.contains(id) || pending[id] == null) return;
    busy.add(id);
    emit();
    try {
      await readStatus(id);
    } finally {
      busy.remove(id);
      emit();
    }
  }

  Future<void> retry(String id) async {
    if (busy.contains(id) || blocked.contains(id) || pending[id] == null)
      return;
    busy.add(id);
    emit();
    try {
      await send(id);
    } catch (e) {
      errors[id] = e.toString();
    } finally {
      busy.remove(id);
      emit();
    }
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}
