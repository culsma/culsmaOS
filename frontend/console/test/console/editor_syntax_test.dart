import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:syntax_highlight/syntax_highlight.dart';
import 'package:culsma_console/features/console/view/protocol_editor_view.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'existing TextMate grammar preserves text and distinguishes language scopes',
    (tester) async {
      Highlighter.addLanguage(
        'culsma',
        await rootBundle.loadString('assets/syntax/culsma.tmLanguage.json'),
      );
      final theme = await HighlighterTheme.loadLightTheme();
      final controller = CulsmaEditingController()
        ..setHighlighter(Highlighter(language: 'culsma', theme: theme));
      const source =
          '// Preparation\nlet source=tube(capacity=200uL,load=[content(kind=formulation,type=buffer,code="B"):100uL]);\nreturn source;';
      controller.text = source;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TextField(controller: controller, maxLines: null),
          ),
        ),
      );
      final context = tester.element(find.byType(TextField));
      final span = controller.buildTextSpan(
        context: context,
        style: const TextStyle(),
        withComposing: false,
      );
      expect(span.toPlainText(), source);
      final colors = <Color>{};
      void collect(InlineSpan value) {
        if (value is TextSpan) {
          if (value.style?.color != null) colors.add(value.style!.color!);
          for (final child in value.children ?? <InlineSpan>[]) collect(child);
        }
      }

      collect(span);
      expect(colors.length, greaterThanOrEqualTo(3));
      controller.value = const TextEditingValue(
        text: 'let sample',
        composing: TextRange(start: 4, end: 10),
      );
      expect(
        controller
            .buildTextSpan(
              context: context,
              style: const TextStyle(),
              withComposing: true,
            )
            .toPlainText(),
        'let sample',
      );
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );
}
