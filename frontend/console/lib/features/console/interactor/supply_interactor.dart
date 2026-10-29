import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../repository/mutation_repository.dart';

class NativeSupplyInteractor extends ChangeNotifier {
  final ConsoleApi api;
  final ConsoleMutationRepository? repository;
  Map<String, dynamic>? data, pending;
  String? error, message, editingRevision;
  final selected = <String>{};
  Completer<void>? refreshCompletion;
  bool get refreshing => refreshCompletion != null;
  bool busy = false,
      editing = false,
      acknowledged = false,
      blocked = false,
      disposed = false;
  NativeSupplyInteractor(this.api, this.repository);
  void emit() {
    if (!disposed) notifyListeners();
  }

  bool get supported => data?['supported'] == true;
  List<String> get positions =>
      List<String>.from(data?['position_choices'] ?? []);
  bool get stale => editingRevision != data?['revision'];
  bool get canApply =>
      supported &&
      !busy &&
      !blocked &&
      pending == null &&
      repository != null &&
      acknowledged &&
      selected.isNotEmpty &&
      !stale &&
      data?['stock']?['ready'] == true &&
      (data?['pending'] as List? ?? []).isEmpty;
  String requestId() => List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<void> restore() async {
    try {
      pending = await repository?.read('supplies');
    } catch (_) {
      blocked = true;
      error =
          'Saved replacement request cannot be read. Replacement is disabled.';
    }
  }

  Future<void> refresh() async {
    if (busy) return;
    if (refreshCompletion != null) return refreshCompletion!.future;
    final completion = Completer<void>();
    refreshCompletion = completion;
    try {
      data = await api.command('/api/v1/consumables', {'action': 'show'});
      if (pending != null) await readStatus(pending!['request_id']);
    } catch (e) {
      error = 'Tip supply status unavailable: $e';
    } finally {
      refreshCompletion = null;
      completion.complete();
      emit();
    }
  }

  void open() {
    if (busy) return;
    editing = true;
    acknowledged = false;
    editingRevision = data?['revision'];
    selected
      ..clear()
      ..addAll(positions);
    emit();
  }

  void close() {
    if (!busy) {
      editing = false;
      acknowledged = false;
      emit();
    }
  }

  void choose(String position, bool value) {
    if (busy || pending != null || !positions.contains(position)) return;
    if (value)
      selected.add(position);
    else
      selected.remove(position);
    acknowledged = false;
    emit();
  }

  void acknowledge(bool value) {
    if (!busy && pending == null) {
      acknowledged = value;
      emit();
    }
  }

  Future<void> apply() async {
    if (refreshCompletion != null) await refreshCompletion!.future;
    if (!canApply) return;
    busy = true;
    error = null;
    emit();
    final payload = <String, dynamic>{
      'action': 'replace',
      'request_id': requestId(),
      'expected_revision': editingRevision,
      'resource_id': data!['resource_id'],
      'positions': positions.where(selected.contains).toList(),
      'simulation_acknowledged': true,
    };
    try {
      await repository!.save('supplies', payload);
      pending = payload;
      final receipt = await api.command('/api/v1/consumables', payload);
      await accept(receipt);
    } on ConsoleApiError catch (e) {
      if (e.status != null && e.status! < 500) {
        await repository!.clear('supplies');
        pending = null;
      }
      error = e.responseUnknown
          ? 'Replacement response unknown. Check the retained request; it will not be sent again.'
          : e.code;
    } catch (e) {
      error = e.toString();
    } finally {
      busy = false;
      emit();
    }
    await refresh();
  }

  Future<void> accept(Map<String, dynamic> receipt) async {
    if (pending == null || receipt['request_id'] != pending!['request_id'])
      return;
    if (receipt['status'] == 'applied') {
      final view = await api.command('/api/v1/consumables', {'action': 'show'});
      if (view['current_load']?['request_id'] != pending!['request_id']) return;
      data = view;
      await repository!.clear('supplies');
      pending = null;
      editing = false;
      acknowledged = false;
      error = null;
      message =
          'New simulated tip box registered. Previous consumption history is retained.';
    } else if (receipt['status'] == 'rejected') {
      error =
          receipt['receipt']?['error'] ??
          'Replacement was not applied. Review the station and start a new request.';
      await repository!.clear('supplies');
      pending = null;
      acknowledged = false;
    }
  }

  Future<void> readStatus(String id) async {
    final receipt = await api.command('/api/v1/consumables', {
      'action': 'status',
      'request_id': id,
    });
    await accept(receipt);
  }

  Future<void> check([String? id]) async {
    if (refreshCompletion != null) await refreshCompletion!.future;
    if (busy) return;
    final request = id ?? pending?['request_id'];
    if (request == null) return;
    busy = true;
    emit();
    try {
      await readStatus(request);
      data = await api.command('/api/v1/consumables', {'action': 'show'});
    } catch (e) {
      error = 'Replacement status unavailable: $e';
    } finally {
      busy = false;
      emit();
    }
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}
