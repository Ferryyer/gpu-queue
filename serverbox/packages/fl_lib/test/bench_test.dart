// ignore_for_file: avoid_print

import 'package:flutter_test/flutter_test.dart' hide isEmpty;

import 'bench.dart';

void main() {
  Future<void> bench_(String Function(String) fn) async {
    final time = await bench(() {
      fn(_str1);
      fn(_str2);
      fn(_str3);
      fn(_str4);
    }, times: 70000);
    print('$fn: $time ms');
  }

  test('bench String.capitalize', () async {
    await bench_(_impl1);
    await bench_(_impl2);
    await bench_(_impl3);
  });
}

const _str1 = 'hello world';
const _str2 = '🪄🎉';
const _str3 = '777';
final _str4 = (_str1 + _str2 + _str3) * 1000;

String _impl1(String s) {
  if (s.isEmpty) return s;
  final firstRune = s.codeUnitAt(0);
  if (firstRune < 0x61 || firstRune > 0x7A) return s;
  final runes = List.of(s.runes);
  runes[0] = firstRune - 0x20;
  return String.fromCharCodes(runes);
}

String _impl2(String s) {
  if (s.isEmpty) return s;
  final runes = s.runes;
  // Only capitalize the first character if it's a lowercase ascii letter.
  if (runes.first < 0x61 || runes.first > 0x7A) return s;
  return s[0].toUpperCase() + s.substring(1);
}

String _impl3(String s) {
  if (s.isEmpty) return s;
  final first = s.codeUnitAt(0);
  if (first < 0x61 || first > 0x7A) return s;
  return String.fromCharCode(first - 0x20) + s.substring(1);
}
