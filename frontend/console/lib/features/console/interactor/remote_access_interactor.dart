import '../../../api/console_api.dart';

/// Local workstation pairing commands; credentials are returned only to the caller.
class RemoteAccessInteractor {
  final ConsoleApi api;
  RemoteAccessInteractor(this.api);

  Future<Map<String, dynamic>> execute(
    String action, [
    Map<String, dynamic> fields = const {},
  ]) => api.command('/api/v1/remote-access', {...fields, 'action': action});
}
