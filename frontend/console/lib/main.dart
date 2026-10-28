import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'features/console/interactor/console_interactor.dart';
import 'features/console/interactor/renderer_interactor.dart';
import 'features/console/repository/pending_request_repository.dart';
import 'features/console/repository/mutation_repository.dart';
import 'package:flutter/material.dart';
import 'api/console_api.dart';
import 'app.dart';
import 'features/layout/interactor/layout_controller.dart';
import 'features/layout/repository/layout_archive_repository.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    final line = await stdin
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .first
        .timeout(const Duration(seconds: 10));
    final connection = DesktopConnection.fromJson(jsonDecode(line));
    final controller = LayoutController(
      LocalConsoleApi(connection),
      archives: FileLayoutArchiveRepository(),
    );
    final stationKey =
        connection.stationKey ??
        sha256.convert(utf8.encode(connection.origin.toString())).toString();
    final requests = FilePendingRequestRepository(
      File(
        '${Platform.environment['HOME']}/Library/Application Support/culsmaOS/$stationKey/pending-run.json',
      ),
    );
    final console = NativeConsoleInteractor(
      controller.api,
      controller,
      requests: requests,
      mutations: FileConsoleMutationRepository(
        File(
          '${Platform.environment['HOME']}/Library/Application Support/culsmaOS/$stationKey/pending-changes.json',
        ),
      ),
    );
    final renderer = connection.rendererToken == null
        ? null
        : NativeRendererInteractor(
            LocalConsoleApi(
              DesktopConnection(connection.origin, connection.rendererToken!),
            ),
            console,
          );
    runApp(
      CulsmaConsole(
        controller: controller,
        console: console,
        renderer: renderer,
      ),
    );
    await Future.wait([controller.load(), console.start()]);
    renderer?.start();
  } catch (_) {
    runApp(
      const MaterialApp(
        home: Scaffold(
          body: Center(
            child: Text(
              'Start this console through culsma-os desktop. No local connection was supplied.',
            ),
          ),
        ),
      ),
    );
  }
}
