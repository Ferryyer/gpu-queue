// ignore_for_file: unnecessary_nullable_for_final_variable_declarations

import 'package:fl_lib/fl_lib.dart';
import 'package:flutter_test/flutter_test.dart';

class _CustomClass {}

void main() {
  group('ObjectX Tests', () {
    test('isBaseType identifies base types correctly', () {
      expect('string'.isBaseType, isTrue);
      expect(123.isBaseType, isTrue);
      expect(123.0.isBaseType, isTrue);
      expect(true.isBaseType, isTrue);
      expect([1, 2].isBaseType, isTrue);
      expect({'key': 'value'}.isBaseType, isTrue);
    });

    test('isBaseType identifies non-base types correctly', () {
      expect(_CustomClass().isBaseType, isFalse);
    });

    test('vn wraps object in VNode', () {
      const obj = 'test';
      final vNode = obj.vn;
      expect(vNode, isA<VNode<String>>());
      expect(vNode.value, obj);
    });
  });

  group('ObjectXNullable Tests', () {
    test('nullOr applies function for non-null value', () {
      const int? value = 5;
      final result = value.nullOr((val) => val + 5);
      expect(result, 10);
    });

    test('nullOr returns null for null value', () {
      const int? value = null;
      final result = value.nullOr((val) => val + 5);
      expect(result, isNull);
    });

    test('vn wraps nullable object in VNode', () {
      const String? nonNullObj = 'test';
      final nonNullVNode = nonNullObj.vn;
      expect(nonNullVNode, isA<VNode<String?>>());
      expect(nonNullVNode.value, nonNullObj);

      const String? nullObj = null;
      final nullVNode = nullObj.vn;
      expect(nullVNode, isA<VNode<String?>>());
      expect(nullVNode.value, isNull);
    });

    group('toStrDynMap Tests', () {
      test('converts Map with non-string keys', () {
        final map = {1: 'one', 2: 'two'};
        final result = map.toStrDynMap;
        expect(result, {'1': 'one', '2': 'two'});
      });

      test('converts List of Maps with non-string keys', () {
        final list = [
          {1: 'one'},
          {2: 'two'}
        ];
        final result = list.toStrDynMap;
        expect(result, [
          {'1': 'one'},
          {'2': 'two'}
        ]);
      });

      test('converts nested structures', () {
        final nested = {
          1: 'one',
          2: {3: 'three', 4: [5, {6: 'six'}]}
        };
        final result = nested.toStrDynMap;
        expect(result, {
          '1': 'one',
          '2': {'3': 'three', '4': [5, {'6': 'six'}]}
        });
      });

      test('returns base types as is', () {
        expect(123.toStrDynMap, 123);
        expect('hello'.toStrDynMap, 'hello');
        expect(true.toStrDynMap, true);
      });

      test('returns null as is', () {
        Object? obj; // explicitly nullable
        expect(obj.toStrDynMap, isNull);
      });

      test('returns custom objects as is', () {
        final custom = _CustomClass();
        expect(custom.toStrDynMap, custom);
      });

      test('handles map with mixed value types including lists and maps', () {
        final map = {
          1: 'string',
          2: 123,
          3: [
            {4: 'nested_string', 5: 456},
            789
          ],
          6: {7: 'another_map', 8: [10, 11]}
        };
        final expected = {
          '1': 'string',
          '2': 123,
          '3': [
            {'4': 'nested_string', '5': 456},
            789
          ],
          '6': {'7': 'another_map', '8': [10, 11]}
        };
        expect(map.toStrDynMap, expected);
      });
    });
  });

  group('nvn Tests', () {
    test('nvn creates a VNode<T?>(null)', () {
      final vNodeInt = nvn<int>();
      expect(vNodeInt, isA<VNode<int?>>());
      expect(vNodeInt.value, isNull);

      final vNodeString = nvn<String>();
      expect(vNodeString, isA<VNode<String?>>());
      expect(vNodeString.value, isNull);

      final vNodeCustom = nvn<_CustomClass>();
      expect(vNodeCustom, isA<VNode<_CustomClass?>>());
      expect(vNodeCustom.value, isNull);
    });
  });
}