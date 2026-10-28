import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../repository/mutation_repository.dart';

/// Presents shared loading plans. Only explicit operator input confirms loading.
class NativeSetupInteractor extends ChangeNotifier {
  final ConsoleApi api;
  final ConsoleMutationRepository? repository;
  final plans = <String, Map<String, dynamic>>{},
      pending = <String, Map<String, dynamic>>{};
  final edits = <String, Map<String, dynamic>>{};
  final acknowledgements = <String, String>{}, errors = <String, String>{};
  final statuses = <String, String>{};
  final blocked = <String>{};
  bool busy = false, disposed = false;
  NativeSetupInteractor(this.api, this.repository);
  bool get dirty =>
      edits.values.any((e) => e['dirty'] == true) ||
      acknowledgements.isNotEmpty;
  void emit() {
    if (!disposed) notifyListeners();
  }

  Map<String, dynamic> copy(Map value) =>
      Map<String, dynamic>.from(jsonDecode(jsonEncode(value)));
  String requestId() => List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<void> observe(Map<String, dynamic> run) async {
    if (busy ||
        (run['status'] != 'awaiting_setup' &&
            run['result']?['os']?['setup'] == null))
      return;
    final id = run['run_id'] as String;
    busy = true;
    try {
      if (!pending.containsKey(id)) {
        final retained = await repository?.read('setup:$id');
        if (retained != null) pending[id] = retained;
      }
      final plan = await api.command('/api/v1/setup', {
        'action': 'show',
        'run_id': id,
      });
      acceptPlan(id, plan);
      if (pending[id] != null) await readStatus(id);
    } catch (e) {
      errors[id] = e.toString();
    } finally {
      busy = false;
      emit();
    }
  }

  void acceptPlan(String id, Map<String, dynamic> plan) {
    if (plans[id]?['fingerprint'] != plan['fingerprint'])
      acknowledgements.remove(id);
    plans[id] = plan;
    if (plan['phase'] != 'loading') acknowledgements.remove(id);
  }

  bool acknowledged(String id) =>
      plans[id]?['fingerprint'] != null &&
      acknowledgements[id] == plans[id]?['fingerprint'];
  void acknowledge(String id, bool value) {
    if (busy || pending[id] != null || plans[id]?['phase'] != 'loading') return;
    if (value)
      acknowledgements[id] = plans[id]!['fingerprint'];
    else
      acknowledgements.remove(id);
    emit();
  }

  Map<String, dynamic> edit(String id) => edits.putIfAbsent(
    id,
    () => {
      'fingerprint': plans[id]!['fingerprint'],
      'values': copy(plans[id]!['preferences'] ?? {}),
      'dirty': false,
    },
  );
  void reloadPreferences(String id) {
    if (!busy && pending[id] == null) {
      edits.remove(id);
      emit();
    }
  }

  void setPreference(String id, String allocation, String mode, Map address) {
    if (busy || pending[id] != null) return;
    final current = edit(id);
    if (current['fingerprint'] != plans[id]?['fingerprint']) return;
    final values = current['values'];
    for (final key in ['fixed', 'preferred']) {
      (values[key] as Map?)?.remove(allocation);
    }
    if (mode != 'automatic')
      (values[mode] ??= <String, dynamic>{})[allocation] = copy(address);
    current['dirty'] = true;
    emit();
  }

  Future<void> command(String id, String action) async {
    final plan = plans[id];
    if (busy ||
        plan == null ||
        pending[id] != null ||
        repository == null ||
        blocked.contains(id))
      return;
    if (action != 'revise' && edits[id]?['dirty'] == true) return;
    if (action == 'begin' && plan['phase'] != 'planned' ||
        action == 'confirm' &&
            (plan['phase'] != 'loading' || !acknowledged(id)) ||
        action == 'revise' &&
            (edits[id]?['fingerprint'] != plan['fingerprint'] ||
                edits[id]?['dirty'] != true))
      return;
    final payload = <String, dynamic>{
      'action': action,
      'run_id': id,
      'request_id': requestId(),
      'fingerprint': plan['fingerprint'],
      if (action == 'revise') 'preferences': copy(edits[id]!['values']),
      if (action == 'confirm') 'acknowledged': true,
    };
    busy = true;
    errors.remove(id);
    emit();
    try {
      await repository!.save('setup:$id', payload);
      pending[id] = payload;
      await send(id);
    } catch (e) {
      errors[id] = 'Request retained if saved: $e. No automatic retry.';
    } finally {
      busy = false;
      emit();
    }
  }

  Future<void> send(String id) async {
    final payload = pending[id]!;
    try {
      await api.command(
        payload['action'] == 'confirm'
            ? '/api/v1/setup/confirmation'
            : '/api/v1/setup',
        payload,
      );
      statuses[id] = 'Request accepted. Waiting for OS application.';
    } on ConsoleApiError catch (e) {
      if (e.status != null && e.status! < 500) {
        await repository!.clear('setup:$id');
        pending.remove(id);
      }
      rethrow;
    }
  }

  Future<void> retry(String id) async {
    if (busy || pending[id] == null || blocked.contains(id)) return;
    busy = true;
    emit();
    try {
      await send(id);
    } catch (e) {
      errors[id] = '$e. The same request identity is retained if unresolved.';
    } finally {
      busy = false;
      emit();
    }
  }

  Future<void> check(String id) async {
    if (busy || pending[id] == null) return;
    busy = true;
    emit();
    try {
      await readStatus(id);
    } catch (e) {
      errors[id] = 'Request status unavailable: $e';
    } finally {
      busy = false;
      emit();
    }
  }

  Future<void> readStatus(String id) async {
    final payload = pending[id]!;
    final receipt = await api.command('/api/v1/setup', {
      'action': 'status',
      'run_id': id,
      'request_id': payload['request_id'],
    });
    if (receipt['request_id'] != payload['request_id']) return;
    if (['completed', 'failed'].contains(receipt['status'])) {
      await repository!.clear('setup:$id');
      pending.remove(id);
      statuses[id] = '${payload['action']}: ${receipt['status']}';
      if (receipt['status'] == 'completed') {
        errors.remove(id);
        edits.remove(id);
        acknowledgements.remove(id);
      } else {
        errors[id] = receipt['error']?.toString() ?? 'Loading request failed.';
      }
    }
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}
