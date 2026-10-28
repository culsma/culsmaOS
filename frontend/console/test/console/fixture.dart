import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/repository/pending_request_repository.dart';
import '../layout/fixture.dart';

class MemoryPendingRequestRepository implements PendingRequestRepository {
  Map<String, dynamic>? value;
  @override
  Future<Map<String, dynamic>?> read() async => value;
  @override
  Future<void> save(Map<String, dynamic> request) async {
    value = Map.of(request);
  }

  @override
  Future<void> clear() async {
    value = null;
  }
}

class NativeConsoleFixtureApi extends FakeConsoleApi {
  bool unknownStart = false;
  int startCount = 0;
  @override
  Future<Map<String, dynamic>> read(String path) async {
    if (path == '/api/v1/station')
      return {
        'host': {'status': 'ready'},
        'runs': [],
        'layout': {'status': 'unavailable'},
      };
    if (path == '/api/v1/programs')
      return {
        'enabled': true,
        'source_root': '/Culsma/projects',
        'programs': [
          {'program_id': 'transfer.culs'},
        ],
      };
    if (path.startsWith('/api/v1/runs/')) return completed;
    return super.read(path);
  }

  static Map<String, dynamic> get completed => {
    'run_id': 'run-one',
    'status': 'completed',
    'result': {
      'execution': {'completed_steps': 3, 'total_steps': 3},
      'os': {
        'registered_material': {
          'state': {
            'containers': {
              'target': {
                'volume_uL': 100,
                'metadata': {'kind': 'tube'},
              },
            },
          },
        },
      },
    },
  };
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path == '/api/v1/consumables')
      return {'supported': false, 'reason': 'Test device has no stock port.'};
    if (path == '/api/v1/programs') {
      calls.add({'path': path, ...body});
      if (body['action'] == 'inspect')
        return {
          'valid': true,
          'snapshot_id': 'snapshot',
          'source': 'protocol source',
        };
      if (body['action'] == 'start') {
        startCount++;
        if (unknownStart)
          throw const ConsoleApiError('LOST_RESPONSE', responseUnknown: true);
        return {'run': completed};
      }
    }
    return super.command(path, body);
  }
}
