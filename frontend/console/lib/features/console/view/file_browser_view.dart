import 'package:flutter/material.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'protocol_name_dialog.dart';
import '../interactor/drop_interactor.dart';
import '../interactor/console_interactor.dart';
import '../interactor/file_browser_interactor.dart';

class NativeFileBrowserView extends StatelessWidget {
  final NativeConsoleInteractor console;
  const NativeFileBrowserView({super.key, required this.console});
  NativeFileBrowserInteractor get browser => console.files;
  String size(dynamic value) {
    if (value is! num) return '';
    if (value < 1024) return '$value B';
    if (value < 1024 * 1024) return '${(value / 1024).toStringAsFixed(1)} KB';
    return '${(value / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  String modified(dynamic ns) {
    if (ns is! num) return '';
    final d = DateTime.fromMicrosecondsSinceEpoch(ns ~/ 1000).toLocal();
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }

  IconData icon(Map row) => switch (row['kind']) {
    'directory' => Icons.folder_outlined,
    'link' => Icons.link,
    'special' => Icons.block,
    _ =>
      row['program'] != null
          ? Icons.science_outlined
          : Icons.insert_drive_file_outlined,
  };
  Future<void> open(Map<String, dynamic> row) async {
    if (row['kind'] == 'directory') {
      await browser.navigate(browser.root, row['path']);
      return;
    }
    final program = row['program'];
    if (program != null)
      await console.launch(
        program['program_id'],
        sourceScope: program['source_scope'],
      );
    else
      await browser.select(row);
  }

  Future<void> createProtocol(BuildContext context) async {
    final relative = await promptProtocolName(
      context,
      'New protocol',
      'new-protocol.culs',
    );
    if (relative == null) return;
    final directory = browser.experimentDirectory;
    final path = directory.isEmpty ? relative : '$directory/$relative';
    if (await console.editor.create(
      path,
      '// Describe your experiment here.\n',
    )) {
      await browser.navigate('programs', directory);
      console.openEditor(path);
    } else {
      browser.error = console.editor.document(path).error;
      browser.changed();
    }
  }

  void editRow(Map row) {
    final program = row['program'];
    if (program?['source_scope'] == 'programs')
      console.openEditor(program['program_id']);
  }

  Future<void> menu(BuildContext context, Map row, Offset position) async {
    if (row['program']?['source_scope'] != 'programs') return;
    final choice = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx,
        position.dy,
        position.dx,
        position.dy,
      ),
      items: [
        const PopupMenuItem(value: 'edit', child: Text('Edit')),
        const PopupMenuItem(value: 'run', child: Text('Run')),
      ],
    );
    if (choice == 'edit') editRow(row);
    if (choice == 'run') await open(Map<String, dynamic>.from(row));
  }

  Future<void> drop(DropDetails details) async {
    if (browser.receiving) return;
    final directory = browser.experimentDirectory;
    browser.receiving = true;
    browser.error = null;
    browser.changed();
    try {
      final entries = await NativeDropInteractor().collect(details.items);
      browser.receiving = false;
      await browser.receive(entries, directory: directory);
    } catch (e) {
      browser.error = 'Files could not be copied: $e';
    } finally {
      browser.receiving = false;
      browser.changed();
    }
  }

  Widget toolbar(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          IconButton(
            key: const Key('files-back'),
            tooltip: 'Back',
            onPressed: browser.loading || !browser.canBack
                ? null
                : browser.back,
            icon: const Icon(Icons.arrow_back, semanticLabel: 'Back'),
          ),
          IconButton(
            key: const Key('files-forward'),
            tooltip: 'Forward',
            onPressed: browser.loading || !browser.canForward
                ? null
                : browser.forward,
            icon: const Icon(Icons.arrow_forward, semanticLabel: 'Forward'),
          ),
          IconButton(
            key: const Key('files-up'),
            tooltip: 'Up one folder',
            onPressed: browser.loading || browser.path.isEmpty
                ? null
                : browser.up,
            icon: const Icon(
              Icons.arrow_upward,
              semanticLabel: 'Up one folder',
            ),
          ),
          IconButton(
            key: const Key('files-refresh'),
            tooltip: 'Refresh folder',
            onPressed: browser.loading ? null : browser.refresh,
            icon: const Icon(Icons.refresh, semanticLabel: 'Refresh folder'),
          ),
          const SizedBox(width: 8),
          const Expanded(
            child: Text(
              'Files',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
          ),
          IconButton(
            key: const Key('files-new-protocol'),
            tooltip: 'New protocol',
            onPressed: () => createProtocol(context),
            icon: const Icon(Icons.note_add_outlined),
          ),
        ],
      ),
      Wrap(
        spacing: 8,
        children: [
          if (browser.selected?['program']?['source_scope'] == 'programs')
            TextButton.icon(
              key: const Key('files-edit'),
              label: const Text('Edit'),
              onPressed: () => editRow(browser.selected!),
              icon: const Icon(Icons.edit_outlined),
            ),
          if (browser.selected?['program'] != null)
            TextButton.icon(
              onPressed: console.working || console.pendingStart != null
                  ? null
                  : () => open(browser.selected!),
              icon: const Icon(Icons.play_arrow),
              label: const Text('Run'),
            ),
        ],
      ),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            TextButton(
              onPressed: () => browser.navigate(browser.root, ''),
              child: Text(browser.rootLabel),
            ),
            for (
              var i = 0;
              i < browser.path.split('/').where((s) => s.isNotEmpty).length;
              i++
            ) ...[
              const Icon(Icons.chevron_right, size: 16),
              TextButton(
                onPressed: () => browser.navigate(
                  browser.root,
                  browser.path.split('/').take(i + 1).join('/'),
                ),
                child: Text(browser.breadcrumbLabel(i)),
              ),
            ],
          ],
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
        child: SelectableText(
          browser.absolutePath,
          style: const TextStyle(fontSize: 12, color: Color(0xff62798c)),
        ),
      ),
    ],
  );
  List<Widget> tree(String root, String path, int depth) => [
    for (final row in browser.folders[browser.key(root, path)] ?? []) ...[
      Row(
        children: [
          SizedBox(width: 8 + depth * 12.0),
          IconButton(
            visualDensity: VisualDensity.compact,
            tooltip: 'Expand ${row['name']}',
            onPressed: () => browser.toggleFolder(root, row['path']),
            icon: Icon(
              browser.expanded.contains(browser.key(root, row['path']))
                  ? Icons.expand_more
                  : Icons.chevron_right,
              size: 16,
              semanticLabel: 'Expand ${row['name']}',
            ),
          ),
          Expanded(
            child: InkWell(
              onTap: () => browser.navigate(root, row['path']),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Text(
                  row['name'],
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),
          ),
        ],
      ),
      if (depth < 12 &&
          browser.expanded.contains(browser.key(root, row['path'])))
        ...tree(root, row['path'], depth + 1),
    ],
  ];
  Widget sidebar() => Material(
    color: const Color(0xfff2f5f8),
    child: ListView(
      padding: const EdgeInsets.symmetric(vertical: 12),
      children: [
        const Padding(
          padding: EdgeInsets.all(12),
          child: Text(
            'Locations',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
        for (final location in browser.roots) ...[
          ListTile(
            dense: true,
            key: ValueKey('files-root-${location['id']}'),
            selected: browser.root == location['id'],
            leading: Icon(
              location['id'] == 'installation'
                  ? Icons.computer
                  : Icons.folder_special_outlined,
            ),
            title: Text(location['label']),
            enabled: location['available'] == true,
            onTap: () => browser.navigate(location['id'], ''),
          ),
          if (browser.expanded.contains(browser.key(location['id'], '')))
            ...tree(location['id'], '', 0),
        ],
      ],
    ),
  );
  Widget details(bool wide) {
    final row = browser.selected;
    if (row == null) return const SizedBox.shrink();
    return Container(
      height: 185,
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: Color(0xffd8e1ea))),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon(row), size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  row['name'],
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              Text(size(row['size'])),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: browser.previewLoading
                ? const Center(child: CircularProgressIndicator())
                : browser.preview?['preview'] == 'text'
                ? SingleChildScrollView(
                    child: SelectableText(
                      browser.preview!['content'],
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 12,
                      ),
                    ),
                  )
                : Text(
                    row['kind'] == 'directory'
                        ? 'Double-click to open this folder.'
                        : row['kind'] != 'file'
                        ? 'Links and special files cannot be opened.'
                        : 'Binary file. Text preview is unavailable.',
                  ),
          ),
          if (browser.preview?['truncated'] == true)
            const Text(
              'Preview limited to 64 KB.',
              style: TextStyle(fontSize: 11),
            ),
        ],
      ),
    );
  }

  Widget content(BuildContext context, bool wide) => Column(
    children: [
      Container(
        color: const Color(0xfff7f9fb),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            const Expanded(flex: 4, child: Text('Name')),
            if (wide) const Expanded(flex: 2, child: Text('Modified')),
            if (wide) const Expanded(child: Text('Type')),
            const SizedBox(
              width: 80,
              child: Text('Size', textAlign: TextAlign.right),
            ),
          ],
        ),
      ),
      Expanded(
        child: browser.loading && browser.entries.isEmpty
            ? const Center(child: CircularProgressIndicator())
            : browser.entries.isEmpty
            ? const Center(child: Text('This folder is empty.'))
            : ListView.builder(
                key: ValueKey('files-list-${browser.root}-${browser.path}'),
                itemCount:
                    browser.entries.length +
                    (browser.nextOffset == null ? 0 : 1),
                itemBuilder: (context, i) {
                  if (i == browser.entries.length)
                    return TextButton(
                      onPressed: browser.loading ? null : browser.more,
                      child: const Text('Show more files'),
                    );
                  final row = browser.entries[i],
                      selected = browser.selected?['path'] == row['path'];
                  return Semantics(
                    label: '${row['kind']}: ${row['name']}',
                    button: true,
                    selected: selected,
                    child: Material(
                      color: selected
                          ? const Color(0xffdceaf9)
                          : Colors.transparent,
                      child: InkWell(
                        key: ValueKey(
                          'file-entry-${browser.root}-${row['path']}',
                        ),
                        onTap: () => browser.select(row),
                        onSecondaryTapUp: (details) =>
                            menu(context, row, details.globalPosition),
                        onDoubleTap: row['openable'] == true
                            ? () => open(row)
                            : null,
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 12,
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                flex: 4,
                                child: Row(
                                  children: [
                                    Icon(
                                      icon(row),
                                      size: 22,
                                      color: const Color(0xff365d83),
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: Text(
                                        row['name'],
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (wide)
                                Expanded(
                                  flex: 2,
                                  child: Text(
                                    modified(row['modified_ns']),
                                    style: const TextStyle(fontSize: 12),
                                  ),
                                ),
                              if (wide)
                                Expanded(
                                  child: Text(
                                    row['kind'] == 'directory'
                                        ? 'Folder'
                                        : row['extension']
                                                  ?.toString()
                                                  .isNotEmpty ==
                                              true
                                        ? row['extension']
                                              .toString()
                                              .substring(1)
                                              .toUpperCase()
                                        : row['kind'],
                                    style: const TextStyle(fontSize: 12),
                                  ),
                                ),
                              SizedBox(
                                width: 80,
                                child: Text(
                                  size(row['size']),
                                  textAlign: TextAlign.right,
                                  style: const TextStyle(fontSize: 12),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
      ),
      details(wide),
      Padding(
        padding: const EdgeInsets.all(10),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(
            '${browser.total} items · Double-click folders to open, .culs files to check before running',
            style: const TextStyle(fontSize: 11, color: Color(0xff62798c)),
          ),
        ),
      ),
    ],
  );
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final wide = constraints.maxWidth >= 700;
      final body = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          toolbar(context),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Text(
              'Drop files or folders here to copy into Experiments. Single-click to preview; Edit to change; double-click to run.',
              style: TextStyle(fontSize: 12),
            ),
          ),
          if (browser.receiving) const LinearProgressIndicator(),
          if (browser.notice != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(browser.notice!),
            ),
          if (console.pendingStart != null)
            MaterialBanner(
              content: const Text(
                'An unresolved run request is retained. No automatic repeat.',
              ),
              actions: [
                TextButton(
                  onPressed: console.busy ? null : console.checkPendingStart,
                  child: const Text('Check retained run request'),
                ),
              ],
            ),
          if (browser.error != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                browser.error!,
                style: const TextStyle(color: Color(0xff924e25)),
              ),
            ),
          if (browser.loading) const LinearProgressIndicator(minHeight: 2),
          if (!wide)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: DropdownButton<String>(
                value: browser.roots.any((r) => r['id'] == browser.root)
                    ? browser.root
                    : null,
                isExpanded: true,
                hint: const Text('Location'),
                items: [
                  for (final row in browser.roots)
                    DropdownMenuItem(
                      value: row['id'],
                      enabled: row['available'] == true,
                      child: Text(row['label']),
                    ),
                ],
                onChanged: (id) {
                  if (id != null) browser.navigate(id, '');
                },
              ),
            ),
          Expanded(
            child: Row(
              children: [
                if (wide) SizedBox(width: 200, child: sidebar()),
                Expanded(child: content(context, wide)),
              ],
            ),
          ),
        ],
      );
      return NativeDropInteractor.available
          ? DropTarget(
              key: const Key('experiment-file-drop'),
              acceptedKinds: const {DropItemKind.file, DropItemKind.directory},
              onDrop: drop,
              child: body,
            )
          : body;
    },
  );
}
