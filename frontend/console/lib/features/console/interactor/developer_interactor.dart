import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';

class NativeDeveloperInteractor extends ChangeNotifier {
  final ConsoleApi api;
  bool busy = false, disposed = false;
  Map<String, dynamic>? result;
  String? error;
  NativeDeveloperInteractor(this.api);

  Future<void> trigger(String scenario) async {
    if (busy) return;
    busy = true;
    error = null;
    notifyListeners();
    try {
      result = await api.command('/api/v1/developer/fault-test', {
        'scenario': scenario,
      });
    } catch (e) {
      error = 'The diagnostic test could not run: $e';
    } finally {
      busy = false;
      if (!disposed) notifyListeners();
    }
  }

  void clear() {
    if (busy) return;
    result = null;
    error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}
