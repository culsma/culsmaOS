import 'fixture.dart';
import 'mutation_fixture.dart';

const diagnostic =
    'BATCH_PREPARATION_REJECTED: No available tip positions are declared for this run.';
Map<String, dynamic> shortage() => {
  'run_id': 'empty-tips',
  'status': 'failed',
  'error': diagnostic,
  'user_guidance': {
    'kind': 'preparation',
    'title': 'More tips are needed',
    'message':
        'There were not enough available tips to prepare this attempt. Update the tip supply before starting a new run.',
    'device_activity': 'none_recorded',
    'next_steps': [
      'Replace or replenish the tip box at the workstation.',
      'Check supplies again, then open the protocol from Files to start a new run.',
    ],
    'actions': ['replace_tips', 'refresh', 'open_files'],
  },
  'result': {
    'execution': {'completed_steps': 10, 'total_steps': 13},
  },
};

class GuidanceStockApi extends NativeConsoleFixtureApi {
  int replacements = 0;
  Map<String, dynamic>? replacement;
  String mode = 'simulation';
  Map<String, dynamic> get stock => {
    'supported': true,
    'mode': mode,
    'resource_id': 'tips',
    'revision': originalFingerprint,
    'position_choices': ['1', '2', '3', '4', '5', '6'],
    'stock': {
      'ready': true,
      'available': replacements == 0 ? [] : ['1', '2', '3', '4', '5', '6'],
      'used': replacements == 0 ? ['1', '2', '3', '4', '5', '6'] : [],
      'load_id': replacements == 0 ? 'old' : replacement!['request_id'],
    },
    'pending': [],
    'history': [],
    'current_load': replacement == null
        ? null
        : {'request_id': replacement!['request_id']},
  };
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path == '/api/v1/consumables') {
      if (body['action'] == 'show') return stock;
      if (body['action'] == 'replace') {
        replacements++;
        replacement = Map.of(body);
      }
      return {'request_id': replacement!['request_id'], 'status': 'applied'};
    }
    return super.command(path, body);
  }

  @override
  Future<Map<String, dynamic>> read(String path) async =>
      path.startsWith('/api/v1/runs/') ? shortage() : super.read(path);
}
