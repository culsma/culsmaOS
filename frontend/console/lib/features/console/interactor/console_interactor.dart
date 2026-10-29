import 'dart:async';
import 'dart:math';
import 'dart:ui';
import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../../layout/interactor/layout_controller.dart';
import '../model/console_model.dart';
import '../repository/pending_request_repository.dart';
import '../repository/mutation_repository.dart';
import 'labware_interactor.dart';
import 'setup_interactor.dart';
import 'supply_interactor.dart';
import 'run_control_interactor.dart';
import 'system_information_interactor.dart';
import 'file_browser_interactor.dart';
import 'run_review_interactor.dart';
import 'developer_interactor.dart';

/// Native presentation coordinator. Backend Interactors own every experiment decision.
class NativeConsoleInteractor extends ChangeNotifier {
  final ConsoleApi api;
  final review = NativeRunReviewInteractor();
  final LayoutController layout;
  final PendingRequestRepository? requests;
  late final NativeDeveloperInteractor developer;
  late final NativeFileBrowserInteractor files;
  late final NativeLabwareInteractor labware;
  late final NativeSetupInteractor setup;
  late final NativeSupplyInteractor supplies;
  late final NativeRunControlInteractor controls;
  late final NativeSystemInformationInteractor information;
  final windows = <ConsoleWindowModel>[];
  final runs = <String, Map<String, dynamic>>{};
  Map<String, dynamic>? station, inspection, pendingStart, launchReview;
  String? activeId, selectedFile, selectedEntity, message, messageDetails;
  bool busy = false, disposed = false;
  bool checkingRun = false, submittingRun = false;
  Completer<void>? refreshCompletion;
  bool get reviewBusy => checkingRun || submittingRun;
  Timer? timer;
  Future<bool> Function(String)? revealTarget;
  NativeConsoleInteractor(
    this.api,
    this.layout, {
    this.requests,
    ConsoleMutationRepository? mutations,
    String initialView = 'files',
  }) {
    developer = NativeDeveloperInteractor(api)..addListener(notifyViewChanged);
    files = NativeFileBrowserInteractor(api)..addListener(notifyViewChanged);
    labware = NativeLabwareInteractor(api, mutations)
      ..addListener(notifyViewChanged);
    information = NativeSystemInformationInteractor(api)
      ..addListener(notifyViewChanged);
    controls = NativeRunControlInteractor(api, mutations)
      ..addListener(notifyViewChanged);
    supplies = NativeSupplyInteractor(api, mutations)
      ..addListener(notifyViewChanged);
    setup = NativeSetupInteractor(api, mutations)
      ..addListener(notifyViewChanged);
    open(initialView);
  }
  ConsoleWindowModel? get active =>
      windows.where((w) => w.id == activeId).firstOrNull;
  String? get stationProblem {
    final host = station?['host'];
    if (host?['worker_error'] != null)
      return 'The station needs attention. Open Workstation or System Info to review its status.';
    if (host?['blocked_run'] != null)
      return host['blocked_reason'] == 'paused'
          ? 'An experiment is paused. Resume or cancel it before starting another.'
          : 'The workstation is waiting for a run to be reviewed. Open its record before starting another experiment.';
    return null;
  }

  bool get dirty =>
      layout.dirty ||
      labware.editing ||
      labware.pending != null ||
      labware.blocked ||
      setup.dirty ||
      supplies.editing ||
      supplies.pending != null ||
      supplies.blocked;
  bool get working =>
      busy ||
      layout.busy ||
      labware.busy ||
      setup.busy ||
      supplies.busy ||
      controls.busy.isNotEmpty;

  ConsoleWindowModel open(String view, [String? entityId]) {
    if (view == 'desktop') {
      showDesktop();
      return ConsoleWindowModel(
        'desktop',
        'desktop',
        'Desktop',
        null,
        Rect.zero,
      );
    }
    if (view == 'experiment' && (entityId == null || entityId.isEmpty))
      throw const FormatException('RUN_ID_REQUIRED');
    final title = view == 'preparation'
        ? 'Check experiment'
        : view == 'experiment'
        ? 'Experiment · ${entityId!.substring(0, min(8, entityId.length))}'
        : ConsoleWindowDescriptor.applications
              .firstWhere((a) => a.view == view)
              .label;
    final id = view == 'experiment' ? 'run:$entityId' : view;
    final existing = windows.where((w) => w.id == id).firstOrNull;
    final window =
        existing ??
        ConsoleWindowModel(
          id,
          view,
          title,
          entityId,
          Rect.fromLTWH(
            20 + (windows.length % 5) * 22,
            18 + (windows.length % 5) * 22,
            1080,
            720,
          ),
        );
    if (existing != null) windows.remove(existing);
    windows.add(window);
    window.minimized = false;
    activeId = id;
    selectedEntity = null;
    message = null;
    messageDetails = null;
    notifyListeners();
    return window;
  }

  void showDesktop() {
    for (final w in windows) {
      w.minimized = true;
    }
    activeId = null;
    notifyListeners();
  }

  bool protect(ConsoleWindowModel w) {
    if (working) {
      message = 'A console operation is finishing.';
      notifyListeners();
      return true;
    }
    if (w.view == 'experiment' &&
        (setup.edits[w.entityId]?['dirty'] == true ||
            setup.acknowledged(w.entityId!))) {
      message =
          'Save or discard placement edits and clear loading acknowledgement before closing this window.';
      notifyListeners();
      return true;
    }
    if (w.view == 'settings' &&
        (dirty || layout.writeUncertain || layout.pendingRequest != null)) {
      message =
          'Save or discard the open edit before closing or minimizing this window.';
      notifyListeners();
      return true;
    }
    return false;
  }

  void closeWindow(ConsoleWindowModel w) {
    if (protect(w)) return;
    windows.remove(w);
    if (w.view == 'preparation') launchReview = null;
    selectRemaining(w);
  }

  void minimize(ConsoleWindowModel w) {
    if (protect(w)) return;
    w.minimized = true;
    selectRemaining(w);
  }

  void selectRemaining(ConsoleWindowModel w) {
    if (activeId == w.id)
      activeId = windows.where((v) => !v.minimized).lastOrNull?.id;
    notifyListeners();
  }

  void maximize(ConsoleWindowModel w) {
    w.maximized = !w.maximized;
    notifyListeners();
  }

  void move(ConsoleWindowModel w, Offset delta, Size area) {
    if (w.maximized) return;
    final width = min(w.bounds.width, area.width),
        height = min(w.bounds.height, area.height);
    w.bounds = Rect.fromLTWH(
      (w.bounds.left + delta.dx).clamp(0, max(0, area.width - width)),
      (w.bounds.top + delta.dy).clamp(0, max(0, area.height - height)),
      w.bounds.width,
      w.bounds.height,
    );
    notifyListeners();
  }

  void resize(ConsoleWindowModel w, Offset delta, Size area) {
    w.bounds = Rect.fromLTWH(
      w.bounds.left,
      w.bounds.top,
      (w.bounds.width + delta.dx).clamp(
        min(390, area.width),
        max(min(390, area.width), area.width - w.bounds.left),
      ),
      (w.bounds.height + delta.dy).clamp(
        min(260, area.height),
        max(min(260, area.height), area.height - w.bounds.top),
      ),
    );
    notifyListeners();
  }

  Future<void> start() async {
    try {
      pendingStart = await requests?.read();
      await labware.restore();
      await supplies.restore();
    } catch (_) {
      message = 'Pending run records could not be read. Starting is disabled.';
      pendingStart = {'blocked': true};
    }
    await refresh();
    schedule();
  }

  void schedule() {
    timer?.cancel();
    if (!disposed)
      timer = Timer(const Duration(seconds: 2), () async {
        await refresh();
        schedule();
      });
  }

  Future<void> refresh() async {
    if (busy || disposed) return;
    final completion = Completer<void>();
    refreshCompletion = completion;
    busy = true;
    notifyListeners();
    try {
      station = await api.read('/api/v1/station');
      await information.observe(station);
      await supplies.refresh();
      final pendingLayout = labware.pending;
      await labware.observe(stationLayout());
      if (pendingLayout != null &&
          labware.pending == null &&
          !layout.dirty &&
          !layout.busy &&
          !layout.writeUncertain &&
          layout.pendingRequest == null) {
        layout.proposal = null;
        layout.draft = null;
        await layout.load();
      }
      if (!files.initialized) await files.initialize();
      final observed = {
        for (final w in windows)
          if (w.view == 'experiment' && w.entityId != null) w.entityId!,
        ...controls.pending.keys,
      };
      for (final run in observed) {
        try {
          runs[run] = await api.read(
            '/api/v1/runs/${Uri.encodeComponent(run)}',
          );
          await controls.observe(runs[run]!);
          if (active?.entityId == run) await setup.observe(runs[run]!);
        } catch (error) {
          message =
              'An experiment record could not be loaded. Refresh the station to try again.';
          messageDetails = error.toString();
        }
      }
    } catch (error) {
      message =
          'The operation could not be completed. Check the workstation and try again when it is ready.';
      messageDetails = error.toString();
    } finally {
      busy = false;
      refreshCompletion = null;
      completion.complete();
      if (!disposed) notifyListeners();
    }
  }

  Map<String, dynamic>? stationLayout() {
    final value = station?['layout'];
    if (value is! Map) return null;
    return {
      ...Map<String, dynamic>.from(value),
      'editing_ready':
          station?['host']?['status'] == 'ready' &&
          pendingStart == null &&
          !(station?['runs'] as List? ?? []).any(
            (run) => !{
              'completed',
              'failed',
              'rejected',
              'cancelled',
            }.contains(run['status']),
          ),
    };
  }

  String requestId() => List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  /// Double-click checks an immutable source snapshot; it never dispatches work.
  Future<void> launch(String id, {String sourceScope = 'programs'}) async {
    if (working || pendingStart != null) return;
    if (dirty) {
      message =
          'Finish or discard the current edit before checking another experiment.';
      notifyListeners();
      return;
    }
    busy = true;
    checkingRun = true;
    selectedFile = id;
    launchReview = null;
    inspection = null;
    open('preparation');
    try {
      final result = await api.command('/api/v1/programs', {
        'action': 'preview',
        'program_id': id,
        if (sourceScope != 'programs') 'source_scope': sourceScope,
      });
      inspection = result;
      if (result['valid'] != true ||
          result['preparation']?['status'] == 'blocked') {
        message = 'The experiment needs attention before it can run.';
        messageDetails =
            result['preparation']?['diagnostic']?.toString() ??
            result['diagnostics']?.toString();
        return;
      }
      if (result['snapshot_id'] is! String)
        throw const FormatException('Missing checked source snapshot');
      launchReview = {
        'action': 'start',
        'program_id': id,
        if (sourceScope != 'programs') 'source_scope': sourceScope,
        'snapshot_id': result['snapshot_id'],
        if (result['preparation']?['configuration_fingerprint'] != null)
          'configuration_fingerprint':
              result['preparation']['configuration_fingerprint'],
      };
    } catch (error) {
      message =
          'The experiment could not be checked. Review the workstation and try again.';
      messageDetails = error.toString();
    } finally {
      busy = false;
      checkingRun = false;
      if (!disposed) notifyListeners();
    }
  }

  /// An explicit simulation action; never reinterpret a hardware station as simulated.
  Future<void> runSimulation() async {
    await refreshCompletion?.future;
    if (disposed) return;
    if (!review.simulationAvailable(station, inspection)) {
      message =
          'No simulation workstation is available. No experiment has started.';
      notifyListeners();
      return;
    }
    await confirmLaunch();
  }

  /// Confirmation is bound to the checked snapshot and station configuration.
  Future<void> confirmLaunch() async {
    final reviewed = launchReview;
    // A background read must neither flicker controls nor discard a user click.
    await refreshCompletion?.future;
    if (disposed || reviewed == null || !identical(reviewed, launchReview))
      return;
    if (working || dirty || pendingStart != null || launchReview == null)
      return;
    if (requests == null) {
      message = 'Durable run request storage is unavailable.';
      notifyListeners();
      return;
    }
    busy = true;
    submittingRun = true;
    message = null;
    messageDetails = null;
    notifyListeners();
    try {
      final payload = {...launchReview!, 'request_id': requestId()};
      await requests!.save(payload);
      pendingStart = payload;
      launchReview = null;
      await sendPendingStart();
      if (pendingStart == null && active?.view == 'experiment')
        windows.removeWhere((w) => w.view == 'preparation');
    } catch (error) {
      message =
          'The run request needs attention. Check its status before trying again.';
      messageDetails = error.toString();
    } finally {
      busy = false;
      submittingRun = false;
      if (!disposed) notifyListeners();
    }
  }

  Future<void> cancelLaunch() async {
    final reviewWindow = active;
    await refreshCompletion?.future;
    if (!disposed &&
        reviewWindow?.view == 'preparation' &&
        active == reviewWindow) {
      closeWindow(reviewWindow!);
    }
  }

  Future<void> checkPendingStart() async {
    if (busy || pendingStart == null || pendingStart!['blocked'] == true)
      return;
    busy = true;
    notifyListeners();
    try {
      await sendPendingStart();
    } finally {
      busy = false;
      if (!disposed) notifyListeners();
    }
  }

  Future<void> sendPendingStart() async {
    try {
      final result = await api.command('/api/v1/programs', pendingStart!);
      final run = Map<String, dynamic>.from(result['run']);
      // Clear only after recording an authoritative run identity in memory.
      runs[run['run_id']] = run;
      open('experiment', run['run_id']);
      await requests!.clear();
      pendingStart = null;
    } on ConsoleApiError catch (error) {
      if (error.status != null && error.status! < 500) {
        await requests!.clear();
        pendingStart = null;
      }
      message = error.responseUnknown
          ? 'Run response unknown. Check the retained request; no automatic retry.'
          : 'The experiment could not be started. Check the workstation and open the protocol again when it is ready.';
      messageDetails = error.code;
    } catch (error) {
      message =
          'The operation could not be completed. Check the workstation and try again when it is ready.';
      messageDetails = error.toString();
    }
  }

  void notifyViewChanged() => notifyListeners();

  void reveal(String entity) {
    open('workstation');
    selectedEntity = entity;
    notifyListeners();
  }

  Map<String, dynamic> get viewState => {
    'view': active?.view ?? 'desktop',
    'entity_id': active?.entityId,
    'selected_entity_id': selectedEntity,
    'dirty': dirty,
    'busy': working,
  };
  @override
  void dispose() {
    disposed = true;
    timer?.cancel();
    developer.dispose();
    files.dispose();
    information.dispose();
    controls.dispose();
    supplies.dispose();
    labware.dispose();
    setup.dispose();
    super.dispose();
  }
}
