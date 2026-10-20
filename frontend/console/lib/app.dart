import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'features/layout/interactor/layout_controller.dart';
import 'features/layout/view/layout_page.dart';
import 'features/layout/view/setup_header.dart';

class CulsmaConsole extends StatefulWidget {
  final LayoutController controller;
  const CulsmaConsole({super.key, required this.controller});
  @override
  State<CulsmaConsole> createState() => CulsmaConsoleState();
}

class CulsmaConsoleState extends State<CulsmaConsole> {
  bool system = false;
  late final SemanticsHandle semantics;
  @override
  void initState() {
    super.initState();
    // Native automation must see the same controls without enabling a screen reader.
    semantics = SemanticsBinding.instance.ensureSemantics();
  }

  @override
  void dispose() {
    semantics.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'culsmaOS',
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'Console',
      colorSchemeSeed: const Color(0xff193c61),
      brightness: Brightness.light,
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
    ),
    home: AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final c = widget.controller;
        return LayoutBuilder(
          builder: (context, bounds) {
            final compact = bounds.maxWidth < 720;
            final content = SafeArea(
              child: Column(
                children: [
                  SetupHeader(controller: c),
                  Expanded(
                    child: system
                        ? systemInformation(context)
                        : LayoutPage(controller: c),
                  ),
                ],
              ),
            );
            return Scaffold(
              backgroundColor: const Color(0xfff4f6f9),
              appBar: compact ? AppBar(title: const Text('culsmaOS')) : null,
              bottomNavigationBar: compact
                  ? NavigationBar(
                      selectedIndex: system ? 1 : 0,
                      onDestinationSelected: (index) =>
                          setState(() => system = index == 1),
                      destinations: const [
                        NavigationDestination(
                          icon: Icon(Icons.dashboard_outlined),
                          label: 'Layout',
                        ),
                        NavigationDestination(
                          icon: Icon(Icons.settings_outlined),
                          label: 'System Information',
                        ),
                      ],
                    )
                  : null,
              body: compact
                  ? content
                  : Row(
                      children: [
                        Container(
                          width: 204,
                          color: const Color(0xff142b43),
                          child: SafeArea(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                const Padding(
                                  padding: EdgeInsets.fromLTRB(24, 30, 20, 6),
                                  child: Text(
                                    'culsmaOS',
                                    style: TextStyle(
                                      fontSize: 25,
                                      color: Colors.white,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                                const Padding(
                                  padding: EdgeInsets.fromLTRB(24, 0, 20, 36),
                                  child: Text(
                                    'STATION CONSOLE',
                                    style: TextStyle(
                                      fontSize: 10,
                                      letterSpacing: 1.5,
                                      color: Color(0xffa1b5c8),
                                    ),
                                  ),
                                ),
                                navigationItem(
                                  'Layout',
                                  Icons.dashboard_outlined,
                                  !system,
                                  () => setState(() => system = false),
                                ),
                                navigationItem(
                                  'System Information',
                                  Icons.settings_outlined,
                                  system,
                                  () => setState(() => system = true),
                                ),
                                const Spacer(),
                                const Padding(
                                  padding: EdgeInsets.all(24),
                                  child: Text(
                                    'Local workspace',
                                    style: TextStyle(
                                      color: Color(0xffa1b5c8),
                                      fontSize: 12,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                        Expanded(child: content),
                      ],
                    ),
            );
          },
        );
      },
    ),
  );

  Widget navigationItem(
    String label,
    IconData icon,
    bool selected,
    VoidCallback action,
  ) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
    child: Semantics(
      selected: selected,
      child: Material(
        color: Colors.transparent,
        child: ListTile(
          selected: selected,
          selectedTileColor: const Color(0xff284761),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          leading: Icon(
            icon,
            size: 20,
            color: selected ? Colors.white : const Color(0xffa1b5c8),
          ),
          title: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              color: selected ? Colors.white : const Color(0xffc3cfda),
            ),
          ),
          onTap: action,
        ),
      ),
    ),
  );

  Widget systemInformation(BuildContext context) {
    final c = widget.controller;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Text(
          'System Information',
          style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 16),
        Text('Station: ${c.active?['host']?['status'] ?? 'Unavailable'}'),
        const SizedBox(height: 8),
        Text(
          'Active setup: ${c.active?['active']?['origin']?['title'] ?? 'Service startup configuration'}',
        ),
        const SizedBox(height: 20),
        const Text(
          'Installed driver definitions',
          style: TextStyle(fontSize: 18),
        ),
        ...c.profiles.map(
          (p) => ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(p['label'] ?? p['driver']),
            subtitle: Text(p['driver']),
          ),
        ),
        const Divider(),
        const Text(
          'Hardware discovery, serial port details and physical position verification are not collected by this integration.',
        ),
        const SizedBox(height: 12),
        const Text(
          'Source: local OS records and installed driver metadata. Proposed layout edits do not change these records.',
        ),
      ],
    );
  }
}
