import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/run_review_interactor.dart';
import 'package:culsma_console/features/console/view/preparation_layout.dart';
import 'package:culsma_console/features/console/view/recorded_deck.dart';
import 'package:culsma_console/features/console/view/labware_symbol.dart';
import 'package:culsma_console/features/console/model/console_model.dart';

void main() {
  final fixture = jsonDecode(
    File(
      'test/console/fixtures/standard_dilution_visual_preparation.json',
    ).readAsStringSync(),
  );
  final review = NativeRunReviewInteractor();
  final plan = fixture['preparation']['plan'] as Map;
  setUpAll(() async {
    await (FontLoader(
      'Console',
    )..addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  test(
    'real driver loading plan retains readable types and exact layout identities',
    () {
      final items = review.loadingItems(plan);
      expect(items.map((i) => i['number']), ['P1', 'P2', 'P3', 'P4']);
      expect(items.map((i) => i['kind']), [
        'reservoir',
        'reservoir',
        'plate',
        'tips',
      ]);
      expect(items.last['title'], 'Filter tip rack');
      expect(items.last['id'], 'HTF_B4_TEST');
      expect(items.last['carrier_address'], 'Carrier B · Site 4');
      expect(items.first['carrier_address'], 'Carrier F · Site 2');
      expect(items[2]['carrier_address'], 'Carrier E · Site 4');
      expect(items.first['model_label'], contains('60 mL reagent vessel'));
      expect(items[2]['title'], 'Destination plate');
      expect(items[2]['placement']['track'], '29');
    },
  );
  test('carrier letters never become physical rail numbers', () {
    expect(RecordedDeck.carrierLabel(0), 'A');
    expect(RecordedDeck.carrierLabel(11), 'L');
    expect(RecordedDeck.carrierLabel(25), 'Z');
    expect(RecordedDeck.carrierLabel(26), 'AA');
    expect(() => RecordedDeck.carrierLabel(-1), throwsRangeError);
    expect(
      review.carrierAddress({}, {'track': '10', 'site': '4'}),
      'Track 10 · Position 4',
    );
  });
  for (final width in [1280.0, 390.0]) {
    testWidgets(
      'graphical loading plan golden and persistent scrolling $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        Widget screen() => MaterialApp(
          theme: ThemeData(fontFamily: 'Console'),
          home: RepaintBoundary(
            key: const Key('preparation-visual'),
            child: Scaffold(
              body: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: NativePreparationLayout(plan: plan, review: review),
              ),
            ),
          ),
        );
        await tester.pumpWidget(screen());
        await tester.pumpAndSettle();
        final state = tester.state<NativePreparationLayoutState>(
          find.byType(NativePreparationLayout),
        );
        final board = tester.widget<RecordedDeckBoard>(
          find.byType(RecordedDeckBoard),
        );
        expect(board.annotations.keys.toSet(), {
          'STANDARD_T36_SITE2',
          'WATER_T36_REAR_SITE1',
          'DWP96_E4',
          'HTF_B4_TEST',
        });
        expect(find.byType(NativeLabwareSymbol), findsWidgets);
        state.scroll.jumpTo(280);
        await tester.pumpAndSettle();
        final offset = state.scroll.offset;
        await tester.pumpWidget(screen());
        await tester.pumpAndSettle();
        expect(state.scroll.offset, offset);
        expect(tester.takeException(), isNull);
        await expectLater(
          find.byKey(const Key('preparation-visual')),
          matchesGoldenFile(
            '../goldens/native-loading-plan-${width.toInt()}.png',
          ),
        );
        final card = find.byKey(const ValueKey('loading-card:DWP96_E4'));
        await tester.ensureVisible(card);
        await tester.tap(card);
        await tester.pumpAndSettle();
        expect(state.selected, 'DWP96_E4');
        expect(state.scroll.offset, greaterThan(280));
        expect(tester.takeException(), isNull);
      },
    );
  }
}
