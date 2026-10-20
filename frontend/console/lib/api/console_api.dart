import 'dart:async';
import 'dart:convert';
import 'dart:io';

abstract interface class ConsoleApi {
  Future<Map<String, dynamic>> read(String path);
  Future<Map<String, dynamic>> command(String path, Map<String, dynamic> body);
  void close();
}

class ConsoleApiError implements Exception {
  final String code;
  final int? status;
  final bool responseUnknown;
  const ConsoleApiError(this.code, {this.status, this.responseUnknown = false});
  @override
  String toString() => code;
}

class DesktopConnection {
  final Uri origin;
  final String token;
  const DesktopConnection(this.origin, this.token);

  factory DesktopConnection.fromJson(Map<String, dynamic> json) {
    final uri = Uri.parse(json['origin'] as String);
    final token = json['access_token'];
    if (json['schema'] != 'culsma_desktop_v1' ||
        uri.scheme != 'http' ||
        uri.host != '127.0.0.1' ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        uri.path.isNotEmpty ||
        token is! String ||
        token.isEmpty) {
      throw const FormatException('DESKTOP_CONNECTION_INVALID');
    }
    return DesktopConnection(uri, token);
  }
}

/// Process-local credential, received through stdin; never stored or logged.
class LocalConsoleApi implements ConsoleApi {
  final DesktopConnection connection;
  final HttpClient client;
  LocalConsoleApi(this.connection, {HttpClient? client})
    : client = client ?? HttpClient() {
    this.client.connectionTimeout = const Duration(seconds: 5);
  }

  @override
  Future<Map<String, dynamic>> read(String path) => request(path, null);
  @override
  Future<Map<String, dynamic>> command(
    String path,
    Map<String, dynamic> body,
  ) => request(path, body);

  Future<Map<String, dynamic>> request(
    String path,
    Map<String, dynamic>? body,
  ) async {
    if (!path.startsWith('/api/v1/') ||
        path.contains('?') ||
        path.contains('#')) {
      throw const ConsoleApiError('CONSOLE_PATH_INVALID');
    }
    try {
      final request = await client.openUrl(
        body == null ? 'GET' : 'POST',
        connection.origin.resolve(path),
      );
      request.followRedirects = false;
      request.headers.set(
        HttpHeaders.authorizationHeader,
        'Bearer ${connection.token}',
      );
      request.headers.set('Origin', connection.origin.toString());
      if (body != null) {
        request.headers.contentType = ContentType.json;
        final encoded = utf8.encode(jsonEncode(body));
        request.contentLength = encoded.length;
        request.add(encoded);
      }
      final response = await request.close().timeout(
        const Duration(seconds: 15),
      );
      final text = await utf8.decoder
          .bind(response)
          .join()
          .timeout(const Duration(seconds: 15));
      if (text.length > 5000000)
        throw const FormatException('RESPONSE_TOO_LARGE');
      final value = jsonDecode(text) as Map<String, dynamic>;
      if (response.statusCode != 200) {
        throw ConsoleApiError(
          value['error']?['code'] as String? ?? 'CONSOLE_REQUEST_FAILED',
          status: response.statusCode,
          responseUnknown: body != null && response.statusCode >= 500,
        );
      }
      return (value['data'] ?? value) as Map<String, dynamic>;
    } on ConsoleApiError {
      rethrow;
    } catch (_) {
      throw ConsoleApiError(
        'CONSOLE_RESPONSE_UNAVAILABLE',
        responseUnknown: body != null,
      );
    }
  }

  @override
  void close() => client.close(force: true);
}
