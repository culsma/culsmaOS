class ProtocolDocument {
  final String path;
  String text = '', savedText = '', revision = '';
  String? error;
  Map<String, dynamic>? inspection;
  bool busy = false, loaded = false, externalChange = false;
  bool get dirty => text != savedText;
  ProtocolDocument(this.path);
}
