import 'dart:convert';

import 'package:fl_lib/src/model/notify.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('app_notify parse', () {
    final items = AppNotify.fromJsonList(json.decode(_raw));
    expect(items.length, 1);
    expect(items[0].title, 't');
    expect(items[0].msg, 'm');
    expect(items[0].vers.length, 1);
    expect(items[0].vers[0].min, 1);
    expect(items[0].vers[0].max, 2);
    expect(items[0].level, 1);
    expect(items[0].contains(1), true);
  });
}

const _raw = '''
[
    {
        "title": "t",
        "msg": "m",
        "vers": ["1-2"],
        "level": 1
    }
]
''';
