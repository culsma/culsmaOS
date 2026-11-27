import 'dart:convert';
import 'dart:io';
import 'dart:ui' show PointerDeviceKind;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/run_review_interactor.dart';
import 'package:culsma_console/features/console/view/preparation_layout.dart';
import 'package:culsma_console/features/console/view/recorded_deck.dart';
import 'package:culsma_console/features/console/view/labware_symbol.dart';
import 'package:culsma_console/features/console/model/console_model.dart';
import 'package:culsma_console/features/console/interactor/setup_interactor.dart';
import 'package:culsma_console/features/console/view/setup_panel.dart';
import 'fixture.dart';

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
  test('loading tooltips include address, quantity and empty destination', () {
    final items = review.loadingItems(plan);
    expect(
      review.loadingInstructions(items.first),
      contains('Carrier F · Site 2'),
    );
    expect(review.loadingInstructions(items.first), contains('load 1000 µL'));
    expect(review.loadingInstructions(items[2]), contains('leave empty'));
    expect(review.loadingInstructions(items.last), contains('P4'));
  });
  test('installed fixture gets its own labelled loading annotation', () {
    final items = review.loadingItems({
      ...plan,
      'installed_fixtures': [
        {
          'id': 'DWP96_E3',
          'kind': 'fixture',
          'label': 'Ariumlab Levitation X-96PLT',
          'model': 'Ariumlab_X_96PLT',
          'placement': {
            'carrier': 'CAR_HHS_3DWP_0001',
            'track': '29',
            'site': '3',
          },
          'instructions': 'Confirm the support is installed.',
        },
      ],
    });
    expect(items.last['id'], 'DWP96_E3');
    expect(items.last['carrier_address'], 'Carrier E · Site 3');
    expect(items.last['number'], 'P5');
    expect(review.loadingInstructions(items.last), contains('Confirm the support'));
  });
  testWidgets(
    'active confirmation panel retains highlights and numbered empty sites',
    (tester) async {
      tester.view.physicalSize = const Size(1920, 1520);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final setup = NativeSetupInteractor(NativeConsoleFixtureApi(), null);
      setup.plans['test'] = {
        ...Map<String, dynamic>.from(plan),
        'phase': 'loading',
        'fingerprint': 'a' * 64,
      };
      await tester.pumpWidget(
        RepaintBoundary(
          key: const Key('loading-confirmation-visual'),
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: ThemeData(fontFamily: 'Console'),
            home: Scaffold(
              body: SingleChildScrollView(
                child: NativeSetupPanel(
                  controller: setup,
                  run: {'run_id': 'test', 'status': 'awaiting_setup'},
                ),
              ),
            ),
          ),
        ),
      );
      final board = tester.widget<RecordedDeckBoard>(
        find.byType(RecordedDeckBoard),
      );
      expect(board.annotations.length, 4);
      expect(
        find.text(
          'Not submitted for execution. Confirm loading to submit and run.',
        ),
        findsOneWidget,
      );
      final carrier = board.deck.carriers.firstWhere(
        (c) => c['id'] == 'PREVIEW_T36_5R60_SUBSTITUTE',
      );
      expect(carrier['sites'], ['1', '2', '3', '4', '5']);
      final first = find.byKey(
        const ValueKey('site-label:PREVIEW_T36_5R60_SUBSTITUTE/1'),
      );
      final fourth = find.byKey(
        const ValueKey('site-label:PREVIEW_T36_5R60_SUBSTITUTE/4'),
      );
      expect(
        tester.getTopLeft(first).dy,
        lessThan(tester.getTopLeft(fourth).dy),
      );
      expect(
        find.byKey(const ValueKey('site-label:PREVIEW_T36_5R60_SUBSTITUTE/3')),
        findsOneWidget,
      );
      expect(
        board.annotations['WATER_T36_REAR_SITE1']!['instructions'],
        contains('load 1000 µL'),
      );
      await tester.pumpAndSettle();
      final surface = find.byKey(const Key('loading-confirmation-visual'));
      await expectLater(
        surface,
        matchesGoldenFile('../goldens/loading-confirmation-overview.png'),
      );

      tester.view.physicalSize = const Size(1280, 1100);
      await tester.pumpAndSettle();
      board.scrollController!.jumpTo(460);
      await tester.pumpAndSettle();
      final water = find.byKey(board.keys['WATER_T36_REAR_SITE1']!);
      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      await mouse.addPointer(location: const Offset(5, 5));
      await mouse.moveTo(tester.getCenter(water));
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();
      final instructions =
          board.annotations['WATER_T36_REAR_SITE1']!['instructions']!;
      expect(find.text(instructions), findsOneWidget);
      // Capture the app surface so the tooltip overlay is included.
      await expectLater(
        surface,
        matchesGoldenFile('../goldens/loading-confirmation-hover.png'),
      );
      await mouse.removePointer();
      await tester.pumpAndSettle();

      await tester.tap(water);
      await tester.pumpAndSettle();
      final callout = find.byKey(
        const ValueKey('selected-loading-instructions'),
      );
      expect(
        find.descendant(of: callout, matching: find.text(instructions)),
        findsOneWidget,
      );
      await expectLater(
        surface,
        matchesGoldenFile('../goldens/loading-confirmation-selected.png'),
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      setup.dispose();
    },
  );
  testWidgets('physical D and E sites remain whole with selectable contents', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1800, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final before = jsonEncode(plan['layout']);
    final deck = RecordedDeck.fromLayout({
      'status': 'available',
      'layout': plan['layout'],
    })!;
    final keys = <String, GlobalKey>{};
    String? selected;
    final board = RecordedDeckBoard(
      deck: deck,
      keys: keys,
      onItem: (item) => selected = item['id'],
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(fontFamily: 'Console'),
        home: Scaffold(
          body: RepaintBoundary(
            key: const Key('whole-sites'),
            child: ColoredBox(color: Colors.white, child: board),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(deck.carriers.take(5).map((c) => (c['sites'] as List).length), [
      5,
      5,
      5,
      4,
      4,
    ]);
    for (final carrier in deck.carriers.skip(3).take(2)) {
      for (final site in carrier['sites']) {
        final slot = find.byKey(
          ValueKey('occupied-site:${carrier['id']}/$site'),
        );
        expect(slot, findsOneWidget);
        // Only the physical site draws a rectangle; its contents do not.
        expect(
          find.descendant(of: slot, matching: find.byType(Container)),
          findsNothing,
        );
      }
    }
    for (final id in ['DWP96_Lid_D1', 'DWP96_D1', 'DWP96_E4']) {
      await tester.tap(find.byKey(keys[id]!));
      expect(selected, id);
    }
    expect(jsonEncode(plan['layout']), before);
    await tester.pumpAndSettle();
    await expectLater(
      find.byKey(const Key('whole-sites')),
      matchesGoldenFile('../goldens/physical-deck-whole-sites.png'),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'occupiedSite and siteItem retain highlight and object callbacks',
    (tester) async {
      final deck = RecordedDeck.fromLayout({
        'status': 'available',
        'layout': plan['layout'],
      })!;
      final carrier = deck.carriers[3];
      final placed = Map<String, dynamic>.from(
        (carrier['placements'] as List).first,
      );
      final id = placed['id'] as String;
      String? selected;
      final board = RecordedDeckBoard(
        deck: deck,
        keys: {},
        selectedEntity: id,
        onItem: (item) => selected = item['id'],
      );
      final site =
          board.occupiedSite(carrier, placed['site'], [placed]) as Container;
      expect((site.decoration as BoxDecoration).color, const Color(0xffbddbf0));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: SizedBox(width: 220, height: 100, child: site)),
        ),
      );
      await tester.tap(find.text(id));
      expect(selected, id);
      selected = null;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: board.siteItem(carrier, placed['site'], placed)),
        ),
      );
      await tester.tap(find.text(id));
      expect(selected, id);
      expect(find.byTooltip(id), findsOneWidget);
    },
  );

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
        expect(
          find.byKey(const ValueKey('selected-loading-instructions')),
          findsOneWidget,
        );
        expect(state.scroll.offset, greaterThan(280));
        expect(tester.takeException(), isNull);
      },
    );
  }
}
