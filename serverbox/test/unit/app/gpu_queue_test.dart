import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/utils/gpu_queue.dart';

void main() {
  test('queue link stays on the owner loopback forward', () {
    for (final value in ['http://127.0.0.1:8790/', 'http://localhost:8791/', 'http://[::1]:8790/']) {
      expect(GpuQueue.parseAddress(value), isNotNull);
    }
    for (final value in ['https://example.com/', 'file:///etc/passwd',
      'http://127.0.0.1.evil.test/', 'http://user@localhost/',
      'http://localhost/?start=1', 'http://localhost/api/tasks/start']) {
      expect(GpuQueue.parseAddress(value), isNull);
    }
  });
}
