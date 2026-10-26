import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';

void main() {
  final now = DateTime.utc(2026, 10, 24, 12);
  test('task update time uses real timestamps with a single UTC format', () {
    final seconds = now.millisecondsSinceEpoch / 1000;
    for (final value in [
      seconds,
      '2026-10-24T12:00:00Z',
      '2026-10-24T20:00:00+08:00',
      '2026-10-24T05:00:00-0700',
    ]) {
      final task = <String, dynamic>{'updated_at': value};
      expect(QueuePresentation.taskUpdated(task), '更新 2026-10-24 12:00:00 UTC');
      expect(QueuePresentation.compactTaskUpdated(task), '更新 10-24 12:00');
      expect(QueuePresentation.taskSortTime(task), now);
    }
    expect(
      QueuePresentation.taskSortTime({'updated_at': seconds + 1}),
      now.add(const Duration(seconds: 1)),
    );
  });
  test('missing updates stay missing even when creation time is available', () {
    for (final value in [
      null,
      '',
      'invalid',
      '2026-10-24T12:00:00',
      -1,
      0,
      double.nan,
      double.infinity,
      8640000000001,
      {},
      true,
    ]) {
      final task = <String, dynamic>{
        'updated_at': value,
        'created_at': '2026-10-24T12:00:00Z',
      };
      expect(QueuePresentation.taskUpdated(task), '更新时间未提供');
      expect(QueuePresentation.compactTaskUpdated(task), '更新时间未提供');
      expect(QueuePresentation.taskSortTime(task), now);
    }
    expect(QueuePresentation.taskSortTime({}), isNull);
  });
  Map<String, dynamic> resource({double age = 35, String status = 'online'}) =>
      {
        'status': status,
        'telemetry': {
          'at': now.millisecondsSinceEpoch / 1000 - age,
          'gpus': [
            {
              'index': 0,
              'name': 'H100',
              'used_mb': 40960,
              'total_mb': 81920,
              'utilization': 65,
              'temperature_c': 61,
            },
            {
              'index': 1,
              'name': 'H100',
              'used_mb': 0,
              'total_mb': 81920,
              'utilization': 0,
            },
          ],
        },
      };
  test('request and version are available before allocation', () {
    final task = <String, dynamic>{
      'resources': {'gpus': 1, 'memory_gb': 2},
      'version': 'abc123',
    };
    expect(QueuePresentation.requirements(task), '申请 GPU：1 张 GPU · 每卡显存：2 GB');
    expect(QueuePresentation.version(task), 'abc123');
  });
  test('missing requirements are never presented as zero', () {
    for (final resources in [
      null,
      {},
      {'gpus': 0, 'memory_gb': -1},
      {'gpus': double.nan},
    ]) {
      expect(
        QueuePresentation.requirements({'resources': resources}),
        '申请 GPU：未提供 · 每卡显存：未提供',
      );
    }
    expect(
      QueuePresentation.requirements({
        'resources': {'gpus': 2},
        'memory': 2.5,
      }),
      contains('每卡显存：2.5 GB'),
    );
    expect(QueuePresentation.version({}), '未提供');
  });
  test(
    'multi GPU uses GiB and preserves real zero; missing measurements use dash',
    () {
      final readings = QueuePresentation.gpus(resource(), now, connected: true);
      expect(readings.length, 2);
      expect(readings.first.title, 'GPU 0 · H100');
      expect(readings.first.utilization, '65%');
      expect(readings.first.memory, '40.0 / 80.0 GiB');
      expect(readings.first.temperature, '61 °C');
      expect(readings.last.utilization, '0%');
      expect(readings.last.memory, '0.0 / 80.0 GiB');
      expect(readings.last.temperature, '—');
    },
  );
  test(
    'expired, offline, disconnected and future samples suppress every metric',
    () {
      for (final input in [
        resource(age: 90),
        resource(status: 'closed'),
        resource(age: -6),
      ]) {
        final gpu = QueuePresentation.gpus(input, now, connected: true).first;
        expect(gpu.utilization, '—');
        expect(gpu.memory, '— / — GiB');
        expect(gpu.temperature, '—');
      }
      expect(
        QueuePresentation.gpus(
          resource(),
          now,
          connected: false,
        ).first.utilization,
        '—',
      );
      expect(QueuePresentation.gpus({}, now, connected: true), isEmpty);
    },
  );
  test('sample age is readable and absolute time is available separately', () {
    expect(QueuePresentation.sampleAge(resource(), now), '35 秒前采样');
    expect(QueuePresentation.sampleAge(resource(age: 120), now), '2 分钟前采样');
    expect(QueuePresentation.sampleAge(resource(age: -6), now), '采样时间异常');
    expect(QueuePresentation.sampleAge({}, now), '尚未采样');
    expect(
      QueuePresentation.sampleTime({
        'telemetry': {'at': double.infinity},
      }),
      isNull,
    );
    expect(
      QueuePresentation.sampleAbsolute(resource()),
      startsWith('2026-10-24'),
    );
  });
  test('step states use Chinese semantics with a safe unknown fallback', () {
    expect(QueuePresentation.stepStatus('running'), '正在执行');
    expect(QueuePresentation.stepStatus('completed'), '已完成');
    expect(QueuePresentation.stepStatus('failed'), '执行失败');
    expect(QueuePresentation.stepStatus('skipped'), '未执行');
    expect(QueuePresentation.stepStatus(null), '等待执行');
    expect(QueuePresentation.stepStatus('new_internal_state'), '状态待核查');
  });
}
