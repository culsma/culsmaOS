import 'dart:math';
import 'package:flutter/material.dart';
import '../interactor/console_interactor.dart';
import '../model/console_model.dart';
import 'console_views.dart';

class ConsoleDesktop extends StatelessWidget {
  final NativeConsoleInteractor console;
  const ConsoleDesktop({super.key, required this.console});
  static const icons = {
    'files': Icons.folder_outlined,
    'workstation': Icons.grid_view,
    'settings': Icons.settings_outlined,
    'system_info': Icons.info_outline,
    'developer': Icons.bug_report_outlined,
  };
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: Listenable.merge([console, console.layout]),
    builder: (context, _) => Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(-.3, -.7),
            radius: 1.7,
            colors: [Color(0xfff5f9fc), Color(0xffd4e2ef)],
          ),
        ),
        child: Column(
          children: [
            Expanded(
              child: LayoutBuilder(
                builder: (context, bounds) => Stack(
                  children: [
                    const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.science_outlined,
                            size: 58,
                            color: Color(0xff66839e),
                          ),
                          SizedBox(height: 12),
                          Text(
                            'CulsmaOS',
                            style: TextStyle(
                              fontSize: 32,
                              color: Color(0xff31516e),
                            ),
                          ),
                          Text('Your laboratory workspace'),
                        ],
                      ),
                    ),
                    for (final w in console.windows)
                      ConsoleNativeWindow(
                        key: ValueKey(w.id),
                        console: console,
                        window: w,
                        area: Size(bounds.maxWidth, bounds.maxHeight),
                      ),
                    if (console.message != null ||
                        console.stationProblem != null)
                      Positioned(
                        bottom: 12,
                        left: 16,
                        right: 16,
                        child: Material(
                          elevation: 3,
                          color: const Color(0xfffff2df),
                          borderRadius: BorderRadius.circular(8),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  console.message ?? console.stationProblem!,
                                ),
                                if (console.messageDetails != null)
                                  ExpansionTile(
                                    title: const Text('Technical details'),
                                    children: [
                                      SizedBox(
                                        height: 100,
                                        child: SingleChildScrollView(
                                          child: SelectableText(
                                            console.messageDetails!.length >
                                                    4000
                                                ? console.messageDetails!
                                                      .substring(0, 4000)
                                                : console.messageDetails!,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                              ],
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            if (console.activity.isNotEmpty)
              Material(
                color: const Color(0xffe7eff7),
                child: ExpansionTile(
                  dense: true,
                  leading: const Icon(Icons.smart_toy_outlined, size: 20),
                  title: Text(
                    activityText(console.activity.last),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: const Text(
                    'Console activity · commands and file changes, not device execution evidence',
                  ),
                  children: [
                    SizedBox(
                      height: 130,
                      child: ListView(
                        children: [
                          for (final row in console.activity.reversed.take(12))
                            ListTile(
                              dense: true,
                              title: Text(activityText(row)),
                              subtitle: Text(row['code']?.toString() ?? ''),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            workbar(context),
          ],
        ),
      ),
    ),
  );
  String activityText(Map<String, dynamic> row) {
    final actor = row['actor'] == 'automation' ? 'AI' : 'Operator';
    final phase =
        {
          'started': 'working',
          'returned': 'request returned',
          'failed': 'needs attention',
        }[row['phase']] ??
        row['phase'];
    final action = (row['action'] as String)
        .replaceAll('.', ' · ')
        .replaceAll('_', ' ');
    return '$actor · $action · $phase${row['target'] == null ? '' : ' · ${row['target']}'}';
  }

  Widget workbar(BuildContext context) => LayoutBuilder(
    builder: (context, bounds) {
      final compact = bounds.maxWidth < 1000,
          experiments = console.windows
              .where((w) => w.view == 'experiment')
              .toList();
      return Container(
        height: compact ? 68 : 76,
        decoration: const BoxDecoration(
          color: Color(0xfff8fbff),
          border: Border(top: BorderSide(color: Color(0xffbccddd))),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Row(
          children: [
            Tooltip(
              message: 'Show desktop',
              child: InkWell(
                key: const Key('show-desktop'),
                onTap: console.showDesktop,
                child: Image.asset(
                  'assets/culsma-os-wordmark.png',
                  width: compact ? 70 : 132,
                ),
              ),
            ),
            const SizedBox(width: 12),
            for (final app in ConsoleWindowDescriptor.applications)
              launcher(app, compact),
            if (experiments.isNotEmpty) ...[
              const VerticalDivider(width: 18),
              Expanded(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (final w in experiments)
                        Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: OutlinedButton(
                            key: ValueKey('task-${w.id}'),
                            onPressed: () {
                              console.open(w.view, w.entityId);
                              console.refresh();
                            },
                            child: Text(
                              w.title,
                              style: const TextStyle(fontSize: 11),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ] else
              const Spacer(),
            if (!compact)
              const Padding(
                padding: EdgeInsets.only(left: 12),
                child: Text(
                  'Local',
                  style: TextStyle(fontSize: 11, color: Color(0xff70889c)),
                ),
              ),
          ],
        ),
      );
    },
  );
  Widget launcher(ConsoleWindowDescriptor app, bool compact) => Padding(
    padding: const EdgeInsets.only(right: 5),
    child: Semantics(
      identifier: 'launcher:${app.view}',
      button: true,
      label: app.label,
      selected: console.active?.view == app.view,
      excludeSemantics: true,
      onTap: () {
        console.open(app.view);
        console.refresh();
      },
      child: Tooltip(
        message: app.label,
        child: InkWell(
          key: ValueKey('launcher-${app.view}'),
          onTap: () {
            console.open(app.view);
            console.refresh();
          },
          borderRadius: BorderRadius.circular(7),
          child: Container(
            padding: EdgeInsets.symmetric(
              horizontal: compact ? 9 : 14,
              vertical: 5,
            ),
            decoration: BoxDecoration(
              color: console.active?.view == app.view
                  ? const Color(0xffdfeafb)
                  : null,
              borderRadius: BorderRadius.circular(7),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icons[app.view], size: 23, color: const Color(0xff436784)),
                if (!compact)
                  Text(app.label, style: const TextStyle(fontSize: 11)),
                Container(
                  margin: const EdgeInsets.only(top: 3),
                  width: 4,
                  height: 4,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: console.windows.any((w) => w.view == app.view)
                        ? const Color(0xff587b9a)
                        : Colors.transparent,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class ConsoleNativeWindow extends StatelessWidget {
  final NativeConsoleInteractor console;
  final ConsoleWindowModel window;
  final Size area;
  const ConsoleNativeWindow({
    super.key,
    required this.console,
    required this.window,
    required this.area,
  });
  @override
  Widget build(BuildContext context) {
    final w = window,
        compact = area.width < 720,
        full = compact || w.maximized,
        active = console.activeId == w.id;
    final width = full ? area.width : min(w.bounds.width, area.width),
        height = full ? area.height : min(w.bounds.height, area.height);
    final left = full
        ? 0.0
        : w.bounds.left.clamp(0, max(0, area.width - width)).toDouble();
    final top = full
        ? 0.0
        : w.bounds.top.clamp(0, max(0, area.height - height)).toDouble();
    return Positioned(
      left: left,
      top: top,
      width: width,
      height: height,
      child: Offstage(
        offstage: w.minimized,
        child: Semantics(
          container: true,
          explicitChildNodes: true,
          label: '${w.title} window',
          identifier: 'window:${w.id}',
          child: Material(
            elevation: active ? 12 : 3,
            shadowColor: const Color(0xff31516e),
            color: const Color(0xfff5f7fa),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(full ? 0 : 10),
              side: BorderSide(
                color: active
                    ? const Color(0xff7f9db8)
                    : const Color(0xffc0cfdd),
              ),
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(
              children: [
                titlebar(compact, active),
                Expanded(
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: ExcludeSemantics(
                          excluding: !active,
                          child: IgnorePointer(
                            ignoring: !active,
                            child: ConsoleViews(
                              key: ValueKey('view-${w.id}'),
                              console: console,
                              window: w,
                            ),
                          ),
                        ),
                      ),
                      if (!active)
                        Positioned.fill(
                          child: Semantics(
                            button: true,
                            label: 'Activate ${w.title}',
                            child: GestureDetector(
                              behavior: HitTestBehavior.opaque,
                              onTap: () {
                                console.open(w.view, w.entityId);
                                console.refresh();
                              },
                            ),
                          ),
                        ),
                      if (!full)
                        Positioned(
                          right: 0,
                          bottom: 0,
                          child: GestureDetector(
                            onPanUpdate: (d) =>
                                console.resize(w, d.delta, area),
                            child: const MouseRegion(
                              cursor: SystemMouseCursors.resizeDownRight,
                              child: SizedBox(
                                width: 20,
                                height: 20,
                                child: Icon(
                                  Icons.south_east,
                                  size: 12,
                                  color: Color(0xff6b849b),
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget windowControl(
    String action,
    String label,
    IconData icon,
    VoidCallback command,
  ) => Semantics(
    identifier: 'window.$action:${window.id}',
    button: true,
    label: '$label ${window.title}',
    excludeSemantics: true,
    onTap: command,
    child: IconButton(
      key: ValueKey('$action-${window.id}'),
      tooltip: '$label ${window.title}',
      onPressed: command,
      icon: Icon(icon, size: action == 'close' ? 18 : 17),
    ),
  );

  Widget titlebar(bool compact, bool active) {
    final w = window;
    return Container(
      height: 42,
      color: active ? Colors.white : const Color(0xffe7eef5),
      padding: const EdgeInsets.only(left: 12),
      child: Row(
        children: [
          Expanded(
            child: GestureDetector(
              onPanUpdate: compact
                  ? null
                  : (d) => console.move(w, d.delta, area),
              onDoubleTap: () => console.maximize(w),
              child: TextButton(
                onPressed: () {
                  console.open(w.view, w.entityId);
                  console.refresh();
                },
                style: TextButton.styleFrom(alignment: Alignment.centerLeft),
                child: Text(
                  w.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),
          ),
          windowControl(
            'minimize',
            'Minimize',
            Icons.remove,
            () => console.minimize(w),
          ),
          if (!compact)
            windowControl(
              'maximize',
              w.maximized ? 'Restore' : 'Maximize',
              w.maximized ? Icons.filter_none : Icons.crop_square,
              () => console.maximize(w),
            ),
          windowControl(
            'close',
            'Close',
            Icons.close,
            () => console.closeWindow(w),
          ),
        ],
      ),
    );
  }
}
