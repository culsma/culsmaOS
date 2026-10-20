import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'api/console_api.dart';
import 'app.dart';
import 'features/layout/interactor/layout_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    final line = await stdin
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .first
        .timeout(const Duration(seconds: 10));
    final connection = DesktopConnection.fromJson(jsonDecode(line));
    final controller = LayoutController(LocalConsoleApi(connection));
    runApp(CulsmaConsole(controller: controller));
    await controller.load();
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
