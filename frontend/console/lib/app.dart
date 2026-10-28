import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'features/layout/interactor/layout_controller.dart';
import 'features/console/interactor/console_interactor.dart';
import 'features/console/view/desktop_shell.dart';
import 'features/console/interactor/renderer_interactor.dart';

class CulsmaConsole extends StatefulWidget {
  final LayoutController controller;
  final NativeConsoleInteractor? console;
  final NativeRendererInteractor? renderer;
  final String initialView;
  const CulsmaConsole({
    super.key,
    required this.controller,
    this.console,
    this.renderer,
    this.initialView = 'files',
  });
  @override
  State<CulsmaConsole> createState() => CulsmaConsoleState();
}

class CulsmaConsoleState extends State<CulsmaConsole>
    with WidgetsBindingObserver {
  late final SemanticsHandle semantics;
  late final NativeConsoleInteractor console;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    semantics = SemanticsBinding.instance.ensureSemantics();
    console =
        widget.console ??
        NativeConsoleInteractor(
          widget.controller.api,
          widget.controller,
          initialView: widget.initialView,
        );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    widget.renderer?.visible =
        state != AppLifecycleState.hidden &&
        state != AppLifecycleState.paused &&
        state != AppLifecycleState.detached;
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.renderer?.close();
    semantics.dispose();
    if (widget.console == null) console.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'CulsmaOS',
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'Console',
      colorSchemeSeed: const Color(0xff193c61),
      brightness: Brightness.light,
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
    ),
    home: ConsoleDesktop(console: console),
  );
}
