import 'package:fl_lib/fl_lib.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('vn test', () {
    final vn = 1.vn;
    expect(vn.value, 1);
    vn.value = 2;
    expect(vn.value, 2);

    final vnn = nvn<Loggers>();
    expect(vnn.value, null);
  });
}
