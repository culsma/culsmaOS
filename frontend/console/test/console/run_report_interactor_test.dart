import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:culsma_console/features/console/interactor/run_report_interactor.dart';

void main() {
  final run = jsonDecode(
    File(
      'test/console/fixtures/standard_dilution_report.json',
    ).readAsStringSync(),
  );
  final report = NativeRunReportInteractor();
  test(
    'actual language report retains products, input amounts and consumption',
    () {
      final sections = report.describe(run['result']);
      expect(sections[0].title, 'Final products');
      expect(sections[0].rows, [
        ['Dilution standards_A1', '100 µL'],
        ['Dilution standards_A2', '100 µL'],
        ['Dilution standards_A3', '100 µL'],
      ]);
      expect(sections[1].rows, [
        ['Diluent', '1000 µL'],
        ['Standard stock', '1000 µL'],
      ]);
      expect(sections[2].rows, [
        ['Diluent', '230 µL'],
        ['Standard stock', '70 µL'],
      ]);
      expect(sections[3].rows, [
        ['tube', '2'],
        ['well', '3'],
      ]);
      expect(sections[4].rows, [
        ['Liquid operations', '3'],
      ]);
      expect(sections.any((s) => s.title == 'Declared instruments'), false);
    },
  );
  test(
    'legacy fallback prefers labels and never exposes internal allocation names',
    () {
      final result = {
        'os': {
          'registered_material': {
            'state': {
              'containers': {
                'container/a': {
                  'metadata': {
                    'label': 'Dilution standards_A1',
                    'allocation_name': '__lw_plate_assay_A1',
                  },
                  'volume_uL': 100,
                },
                'container/b': {
                  'metadata': {'allocation_name': '__lw_plate_assay_A2'},
                  'volume_uL': 73.2,
                },
              },
            },
          },
        },
      };
      final rows = report.describe(result).single.rows;
      expect(rows[0], ['Dilution standards_A1', '100 µL']);
      expect(rows[1], ['Container 2', '73.2 µL']);
      expect(report.describe({}), isEmpty);
      expect(report.quantity({}, 'initial'), 'Not reported');
      expect(report.quantity({'consumed_mg': 2.5}, 'consumed'), '2.5 mg');
      expect(report.quantity({'volume_mL': 0.1}, 'volume'), '0.1 mL');
    },
  );
}
