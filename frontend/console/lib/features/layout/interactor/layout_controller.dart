import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../model/layout_model.dart';

class LayoutController extends ChangeNotifier {
  final ConsoleApi api;
  Map<String, dynamic>? active, draft, proposal, profile;
  List<Map<String, dynamic>> profiles = [], drafts = [];
  String? selectedPosition, message, pendingRequest;
  bool busy = false, valid = false, confirmed = false, writeUncertain = false;
  final Duration pollInterval;
  LayoutController(
    this.api, {
    this.pollInterval = const Duration(milliseconds: 300),
  });

  LayoutDefinition? get definition {
    if (profile?['layout'] == null || proposal == null) return null;
    return LayoutDefinition(profile!['layout'], proposal!);
  }

  bool get dirty =>
      proposal != null &&
      LayoutData.canonical(proposal) !=
          LayoutData.canonical(draft?['configuration']);
  bool get canApply =>
      profile?['activation_supported'] != false &&
      !busy &&
      !dirty &&
      valid &&
      confirmed &&
      !writeUncertain &&
      pendingRequest == null &&
      active?['active']?['fingerprint'] != null &&
      ['ready', 'failed'].contains(active?['host']?['status']);

  Future<void> perform(
    Future<void> Function() operation, {
    bool writes = false,
  }) async {
    if (busy) return;
    busy = true;
    message = null;
    notifyListeners();
    try {
      await operation();
    } on ConsoleApiError catch (error) {
      writeUncertain = writeUncertain || (writes && error.responseUnknown);
      message = error.responseUnknown && writes
          ? 'Response unknown. No automatic retry. Inspect the station and saved records before continuing.'
          : error.code;
    } catch (error) {
      message = error is FormatException
          ? error.message.toString()
          : 'CONSOLE_PRESENTATION_ERROR';
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> load() => perform(() async {
    active = await api.read('/api/v1/configuration/active');
    profiles = List<Map<String, dynamic>>.from(
      (await api.read('/api/v1/configuration/profiles'))['profiles'],
    );
    drafts = List<Map<String, dynamic>>.from(
      (await api.read('/api/v1/configuration/drafts'))['drafts'],
    );
    final origin = active?['active']?['origin'];
    if (proposal != null) return; // Refresh must never discard unsaved work.
    if (origin != null) {
      final result = await api.command('/api/v1/configuration/drafts', {
        'action': 'get',
        'draft_id': origin['draft_id'],
        'revision': origin['revision'],
      });
      final record = result['draft'] as Map<String, dynamic>;
      if (record['draft_id'] != origin['draft_id'] ||
          record['revision'] != origin['revision'] ||
          record['fingerprint'] != origin['configuration_fingerprint']) {
        throw const FormatException('CURRENT_CONFIGURATION_IDENTITY_MISMATCH');
      }
      selectDraft(record);
    }
  });

  void selectDraft(Map<String, dynamic> record) {
    if (dirty || writeUncertain || pendingRequest != null)
      throw const FormatException('LAYOUT_UNSAVED_CHANGES');
    draft = LayoutData.copy(record);
    proposal = LayoutData.copy(record['configuration']);
    profile = profiles
        .where((p) => p['driver'] == record['driver'])
        .firstOrNull;
    valid = false;
    confirmed = false;
    selectedPosition = null;
    notifyListeners();
  }

  Future<void> openDraft(String id) => perform(() async {
    final result = await api.command('/api/v1/configuration/drafts', {
      'action': 'get',
      'draft_id': id,
    });
    selectDraft(result['draft']);
  });

  Future<void> createSetup(
    Map<String, dynamic> installedProfile,
  ) => perform(() async {
    if (dirty || writeUncertain || pendingRequest != null) return;
    final result = await api.command('/api/v1/configuration/drafts', {
      'action': 'create',
      'title': '${installedProfile['label'] ?? installedProfile['driver']} setup'
          .substring(
            0,
            min(
              120,
              '${installedProfile['label'] ?? installedProfile['driver']} setup'
                  .length,
            ),
          ),
      'driver': installedProfile['driver'],
      'configuration': installedProfile['template'],
    });
    selectDraft(result['draft']);
    message = installedProfile['activation_supported'] == false
        ? 'New offline proposal. The active station is unchanged.'
        : 'New proposed setup from the installed driver. Check and apply it explicitly.';
  }, writes: true);

  void selectPosition(String id) {
    selectedPosition = id;
    notifyListeners();
  }

  void confirm(bool value) {
    confirmed = value;
    notifyListeners();
  }

  void edit(Map<String, dynamic> value) {
    if (busy || writeUncertain || pendingRequest != null) return;
    proposal = value;
    try {
      if (selectedPosition != null &&
          !(definition?.positions.any((p) => p.id == selectedPosition) ??
              false)) {
        selectedPosition = null;
      }
    } on FormatException {
      selectedPosition = null;
    }
    valid = false;
    confirmed = false;
    message = 'Proposed layout changed. No hardware has moved.';
    notifyListeners();
  }

  void move(LayoutItem item, String position) {
    try {
      edit(definition!.move(proposal!, item, position));
      selectedPosition = position;
      notifyListeners();
    } on FormatException catch (error) {
      message = error.message.toString();
      notifyListeners();
    }
  }

  void add(
    LayoutCollection collection,
    String name,
    String model,
    String position,
  ) {
    try {
      edit(definition!.add(proposal!, collection, name, model, position));
    } on FormatException catch (error) {
      message = error.message.toString();
      notifyListeners();
    }
  }

  void placeChild(
    LayoutCollection collection,
    String name,
    String model,
    LayoutItem parent,
    String site,
  ) {
    try {
      edit(
        definition!.placeChild(
          proposal!,
          collection,
          name,
          model,
          parent,
          site,
        ),
      );
    } on FormatException catch (error) {
      message = error.message.toString();
      notifyListeners();
    }
  }

  void discard() {
    if (busy || writeUncertain || pendingRequest != null || draft == null)
      return;
    proposal = LayoutData.copy(draft!['configuration']);
    valid = false;
    confirmed = false;
    message = 'Unsaved layout edits discarded.';
    notifyListeners();
  }

  Future<void> save() => perform(() async {
    if (!dirty || writeUncertain || pendingRequest != null) return;
    final result = await api.command('/api/v1/configuration/drafts', {
      'action': 'save',
      'draft_id': draft!['draft_id'],
      'revision': draft!['revision'],
      'title': draft!['title'],
      'driver': draft!['driver'],
      'configuration': proposal,
    });
    draft = result['draft'];
    proposal = LayoutData.copy(draft!['configuration']);
    valid = false;
    confirmed = false;
    message = profile?['activation_supported'] == false
        ? 'Layout saved. Check the proposed placement.'
        : 'Layout saved. Check before applying.';
  }, writes: true);

  Future<void> validate() => perform(() async {
    if (dirty || draft == null || writeUncertain || pendingRequest != null)
      return;
    valid = false;
    confirmed = false;
    final result = await api.command('/api/v1/configuration/drafts', {
      'action': 'validate',
      'draft_id': draft!['draft_id'],
      'revision': draft!['revision'],
    });
    valid = result['validation']['valid'] == true;
    final diagnostics = result['validation']['diagnostics'] as List;
    message = valid
        ? (profile?['activation_supported'] == false
              ? 'Offline layout checks passed. The active station is unchanged.'
              : 'Static layout checks passed. Device preflight still runs before execution.')
        : diagnostics
              .map((e) => '${e['path']}: ${e['message'] ?? e['code']}')
              .join('\n');
  });

  Future<void> apply() async {
    if (!canApply) return;
    await perform(() async {
      final random = Random.secure();
      pendingRequest = List.generate(
        24,
        (_) => random.nextInt(16).toRadixString(16),
      ).join();
      // A write is dispatched once. All subsequent requests only read its durable receipt.
      try {
        await api.command('/api/v1/configuration/activation', {
          'action': 'apply',
          'draft_id': draft!['draft_id'],
          'revision': draft!['revision'],
          'expected_fingerprint': active!['active']['fingerprint'],
          'request_id': pendingRequest,
        });
      } on ConsoleApiError catch (error) {
        if (error.status != null && error.status! < 500) pendingRequest = null;
        rethrow;
      }
      confirmed = false;
      await observeApplication();
    }, writes: true);
  }

  Future<void> observeApplication() async {
    for (var attempt = 0; attempt < 100; attempt++) {
      active = await api.command('/api/v1/configuration/activation', {
        'action': 'status',
        'request_id': pendingRequest,
      });
      final receipt = active?['receipt'];
      if (receipt?['request_id'] == pendingRequest &&
          ['applied', 'failed', 'interrupted'].contains(receipt?['status'])) {
        message = receipt['status'] == 'applied'
            ? 'Layout applied. Station ready.'
            : 'Application ${receipt['status']}: ${receipt['error'] ?? 'Inspect station state'}';
        pendingRequest = null;
        valid = false;
        writeUncertain = false;
        return;
      }
      notifyListeners();
      await Future<void>.delayed(pollInterval);
    }
    message =
        'Application still pending. Inspect its status; no automatic apply retry.';
  }

  Future<void> inspectPending() => perform(observeApplication);

  @override
  void dispose() {
    api.close();
    super.dispose();
  }
}
