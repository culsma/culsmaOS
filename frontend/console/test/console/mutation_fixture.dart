import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/console/repository/mutation_repository.dart';
import 'fixture.dart';

class MemoryConsoleMutationRepository implements ConsoleMutationRepository {
  final values = <String, Map<String, dynamic>>{};
  bool failSave = false;
  @override
  Future<Map<String, dynamic>?> read(String slot) async => values[slot];
  @override
  Future<void> save(String slot, Map<String, dynamic> request) async {
    if (failSave) throw StateError('disk unavailable');
    values[slot] = Map.of(request);
  }

  @override
  Future<void> clear(String slot) async {
    values.remove(slot);
  }
}

const originalFingerprint =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const updatedFingerprint =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
Map<String, dynamic> envelope([String fingerprint = originalFingerprint]) => {
  'status': 'available',
  'editing_ready': true,
  'configuration_fingerprint': fingerprint,
  'layout': {
    'definition': {
      'schema': 'culsma_layout_instances_v1',
      'diagram': {
        'scene': {
          'label': 'Test track deck',
          'positions': List.generate(
            8,
            (i) => {'id': '${i + 1}', 'label': '${i + 1}'},
          ),
          'carriers': [
            {
              'id': 'rack',
              'model': 'old-rack',
              'start': 0,
              'span': 6,
              'sites': ['1', '2'],
              'placements': [
                {'id': 'sample-plate', 'site': '1', 'model': 'old-model'},
              ],
            },
          ],
        },
      },
    },
    'configuration': {},
  },
};

class MutationFixtureApi extends NativeConsoleFixtureApi {
  String fingerprint = originalFingerprint, phase = 'planned';
  bool lostApply = false, lostSetup = false, applied = false;
  Map<String, dynamic>? applyRequest;
  final setupRequests = <Map<String, dynamic>>[];
  Map<String, dynamic> get plan => {
    'run_id': 'loading-run',
    'fingerprint': fingerprint,
    'phase': phase,
    'layout': envelope()['layout'],
    'preferences': {},
    'activity': [],
    'items': [
      {
        'allocation_id': 'allocation',
        'name': 'sample',
        'kind': 'well',
        'capacity_uL': 100,
        'address': {'labware': 'sample-plate', 'well': 'A1'},
      },
    ],
    'candidates': [
      {
        'labware': 'sample-plate',
        'well': 'A1',
        'kinds': ['well'],
        'capacity_uL': 200,
      },
    ],
    'loadout': [
      {
        'labware': 'sample-plate',
        'model': 'Plate',
        'placement': {'carrier': 'rack', 'track': '1', 'site': '1'},
        'containers': [
          {
            'name': 'sample',
            'well': 'A1',
            'volume_uL': 100,
            'contents': {'buffer': 100},
          },
        ],
      },
    ],
    'supplies': [
      {
        'id': 'tips',
        'model': 'Tip rack',
        'available': 6,
        'positions': ['1', '2', '3', '4', '5', '6'],
      },
    ],
  };
  @override
  Future<Map<String, dynamic>> read(String path) async {
    if (path == '/api/v1/station')
      return {
        'host': {'status': 'ready'},
        'runs': [],
        'layout': envelope(fingerprint)..remove('editing_ready'),
      };
    return super.read(path);
  }

  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path == '/api/v1/configuration/labware') {
      calls.add({'path': path, ...body});
      if (body['action'] == 'catalogue')
        return {
          'configuration_fingerprint': fingerprint,
          'catalogue': {
            'targets': [
              {
                'id': 'carrier:rack',
                'kind': 'carrier',
                'parent': 'deck',
                'site': '1',
                'occupants': ['rack'],
                'models': ['new-rack'],
                'current_model': 'old-rack',
                'label': 'Rack at track 1',
              },
              {
                'id': 'occupied',
                'kind': 'site',
                'parent': 'rack',
                'site': '1',
                'occupants': ['sample-plate'],
                'models': ['plate-model', 'reservoir-model'],
                'label': 'rack · site 1',
                'suggested_name': 'new-plate',
              },
              {
                'id': 'vacant',
                'kind': 'site',
                'parent': 'rack',
                'site': '2',
                'occupants': [],
                'models': ['plate-model', 'reservoir-model'],
                'label': 'rack · site 2',
                'suggested_name': 'new-plate',
              },
            ],
            'models': [
              {
                'id': 'new-rack',
                'label': 'Compatible rack',
                'category': 'carrier',
              },
              {
                'id': 'plate-model',
                'label': '96-well plate',
                'category': 'plate',
              },
              {
                'id': 'reservoir-model',
                'label': 'Reservoir 60 mL',
                'category': 'reservoir',
              },
            ],
          },
        };
      return {
        'expected_fingerprint': fingerprint,
        'draft': {'draft_id': 'new-draft', 'revision': 1},
        'impact': ['Bindings cleared'],
      };
    }
    if (path == '/api/v1/configuration/activation') {
      calls.add({'path': path, ...body});
      if (body['action'] == 'apply') {
        applyRequest = Map.of(body);
        if (lostApply)
          throw const ConsoleApiError('LOST_RESPONSE', responseUnknown: true);
        return {'status': 'accepted'};
      }
      return {
        'receipt': {
          'request_id': applyRequest?['request_id'],
          'status': applied ? 'applied' : 'accepted',
        },
        'active': {'fingerprint': updatedFingerprint},
        'host': {'status': 'ready'},
      };
    }
    if (path == '/api/v1/setup' || path == '/api/v1/setup/confirmation') {
      calls.add({'path': path, ...body});
      if (body['action'] == 'show') return plan;
      if (body['action'] == 'status')
        return {'request_id': body['request_id'], 'status': 'completed'};
      setupRequests.add(Map.of(body));
      if (lostSetup)
        throw const ConsoleApiError('LOST_RESPONSE', responseUnknown: true);
      if (body['action'] == 'begin') phase = 'loading';
      return {'status': 'accepted'};
    }
    return super.command(path, body);
  }
}
