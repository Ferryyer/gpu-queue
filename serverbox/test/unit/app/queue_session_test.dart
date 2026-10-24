import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/gpu_queue/session.dart';

void main() {
  const start = '/api/tasks/GQ-0000000000000001/start';
  test(
    'mode changes, poll and reconnect never post task authorization',
    () async {
      final calls = <String>[];
      final session = QueueSession(
        poll: false,
        identity: () => 'A',
        saveAuto: (_) {},
        request: (path, body, connect) async {
          calls.add('$path:${body == null}');
          return {'tasks': []};
        },
      );
      addTearDown(session.dispose);
      session.setAuto(true);
      session.setAuto(false);
      await session.refresh();
      await session.refresh(connect: true);
      expect(calls, ['/api/state:true', '/api/state:true']);
    },
  );
  test(
    'Auto rejects start and reorder while retaining explicit Stop',
    () async {
      final calls = <String>[];
      final session = QueueSession(
        poll: false,
        identity: () => 'A',
        auto: true,
        saveAuto: (_) {},
        request: (path, body, connect) async {
          calls.add(path);
          return {'tasks': []};
        },
      );
      addTearDown(session.dispose);
      await session.refresh();
      await expectLater(
        session.action(start, {'digest': 'version'}),
        throwsStateError,
      );
      await expectLater(
        session.action('/api/queue/reorder', {}),
        throwsStateError,
      );
      await session.action(start.replaceAll('start', 'stop'), {
        'digest': 'version',
      });
      expect(calls, ['/api/state', start.replaceAll('start', 'stop')]);
    },
  );
  test('uncertain POST outcome is never replayed after reconnect', () async {
    final calls = <String>[];
    final session = QueueSession(
      poll: false,
      identity: () => 'A',
      saveAuto: (_) {},
      request: (path, body, connect) async {
        calls.add(path);
        if (body != null) throw TimeoutException('lost acknowledgement');
        return {'tasks': []};
      },
    );
    addTearDown(session.dispose);
    await session.refresh();
    await expectLater(
      session.action(start, {'digest': 'version'}),
      throwsA(isA<TimeoutException>()),
    );
    expect(session.connected, isFalse);
    await session.refresh(connect: true);
    await session.refresh();
    expect(calls.where((path) => path == start).length, 1);
  });
  test('editing destination invalidates actions until a new read', () async {
    var destination = 'A';
    var posts = 0;
    final session = QueueSession(
      poll: false,
      identity: () => destination,
      saveAuto: (_) {},
      request: (path, body, connect) async {
        if (body != null) posts++;
        return {'tasks': []};
      },
    );
    addTearDown(session.dispose);
    await session.refresh();
    destination = 'B';
    await expectLater(
      session.action(start, {'digest': 'version'}),
      throwsStateError,
    );
    expect(posts, 0);
    await session.refresh();
    await session.action(start, {'digest': 'version'});
    expect(posts, 1);
  });
  test(
    'late response from previous host cannot replace current snapshot',
    () async {
      var destination = 'A';
      final response = Completer<Map<String, dynamic>>();
      final session = QueueSession(
        poll: false,
        identity: () => destination,
        saveAuto: (_) {},
        request: (path, body, connect) => response.future,
      );
      addTearDown(session.dispose);
      final loading = session.refresh();
      destination = 'B';
      response.complete({
        'tasks': [
          {'id': 'old-host'},
        ],
      });
      await loading;
      expect(session.tasks, isEmpty);
      expect(session.connected, isFalse);
    },
  );
  test(
    'failed refresh retains history and marks service unavailable',
    () async {
      var fail = false;
      final session = QueueSession(
        poll: false,
        identity: () => 'A',
        saveAuto: (_) {},
        request: (path, body, connect) async {
          if (fail) throw StateError('permission denied');
          return {
            'tasks': [
              {'id': 'task'},
            ],
          };
        },
      );
      addTearDown(session.dispose);
      await session.refresh();
      fail = true;
      await session.refresh();
      expect(session.tasks.single['id'], 'task');
      expect(session.connected, isFalse);
      expect(session.error, contains('permission denied'));
    },
  );
}
