import 'dart:async';
import 'package:flutter/scheduler.dart';
import '../../../api/console_api.dart';
import 'console_interactor.dart';

/// The same renderer-session protocol as other consoles, with a pipe-issued credential.
class NativeRendererInteractor {
  final ConsoleApi api;
  final NativeConsoleInteractor console;
  Map<String, dynamic>? session;
  final completed = <String, Map<String, dynamic>>{};
  Timer? timer, heartbeatTimer;
  int activityCursor = 0;
  bool stopped = false, visible = true;
  NativeRendererInteractor(this.api, this.console);
  Future<Map<String, dynamic>> request(Map<String, dynamic> payload) =>
      api.command('/api/v1/console/renderer', payload);
  Map<String, dynamic> identity(String action) => {
    'action': action,
    'session_id': session!['session_id'],
    'epoch': session!['epoch'],
    'revision': session!['revision'],
  };
  void start() {
    poll();
    heartbeat();
  }

  Future<void> heartbeat() async {
    if (stopped) return;
    try {
      if (session != null) await request(identity('heartbeat'));
    } catch (_) {
      /* Poll reconciles the owned session. */
    }
    if (!stopped) heartbeatTimer = Timer(const Duration(seconds: 4), heartbeat);
  }

  Future<void> poll() async {
    if (stopped) return;
    try {
      if (session == null) {
        final registered = await request({
          'action': 'register',
          'state': console.viewState,
        });
        session = registered['session'];
        // History is visible, but old actions never steal focus when a renderer starts.
        await observeActivity(registered['activity'], follow: false);
      }
      final result = await request({
        ...identity('poll'),
        'activity_after': activityCursor,
        'state': console.viewState,
      });
      session = result['session'];
      await observeActivity(result['activity']);
      for (final row in result['requests'] as List) {
        if (stopped) break;
        final id = row['request_id'] as String,
            command = Map<String, dynamic>.from(row['request']);
        var outcome = completed[id];
        if (outcome == null) {
          var status = 'deferred';
          if (command['expected_revision'] == session!['revision'] &&
              !console.dirty &&
              !console.working &&
              visible) {
            try {
              status = await apply(command) ? 'displayed' : 'rejected';
            } catch (_) {
              status = 'rejected';
            }
          }
          outcome = {'outcome': status, 'state': console.viewState};
          completed[id] = outcome;
          if (completed.length > 64) completed.remove(completed.keys.first);
        }
        session = (await request({
          ...identity('acknowledge'),
          'request_id': id,
          ...outcome,
        }))['session'];
      }
    } on ConsoleApiError catch (error) {
      if (error.status == 409 && session != null) {
        try {
          session = (await request(identity('inspect')))['session'];
        } catch (_) {
          stopped = true;
        }
      } else if (error.status == 401 ||
          error.code == 'CONSOLE_RENDERER_EXPIRED')
        stopped = true;
    } catch (_) {
      /* A transport failure never repeats an experiment command. */
    }
    if (!stopped) timer = Timer(const Duration(milliseconds: 600), poll);
  }

  Future<void> observeActivity(dynamic rows, {bool follow = true}) async {
    if (rows is! List) return;
    for (final value in rows) {
      final row = Map<String, dynamic>.from(value);
      final sequence = row['sequence'] as int;
      if (sequence <= activityCursor) continue;
      activityCursor = sequence;
      await console.observeActivity(row, follow: follow && visible);
    }
  }

  Future<bool> apply(Map<String, dynamic> command) async {
    final view = command['view'] as String;
    console.open(
      view,
      {'experiment', 'editor'}.contains(view) ? command['entity_id'] : null,
    );
    if (view == 'editor') {
      await console.editor.load(command['entity_id']);
      if (!console.editor.document(command['entity_id']).loaded) return false;
    } else if (view != 'desktop')
      await console.refresh();
    await SchedulerBinding.instance.endOfFrame;
    if ((console.active?.view ?? 'desktop') != view) return false;
    if (view == 'experiment' &&
        (console.active?.entityId != command['entity_id'] ||
            !console.runs.containsKey(command['entity_id'])))
      return false;
    if (view == 'workstation' && command['entity_id'] != null) {
      console.selectedEntity = command['entity_id'];
      console.notifyViewChanged();
      await SchedulerBinding.instance.endOfFrame;
      return await console.revealTarget?.call(command['entity_id']) ?? false;
    }
    return true;
  }

  Future<void>? closing;

  Future<void> close() => closing ??= closeSession();

  Future<void> closeSession() async {
    stopped = true;
    timer?.cancel();
    heartbeatTimer?.cancel();
    if (session != null) {
      try {
        await request(identity('close'));
      } catch (_) {
        /* Presence expires without releasing reservations. */
      }
    }
    api.close();
  }
}
