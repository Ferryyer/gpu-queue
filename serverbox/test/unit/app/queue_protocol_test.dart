import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';

void main() {
  test('only existing queue API paths are sent over SSH', () {
    expect(QueueProtocol.command('/api/state'), contains('python3 -c'));
    for (final path in [
      '/api/worker/claim',
      '/api/tasks/GQ-0000000000000001/start; rm',
      'https://example.com',
      '/api/state\nwhoami',
    ]) {
      expect(() => QueueProtocol.command(path), throwsArgumentError);
    }
    final hostile = "'; touch /tmp/queue-injection; \$(echo bad)";
    final command = QueueProtocol.command(
      '/api/tasks/GQ-0000000000000001/start',
      {'digest': hostile},
    );
    expect(command, isNot(contains(hostile)));
    final body = jsonDecode(
      utf8.decode(base64.decode(command.split(' ').last)),
    );
    expect(body['body']['digest'], hostile);
  });
  test('service errors and malformed responses cannot become success', () {
    expect(
      QueueProtocol.decode('{"status":200,"body":{"tasks":[]}}')['tasks'],
      isEmpty,
    );
    expect(
      () => QueueProtocol.decode('{"status":403,"body":{"error":"forbidden"}}'),
      throwsStateError,
    );
    expect(() => QueueProtocol.decode('not json'), throwsFormatException);
  });
  test(
    'instance namespace separates queue services and ignores host names',
    () {
      expect(
        QueueTarget.key('A', 'instance'),
        isNot(QueueTarget.key('B', 'instance')),
      );
      expect(QueueTarget.instance({'name': 'gpu-1', 'host': 'gpu-1'}), isNull);
      expect(QueueTarget.instance({'request_uuid': 'request-1'}), 'request-1');
      expect(
        QueueTarget.directory({
          'execution': {'workspace': '/a b/测试'},
        }),
        '/a b/测试',
      );
      expect(
        QueueTarget.directory({
          'execution': {'workspace': 'relative'},
        }),
        isNull,
      );
    },
  );
  test('binding invalidates when either SSH endpoint changes', () {
    final binding = {'identity': 'target:22', 'origin': 'queue:22'};
    expect(
      QueueTarget.bindingMatches(binding, 'target:22', 'queue:22'),
      isTrue,
    );
    expect(
      QueueTarget.bindingMatches(binding, 'target:23', 'queue:22'),
      isFalse,
    );
    expect(
      QueueTarget.bindingMatches(binding, 'target:22', 'other:22'),
      isFalse,
    );
  });
  test('disconnection, stale and future timestamps suppress live metrics', () {
    final now = DateTime.fromMillisecondsSinceEpoch(1000000);
    final resource = <String, dynamic>{
      'status': 'online',
      'telemetry': {'at': 999},
    };
    expect(QueueTarget.fresh(resource, now, connected: true), isTrue);
    expect(QueueTarget.fresh(resource, now, connected: false), isFalse);
    resource['telemetry']['at'] = 900;
    expect(QueueTarget.fresh(resource, now, connected: true), isFalse);
    resource['telemetry']['at'] = 1010;
    expect(QueueTarget.fresh(resource, now, connected: true), isFalse);
  });
}
