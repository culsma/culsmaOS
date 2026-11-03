/// Presentation of observed run state; batch duration is never estimated.
class NativeRunProgress {
  final String title, message;
  const NativeRunProgress(this.title, this.message);

  static NativeRunProgress? fromRun(Map run) {
    final status = run['status'];
    if (!const {
      'ready',
      'queued',
      'running',
      'waiting',
      'preparing',
    }.contains(status))
      return null;
    final attempts = run['execution_evidence']?['attempts'] as List? ?? [];
    final outstanding = attempts.any(
      (a) =>
          a['evidence'] == null ||
          !const {'completed', 'rejected'}.contains(a['evidence']?['outcome']),
    );
    if (outstanding)
      return const NativeRunProgress(
        'Waiting for execution to finish',
        'The run is in progress. Completion will appear here automatically. This operation may return its result only when the whole method finishes.',
      );
    if (status == 'ready' || status == 'queued' || status == 'preparing')
      return const NativeRunProgress(
        'Preparing the experiment…',
        'Checking the loading plan and preparing execution. Results will appear here automatically.',
      );
    return const NativeRunProgress(
      'Experiment in progress…',
      'Waiting for the next execution update. Results will appear here automatically.',
    );
  }
}
