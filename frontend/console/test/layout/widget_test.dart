import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/app.dart';
import 'fixture.dart';

void main() {
  testWidgets(
    'select position and move labware through native labeled controls',
    (tester) async {
      final c = LayoutFixture.controller();
      await tester.pumpWidget(CulsmaConsole(controller: c));
      await tester.pumpAndSettle();
      final semantics = tester.ensureSemantics();
      await tester.ensureVisible(find.byKey(const ValueKey('position-1')));
      await tester.tap(find.byKey(const ValueKey('position-1')));
      await tester.pumpAndSettle();
      expect(find.text('Move to position'), findsOneWidget);
      await tester.ensureVisible(
        find.byType(DropdownButtonFormField<String>).last,
      );
      await tester.tap(find.byType(DropdownButtonFormField<String>).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('3').last);
      await tester.pumpAndSettle();
      expect(c.proposal!['labware']['tubes']['slot'], '3');
      expect(c.dirty, isTrue);
      expect(find.bySemanticsLabel(RegExp('Position 3, tubes')), findsWidgets);
      semantics.dispose();
    },
  );
  testWidgets('select catalogue instead of typing a model identifier', (
    tester,
  ) async {
    final c = LayoutFixture.controller();
    await tester.pumpWidget(CulsmaConsole(controller: c));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('position-3')));
    await tester.tap(find.byKey(const ValueKey('position-3')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byType(DropdownButtonFormField<String>).last,
    );
    await tester.tap(find.byType(DropdownButtonFormField<String>).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('96-well plate · Corning 360 uL').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('add-labware')));
    await tester.tap(find.byKey(const Key('add-labware')));
    await tester.pumpAndSettle();
    expect(c.proposal!['labware']['labware_1']['slot'], '3');
    expect(find.text('labware_1'), findsWidgets);
  });
  testWidgets(
    'system navigation preserves edits and keyboard traversal works',
    (tester) async {
      final c = LayoutFixture.controller();
      await tester.pumpWidget(CulsmaConsole(controller: c));
      await tester.pumpAndSettle();
      c.move(c.definition!.items(c.proposal!).first, '3');
      await tester.pumpAndSettle();
      await tester.tap(find.text('System Information'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('save-layout')), findsNothing);
      await tester.tap(find.text('Layout').first);
      await tester.pumpAndSettle();
      expect(c.dirty, isTrue);
      expect(c.proposal!['labware']['tubes']['slot'], '3');
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pump();
      expect(FocusManager.instance.primaryFocus, isNotNull);
    },
  );
  testWidgets(
    'track carrier selection and site placement use accessible native controls',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final c = LayoutFixture.controller(
        installedProfile: LayoutFixture.hamiltonProfile(),
      );
      await tester.pumpWidget(CulsmaConsole(controller: c));
      await tester.pumpAndSettle();
      expect(
        tester
            .getSemantics(find.bySemanticsLabel(RegExp('Track 1, plates')))
            .flagsCollection
            .isButton,
        isTrue,
      );
      expect(find.text('Open setup'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('carrier-plates')));
      await tester.pumpAndSettle();
      expect(find.text('Carrier sites'), findsOneWidget);
      final site = find.widgetWithText(
        DropdownButtonFormField<String>,
        'Empty carrier site',
      );
      await tester.ensureVisible(site);
      await tester.tap(site);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Site 2').last);
      await tester.pumpAndSettle();
      final model = find.widgetWithText(
        DropdownButtonFormField<String>,
        'Compatible labware',
      );
      await tester.ensureVisible(model);
      await tester.tap(model);
      await tester.pumpAndSettle();
      await tester.tap(find.text('96-position deep-well plate').last);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('site-labware-name')),
        'destination',
      );
      await tester.ensureVisible(find.byKey(const Key('place-site-labware')));
      await tester.tap(find.byKey(const Key('place-site-labware')));
      await tester.pumpAndSettle();
      expect(c.proposal!['labware']['destination']['site'], '2');
      expect(c.dirty, isTrue);
      expect(c.canApply, isFalse);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'opening another platform resets the pending catalogue selection',
    (tester) async {
      final c = LayoutFixture.controller();
      final hamilton = LayoutFixture.hamiltonProfile();
      hamilton['template']['carriers'] = <String, dynamic>{};
      hamilton['template']['labware'] = <String, dynamic>{};
      c.profiles.add(hamilton);
      await tester.pumpWidget(CulsmaConsole(controller: c));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const ValueKey('position-3')));
      await tester.tap(find.byKey(const ValueKey('position-3')));
      await tester.pumpAndSettle();
      final catalogue = find.widgetWithText(
        DropdownButtonFormField<String>,
        'Choose labware',
      );
      await tester.ensureVisible(catalogue);
      await tester.tap(catalogue);
      await tester.pumpAndSettle();
      await tester.tap(find.text('96-well plate · Corning 360 uL').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Open station setup'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('New: Hamilton · offline layout planning'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const ValueKey('position-3')));
      await tester.tap(find.byKey(const ValueKey('position-3')));
      await tester.pumpAndSettle();
      expect(find.text('Choose carrier'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
