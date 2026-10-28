import 'dart:math';
import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../repository/mutation_repository.dart';

/// Native presentation of the existing driver catalogue and OS activation receipts.
class NativeLabwareInteractor extends ChangeNotifier {
  final ConsoleApi api;
  final ConsoleMutationRepository? repository;
  Map<String, dynamic>? envelope,
      catalogue,
      target,
      selection,
      pending,
      proposal;
  String? fingerprint, error, message;
  String category = '', model = '', name = '';
  bool editing = false, busy = false, blocked = false, disposed = false;
  int version = 0;
  NativeLabwareInteractor(this.api, this.repository);
  bool get editingCarrier => selection?['carrier'] != null;
  bool get ready => envelope?['editing_ready'] == true;
  bool get stale => fingerprint != envelope?['configuration_fingerprint'];
  List<Map<String, dynamic>> get models => List<Map<String, dynamic>>.from(
    (catalogue?['models'] as List? ?? []).where(
      (m) => (target?['models'] as List? ?? []).contains(m['id']),
    ),
  );
  bool get changed => category == 'empty'
      ? (target?['occupants'] as List? ?? []).isNotEmpty
      : model.isNotEmpty &&
            (model != selection?['model'] ||
                (target?['occupants'] as List? ?? []).isEmpty);
  bool get canSave =>
      !busy &&
      !blocked &&
      pending == null &&
      repository != null &&
      ready &&
      !stale &&
      target != null &&
      target!['reason'] == null &&
      changed &&
      (!editingCarrier || category == 'carrier') &&
      (category == 'empty' || models.any((m) => m['id'] == model));
  void emit() {
    if (!disposed) notifyListeners();
  }

  Future<void> restore() async {
    try {
      pending = await repository?.read('labware');
    } catch (_) {
      blocked = true;
      error = 'Saved layout request cannot be read. Saving is disabled.';
    }
  }

  Future<void> observe(Map<String, dynamic>? value) async {
    envelope = value;
    if (pending != null && !busy) await checkStatus();
    emit();
  }

  Future<void> edit(
    Map<String, dynamic> desired, {
    bool settingsBlocked = false,
  }) async {
    if (busy) return;
    editing = true;
    error = null;
    if (pending != null || blocked) {
      emit();
      return;
    }
    selection = Map.of(desired);
    target = null;
    catalogue = null;
    fingerprint = envelope?['configuration_fingerprint'];
    if (!ready || settingsBlocked) {
      error =
          'Finish current work and leave the station ready before editing this position.';
      emit();
      return;
    }
    final requestVersion = ++version;
    busy = true;
    emit();
    try {
      final result = await api.command('/api/v1/configuration/labware', {
        'action': 'catalogue',
        'expected_fingerprint': fingerprint,
      });
      if (requestVersion != version || stale) {
        error = 'The layout changed. Close and reopen this position.';
        return;
      }
      if (result['configuration_fingerprint'] != fingerprint) {
        throw const FormatException('LABWARE_CATALOGUE_IDENTITY_MISMATCH');
      }
      catalogue = Map<String, dynamic>.from(result['catalogue']);
      target = List<Map<String, dynamic>>.from(catalogue!['targets'])
          .where(
            (t) => (desired['carrier'] != null
                ? t['kind'] == 'carrier' &&
                      (t['occupants'] as List).contains(desired['carrier'])
                : t['kind'] != 'carrier' &&
                      (desired['item'] != null
                          ? (t['occupants'] as List).contains(desired['item'])
                          : t['parent'] == desired['parent'] &&
                                t['site'] == desired['site'])),
          )
          .firstOrNull;
      if (target == null) {
        error = 'This position is read-only in the installed driver.';
        return;
      }
      final current = models
          .where((m) => m['id'] == desired['model'])
          .firstOrNull;
      model = current?['id'] ?? '';
      category = editingCarrier
          ? 'carrier'
          : (target!['occupants'] as List).isEmpty
          ? 'empty'
          : current?['category'] ?? '';
      name = target!['suggested_name'] ?? '';
    } catch (e) {
      error = e.toString();
    } finally {
      busy = false;
      emit();
    }
  }

  void chooseCategory(String value) {
    if (busy || pending != null) return;
    category = value;
    final choices = models.where((m) => m['category'] == value).toList();
    model = choices.length == 1 ? choices.single['id'] : '';
    emit();
  }

  void chooseModel(String value) {
    if (!busy && pending == null) {
      model = value;
      emit();
    }
  }

  void close() {
    if (!busy) {
      editing = false;
      version++;
      emit();
    }
  }

  String requestId() => List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<void> save() async {
    if (!canSave) return;
    busy = true;
    error = null;
    message = null;
    emit();
    try {
      final action = editingCarrier
          ? 'replace-carrier'
          : category == 'empty'
          ? 'remove'
          : (target!['occupants'] as List).isEmpty
          ? 'place'
          : 'replace';
      final change = {
        'action': action,
        'target': target!['id'],
        if (action != 'remove') 'model': model,
        if (action == 'place') 'name': name,
      };
      proposal = await api.command('/api/v1/configuration/labware', {
        'action': 'prepare',
        'expected_fingerprint': fingerprint,
        'change': change,
      });
      if (stale || proposal!['expected_fingerprint'] != fingerprint) {
        throw const FormatException(
          'Layout changed. Reopen this position before saving.',
        );
      }
      final payload = <String, dynamic>{
        'action': 'apply',
        'draft_id': proposal!['draft']['draft_id'],
        'revision': proposal!['draft']['revision'],
        'expected_fingerprint': fingerprint,
        'request_id': requestId(),
      };
      await repository!.save('labware', payload);
      pending = payload;
      await api.command('/api/v1/configuration/activation', payload);
    } on ConsoleApiError catch (e) {
      if (pending != null && e.status != null && e.status! < 500) {
        await repository!.clear('labware');
        pending = null;
      }
      error = e.responseUnknown
          ? 'Save response unknown. The request is retained; it will not be sent again.'
          : e.code;
    } catch (e) {
      error = e.toString();
    } finally {
      busy = false;
      emit();
    }
    if (pending != null) await checkStatus();
  }

  Future<void> checkStatus() async {
    if (busy || pending == null || blocked) return;
    busy = true;
    emit();
    try {
      final result = await api.command('/api/v1/configuration/activation', {
        'action': 'status',
        'request_id': pending!['request_id'],
      });
      final receipt = result['receipt'];
      if (receipt?['request_id'] != pending!['request_id']) return;
      if (['failed', 'interrupted'].contains(receipt?['status'])) {
        error =
            'Layout save ${receipt['status']}: ${receipt['error'] ?? 'Inspect station state'}';
        await repository!.clear('labware');
        pending = null;
      } else if (receipt?['status'] == 'applied' &&
          result['host']?['status'] == 'ready' &&
          result['active']?['fingerprint'] ==
              envelope?['configuration_fingerprint'] &&
          ready) {
        await repository!.clear('labware');
        pending = null;
        editing = false;
        error = null;
        message = 'Layout saved. Station ready.';
        catalogue = null;
        target = null;
        selection = null;
      }
    } catch (e) {
      error = 'Save status unavailable: $e. No automatic repeat.';
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
