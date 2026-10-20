import 'dart:convert';

class LayoutData {
  static dynamic at(Map<String, dynamic> root, List<dynamic> path) {
    dynamic value = root;
    for (final part in path) {
      value = value is Map ? value[part] : null;
    }
    return value;
  }

  static Map<String, dynamic> copy(Map<String, dynamic> value) =>
      jsonDecode(jsonEncode(value)) as Map<String, dynamic>;
  static String canonical(dynamic value) {
    if (value is Map) {
      final keys = value.keys.map((key) => key.toString()).toList()..sort();
      return '{${keys.map((key) => '${jsonEncode(key)}:${canonical(value[key])}').join(',')}}';
    }
    if (value is List) return '[${value.map(canonical).join(',')}]';
    return jsonEncode(value);
  }
}

class LayoutPosition {
  final String id, label;
  final double x, y, width, height;
  final Set<String> accepts;
  final String? fixedLabel;
  LayoutPosition.fromJson(Map<String, dynamic> raw)
    : id = raw['id'],
      label = raw['label'],
      x = (raw['x'] as num).toDouble(),
      y = (raw['y'] as num).toDouble(),
      width = (raw['width'] as num).toDouble(),
      height = (raw['height'] as num).toDouble(),
      accepts = Set<String>.from(raw['accepts']),
      fixedLabel = raw['fixed_label'];
}

class LayoutCollection {
  final String id, category, modelField, positionField;
  final List<String> path;
  final bool keyed, editable;
  final String? parentField;
  LayoutCollection.fromJson(Map<String, dynamic> raw)
    : id = raw['id'],
      category = raw['category'],
      path = List<String>.from(raw['path']),
      modelField = raw['model_field'],
      positionField = raw['position_field'],
      parentField = raw['parent_field'],
      keyed = raw['keyed'],
      editable = raw['editable'];
}

class LayoutItem {
  final LayoutCollection collection;
  final String name, model;
  final String? position, parent;
  final Map<String, dynamic> spec;
  LayoutItem(this.collection, this.name, this.spec)
    : model = spec[collection.modelField] as String,
      position = spec[collection.positionField] as String?,
      parent = collection.parentField == null
          ? null
          : spec[collection.parentField] as String?;
  String get id => '${collection.id}/$name';
}

class LayoutDefinition {
  final Map<String, dynamic> raw;
  final Map<String, dynamic> variant;
  late final List<LayoutPosition> positions;
  late final List<LayoutCollection> collections;
  String get id => variant['id'];
  String get label => variant['label'];
  double get width => (variant['width'] as num).toDouble();
  double get height => (variant['height'] as num).toDouble();

  LayoutDefinition(
    Map<String, dynamic> metadata,
    Map<String, dynamic> configuration,
  ) : raw = LayoutData.copy(metadata),
      variant = select(metadata, configuration) {
    if (raw['schema'] != 'culsma_layout_v1' || raw['revision'] != 1) {
      throw const FormatException('LAYOUT_SCHEMA_UNSUPPORTED');
    }
    positions = (variant['positions'] as List)
        .map((p) => LayoutPosition.fromJson(p))
        .toList();
    collections = (raw['collections'] as List)
        .map((c) => LayoutCollection.fromJson(c))
        .toList();
    if (!width.isFinite ||
        !height.isFinite ||
        width <= 0 ||
        height <= 0 ||
        positions.isEmpty ||
        positions.map((p) => p.id).toSet().length != positions.length ||
        positions.any(
          (p) =>
              !p.x.isFinite ||
              !p.y.isFinite ||
              !p.width.isFinite ||
              !p.height.isFinite ||
              p.x < 0 ||
              p.y < 0 ||
              p.width <= 0 ||
              p.height <= 0 ||
              p.x + p.width > width ||
              p.y + p.height > height,
        )) {
      throw const FormatException('LAYOUT_GEOMETRY_INVALID');
    }
  }

  static Map<String, dynamic> select(
    Map<String, dynamic> metadata,
    Map<String, dynamic> configuration,
  ) {
    final selector = LayoutData.at(
      configuration,
      metadata['selector_path'] as List,
    );
    final value = metadata['variants']?[selector];
    if (value is! Map<String, dynamic>)
      throw const FormatException('LAYOUT_DEFINITION_UNAVAILABLE');
    return LayoutData.copy(value);
  }

  List<LayoutItem> items(Map<String, dynamic> configuration) {
    final result = <LayoutItem>[];
    for (final collection in collections) {
      final values = LayoutData.at(configuration, collection.path);
      if (values is! Map<String, dynamic>) continue;
      if (collection.keyed) {
        for (final entry in values.entries) {
          result.add(
            LayoutItem(
              collection,
              entry.key,
              Map<String, dynamic>.from(entry.value),
            ),
          );
        }
      } else {
        result.add(
          LayoutItem(
            collection,
            collection.id,
            Map<String, dynamic>.from(values),
          ),
        );
      }
    }
    return result;
  }

  String modelLabel(String model) {
    for (final entry in raw['catalogue'] as List) {
      if (entry['id'] == model) return entry['label'];
    }
    return model; // Preserve installed definitions absent from the curated catalogue.
  }

  Map<String, dynamic>? catalogueEntry(String model) =>
      (raw['catalogue'] as List)
          .cast<Map<String, dynamic>>()
          .where((entry) => entry['id'] == model)
          .firstOrNull;

  Set<String> footprintAt(String model, String? position) {
    final entry = catalogueEntry(model);
    if (entry?['footprints']?[position] != null) {
      return Set<String>.from(entry!['footprints'][position]);
    }
    return position == null ? {} : {position};
  }

  Set<String> footprint(LayoutItem item) =>
      footprintAt(item.model, item.position);

  bool fits(
    Map<String, dynamic> configuration,
    String model,
    String target,
    String category, {
    String? except,
  }) {
    final footprint = footprintAt(model, target);
    final occupied = items(configuration)
        .where((i) => i.parent == null && i.id != except)
        .expand((i) => this.footprint(i))
        .toSet();
    return footprint.isNotEmpty &&
        footprint.every(
          (id) =>
              positions.any((p) => p.id == id && p.accepts.contains(category)),
        ) &&
        footprint.intersection(occupied).isEmpty;
  }

  List<String> sites(LayoutItem parent) =>
      List<String>.from(catalogueEntry(parent.model)?['sites'] ?? []);

  Map<String, dynamic> placeChild(
    Map<String, dynamic> configuration,
    LayoutCollection collection,
    String name,
    String model,
    LayoutItem parent,
    String site,
  ) {
    final entry = catalogueEntry(model);
    if (!collection.editable ||
        !collection.keyed ||
        collection.parentField == null ||
        !RegExp(r'^[A-Za-z][A-Za-z0-9_-]{0,63}$').hasMatch(name) ||
        entry?['category'] != collection.category ||
        !(entry?['parents'] as List? ?? []).contains(parent.model) ||
        !sites(parent).contains(site) ||
        items(configuration).any(
          (i) =>
              i.collection.id == collection.id && i.name == name ||
              i.parent == parent.name && i.position == site,
        )) {
      throw const FormatException('LAYOUT_SITE_REJECTED');
    }
    final updated = LayoutData.copy(configuration);
    final container =
        LayoutData.at(updated, collection.path) as Map<String, dynamic>;
    container[name] = {
      collection.modelField: model,
      collection.positionField: site,
      collection.parentField!: parent.name,
    };
    return updated;
  }

  LayoutItem? occupant(Map<String, dynamic> configuration, String position) {
    for (final item in items(configuration)) {
      if (item.parent == null && footprint(item).contains(position))
        return item;
    }
    return null;
  }

  List<Map<String, dynamic>> catalogue(
    LayoutCollection collection,
    Map<String, dynamic> configuration,
  ) {
    return (raw['catalogue'] as List).cast<Map<String, dynamic>>().where((
      entry,
    ) {
      if (entry['category'] != collection.category) return false;
      final when = entry['when'] as Map<String, dynamic>? ?? {};
      return when.entries.every(
        (e) => (e.value as List).contains(configuration[e.key]),
      );
    }).toList();
  }

  List<LayoutPosition> destinations(
    Map<String, dynamic> configuration,
    LayoutItem item,
  ) {
    return positions
        .where(
          (p) => fits(
            configuration,
            item.model,
            p.id,
            item.collection.category,
            except: item.id,
          ),
        )
        .toList();
  }

  Map<String, dynamic> move(
    Map<String, dynamic> configuration,
    LayoutItem item,
    String target,
  ) {
    if (!item.collection.editable ||
        item.parent != null ||
        !destinations(configuration, item).any((p) => p.id == target)) {
      throw const FormatException('LAYOUT_MOVE_REJECTED');
    }
    final updated = LayoutData.copy(configuration);
    final values =
        LayoutData.at(updated, item.collection.path) as Map<String, dynamic>;
    final spec = item.collection.keyed
        ? values[item.name] as Map<String, dynamic>
        : values;
    spec[item.collection.positionField] = target;
    return updated;
  }

  Map<String, dynamic> add(
    Map<String, dynamic> configuration,
    LayoutCollection collection,
    String name,
    String model,
    String target,
  ) {
    if (!collection.editable ||
        !collection.keyed ||
        !RegExp(r'^[A-Za-z][A-Za-z0-9_-]{0,63}$').hasMatch(name) ||
        !catalogue(collection, configuration).any((e) => e['id'] == model) ||
        !positions.any(
          (p) => p.id == target && p.accepts.contains(collection.category),
        ) ||
        !fits(configuration, model, target, collection.category)) {
      throw const FormatException('LAYOUT_ADD_REJECTED');
    }
    final updated = LayoutData.copy(configuration);
    final parent =
        LayoutData.at(
              updated,
              collection.path.take(collection.path.length - 1).toList(),
            )
            as Map<String, dynamic>;
    parent[collection.path.last] ??= <String, dynamic>{};
    final values = parent[collection.path.last] as Map<String, dynamic>;
    if (values.containsKey(name))
      throw const FormatException('LAYOUT_NAME_EXISTS');
    values[name] = {
      collection.modelField: model,
      collection.positionField: target,
    };
    return updated;
  }
}
