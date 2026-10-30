import 'dart:convert';
import 'dart:io';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/drop_interactor.dart';

void registerDropInteractorTests() {
  late Directory root;
  setUp(() async {
    root = await Directory.systemTemp.createTemp('culsma-drop-unit-');
  });
  tearDown(() async {
    await root.delete(recursive: true);
  });
  test(
    'real provider copies nested files and binary companions, skips hidden files, preserves originals',
    () async {
      final project = await Directory('${root.path}/assay µ').create();
      await Directory('${project.path}/nested').create();
      final source = File('${project.path}/nested/main.culs');
      await source.writeAsString('let sample=tube(capacity=200uL);');
      await File('${project.path}/data.bin').writeAsBytes([0, 128, 255]);
      await File('${project.path}/.hidden').writeAsString('private');
      final entries = await NativeDropInteractor().collect([
        DropDirectoryItem(
          directory: XDirectory.fileSystem(path: project.path),
          name: 'assay µ',
        ),
      ]);
      expect(entries.map((e) => e['path']).toSet(), {
        'assay µ/nested/main.culs',
        'assay µ/data.bin',
      });
      expect(
        base64Decode(
          entries.firstWhere((e) => e['path']!.endsWith('data.bin'))['data']!,
        ),
        [0, 128, 255],
      );
      expect(await source.readAsString(), contains('200uL'));
      expect(await File('${project.path}/.hidden').exists(), isTrue);
    },
  );
  test('empty or hidden-only providers are rejected', () async {
    await expectLater(
      NativeDropInteractor().collect([]),
      throwsFormatException,
    );
    final file = await File('${root.path}/.hidden').writeAsString('hidden');
    await expectLater(
      NativeDropInteractor().collect([DropFileItem.fromPath(file.path)]),
      throwsFormatException,
    );
  });
  test('native symlinks are rejected without reading their target', () async {
    final outside = await File(
      '${root.path}/outside.culs',
    ).writeAsString('outside');
    final link = await Link('${root.path}/link.culs').create(outside.path);
    await expectLater(
      NativeDropInteractor().collect([DropFileItem.fromPath(link.path)]),
      throwsFormatException,
    );
    expect(await outside.readAsString(), 'outside');
  });
  test(
    'file count and total byte limits are enforced over actual provider files',
    () async {
      final folder = await Directory('${root.path}/many').create();
      for (var i = 0; i < 201; i++) {
        await File('${folder.path}/$i.culs').writeAsString('x');
      }
      await expectLater(
        NativeDropInteractor().collect([
          DropDirectoryItem(
            directory: XDirectory.fileSystem(path: folder.path),
            name: 'many',
          ),
        ]),
        throwsFormatException,
      );
      final large = await File(
        '${root.path}/large.bin',
      ).writeAsBytes(List.filled(4000001, 0));
      await expectLater(
        NativeDropInteractor().collect([DropFileItem.fromPath(large.path)]),
        throwsFormatException,
      );
    },
  );
}
