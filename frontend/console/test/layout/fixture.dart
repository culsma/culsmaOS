import 'dart:convert';
import 'dart:io';
import 'package:culsma_console/api/console_api.dart';
import 'package:culsma_console/features/layout/interactor/layout_controller.dart';
import 'package:culsma_console/features/layout/model/layout_model.dart';

class LayoutFixture {
  static Map<String, dynamic> profile() =>
      jsonDecode(File('test/fixtures/profile.json').readAsStringSync());
  static Map<String, dynamic> hamiltonProfile() => jsonDecode(
    File('test/fixtures/hamilton_profile.json').readAsStringSync(),
  );
  static LayoutController controller({Map<String, dynamic>? installedProfile}) {
    final profile = installedProfile ?? LayoutFixture.profile();
    final c = LayoutController(FakeConsoleApi(), pollInterval: Duration.zero);
    c.profiles = [profile];
    c.active = {
      'host': {'status': 'ready'},
      'active': {
        'fingerprint': 'host-fingerprint',
        'origin': {
          'draft_id': profile['activation_supported'] == false
              ? 'other-active-setup'
              : 'station',
          'revision': 1,
          'configuration_fingerprint': 'saved-fingerprint',
          'title': 'Transfer station',
        },
      },
    };
    c.selectDraft({
      'draft_id': 'station',
      'revision': 1,
      'fingerprint': 'saved-fingerprint',
      'driver': profile['driver'],
      'title': profile['activation_supported'] == false
          ? 'Hamilton layout proposal'
          : 'Transfer station',
      'configuration': profile['template'],
    });
    return c;
  }
}

class FakeConsoleApi implements ConsoleApi {
  final calls = <Map<String, dynamic>>[];
  ConsoleApiError? error;
  Map<String, dynamic>? getRecord;
  bool closed = false;
  @override
  Future<Map<String, dynamic>> read(String path) async {
    calls.add({'path': path});
    if (error != null) throw error!;
    if (path.endsWith('/profiles'))
      return {
        'profiles': [LayoutFixture.profile()],
      };
    if (path.endsWith('/drafts')) return {'drafts': []};
    return {
      'host': {'status': 'ready'},
      'active': {
        'fingerprint': 'host-fingerprint',
        'origin': {
          'draft_id': 'station',
          'revision': 1,
          'configuration_fingerprint': 'saved-fingerprint',
        },
      },
    };
  }

  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) async {
    calls.add({'path': path, ...LayoutData.copy(body)});
    if (error != null) throw error!;
    switch (body['action']) {
      case 'create':
        return {
          'draft': {
            ...body,
            'draft_id': 'new-setup',
            'revision': 1,
            'fingerprint': 'new-fingerprint',
          },
        };
      case 'get':
        return {
          'draft':
              getRecord ??
              {
                'draft_id': 'station',
                'revision': 1,
                'fingerprint': 'saved-fingerprint',
                'driver': 'opentrons-simulator',
                'title': 'Transfer station',
                'configuration': LayoutFixture.profile()['template'],
              },
        };
      case 'save':
        return {
          'draft': {
            ...body,
            'revision': body['revision'] + 1,
            'fingerprint': 'new-fingerprint',
          },
        };
      case 'validate':
        return {
          'validation': {'valid': true, 'diagnostics': []},
        };
      case 'apply':
        return {'status': 'accepted'};
      case 'status':
        return {
          'host': {'status': 'ready'},
          'active': {
            'fingerprint': 'new-host',
            'origin': {'draft_id': 'station', 'revision': 2},
          },
          'receipt': {'request_id': body['request_id'], 'status': 'applied'},
        };
      default:
        throw StateError('Unexpected request');
    }
  }

  @override
  void close() {
    closed = true;
  }
}
