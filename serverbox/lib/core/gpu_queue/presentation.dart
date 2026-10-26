import 'package:server_box/core/gpu_queue/protocol.dart';

/// Human-readable queue data. Missing values stay missing, and historical GPU
/// readings never become live metrics merely because an SSH session is open.
abstract final class QueuePresentation {
  static String taskStatus(Object? state) =>
      const {
        'ready': '待开始',
        'queued': '队列中',
        'waiting_gpu': '等待 GPU',
        'checking_resources': '核查资源',
        'dispatching': '正在投放',
        'starting': '启动中',
        'running': '运行中',
        'stopping': '正在停止',
        'stopped': '已停止',
        'cancelled': '已取消',
        'completed': '已完成',
        'failed': '失败',
        'blocked': '需核查',
        'execution_unknown': '执行状态待核查',
        'interrupted': '已中断',
      }[state] ??
      '状态待核查';

  static num? _number(Object? value) =>
      value is num && value.isFinite && value >= 0 ? value : null;
  static String _decimal(num value) => value == value.roundToDouble()
      ? value.toInt().toString()
      : value.toStringAsFixed(1);
  static String _requirement(Object? value, String unit) {
    final number = _number(value);
    return number != null && number > 0 ? '${_decimal(number)} $unit' : '未提供';
  }

  static String requirements(Map<String, dynamic> task) {
    final resources = task['resources'] is Map
        ? task['resources'] as Map
        : const {};
    return '申请 GPU：${_requirement(resources['gpus'], '张 GPU')} · '
        '每卡显存：${_requirement(resources['memory_gb'] ?? task['memory'], 'GB')}';
  }

  static String compactRequirements(Map<String, dynamic> task) {
    final resources = task['resources'] is Map
        ? task['resources'] as Map
        : const {};
    return '${_requirement(resources['gpus'], 'GPU')} / ${_requirement(resources['memory_gb'] ?? task['memory'], 'GB')}';
  }

  static String version(Map<String, dynamic> task) {
    final value = task['version'] ?? task['digest'];
    return value is String && value.trim().isNotEmpty ? value : '未提供';
  }

  /// Task timestamps are ISO 8601 with an explicit zone or Unix seconds.
  /// Reject ambiguous / malformed values; polling time is never a substitute.
  static DateTime? taskTime(Object? value) {
    if (value is num) {
      if (!value.isFinite || value <= 0 || value > 8640000000000) return null;
      return DateTime.fromMillisecondsSinceEpoch(
        (value * 1000).round(),
        isUtc: true,
      );
    }
    if (value is! String ||
        !RegExp(
          r'(Z|[+-]\d{2}:?\d{2})$',
          caseSensitive: false,
        ).hasMatch(value)) {
      return null;
    }
    return DateTime.tryParse(value)?.toUtc();
  }

  static DateTime? taskSortTime(Map<String, dynamic> task) =>
      taskTime(task['updated_at']) ?? taskTime(task['created_at']);

  static String taskUpdated(Map<String, dynamic> task) {
    final at = taskTime(task['updated_at']);
    if (at == null) return '更新时间未提供';
    String two(int value) => value.toString().padLeft(2, '0');
    return '更新 ${at.year}-${two(at.month)}-${two(at.day)} '
        '${two(at.hour)}:${two(at.minute)}:${two(at.second)} UTC';
  }

  static String stepStatus(Object? state) =>
      const {
        'ready': '准备完成',
        'pending': '等待执行',
        'queued': '等待执行',
        'starting': '启动中',
        'running': '正在执行',
        'completed': '已完成',
        'done': '已完成',
        'failed': '执行失败',
        'stopping': '正在停止',
        'stopped': '已停止',
        'cancelled': '已取消',
        'skipped': '未执行',
        'interrupted': '执行中断',
        'blocked': '需要核查',
        'execution_unknown': '执行状态待核查',
      }[state] ??
      (state == null ? '等待执行' : '状态待核查');

  static DateTime? sampleTime(Map<String, dynamic> resource) {
    final at = _number(resource['telemetry']?['at']);
    if (at == null || at <= 0 || at > 8640000000000) return null;
    return DateTime.fromMillisecondsSinceEpoch((at * 1000).round());
  }

  static String sampleAge(Map<String, dynamic> resource, DateTime now) {
    final at = sampleTime(resource);
    if (at == null) return '尚未采样';
    final seconds = now.difference(at).inSeconds;
    if (seconds < -5) return '采样时间异常';
    if (seconds < 5) return '刚刚采样';
    if (seconds < 60) return '$seconds 秒前采样';
    if (seconds < 3600) return '${seconds ~/ 60} 分钟前采样';
    if (seconds < 86400) return '${seconds ~/ 3600} 小时前采样';
    return '${seconds ~/ 86400} 天前采样';
  }

  static String sampleAbsolute(Map<String, dynamic> resource) {
    final at = sampleTime(resource)?.toLocal();
    if (at == null) return '未提供采样时间';
    String two(int value) => value.toString().padLeft(2, '0');
    return '${at.year}-${two(at.month)}-${two(at.day)} '
        '${two(at.hour)}:${two(at.minute)}:${two(at.second)} ${at.timeZoneName}';
  }

  static String resourceStatus(
    Map<String, dynamic> resource,
    DateTime now, {
    required bool connected,
  }) {
    final state = resource['status'];
    if (state == 'closed') return '已回收';
    if (state == 'failed') return '申请失败';
    if (!connected) return '连接中断';
    if (QueueTarget.fresh(resource, now, connected: connected)) return '实时采样';
    if (state == 'pending') return '等待 GPU 就绪';
    final monitor = resource['monitor'];
    final phase = monitor is Map ? monitor['state'] : null;
    return const {
          'retry': '自动恢复中',
          'waiting': '等待查询回执',
          'reconciling': '正在核对查询回执',
          'sampling': '正在采样',
        }[phase] ??
        (state == 'ready' ? '正在采样' : '等待有效采样');
  }

  static List<Map<String, dynamic>> orderedResources(
    List<Map<String, dynamic>> resources,
    DateTime now, {
    required bool connected,
  }) {
    final rows = List<Map<String, dynamic>>.of(resources);
    int rank(Map<String, dynamic> row) =>
        QueueTarget.fresh(row, now, connected: connected)
        ? 0
        : const ['closed', 'failed'].contains(row['status'])
        ? 2
        : 1;
    rows.sort((a, b) {
      final order = rank(a).compareTo(rank(b));
      if (order != 0) return order;
      return (sampleTime(b)?.millisecondsSinceEpoch ?? 0).compareTo(
        sampleTime(a)?.millisecondsSinceEpoch ?? 0,
      );
    });
    return rows;
  }

  static String monitorSummary(
    List<Map<String, dynamic>> resources,
    DateTime now, {
    required bool connected,
  }) {
    final ids = <String>{};
    var recovering = 0;
    for (final row in resources) {
      if (QueueTarget.fresh(row, now, connected: connected)) {
        final raw = row['telemetry']?['gpus'];
        if (raw is List) {
          for (final gpu in raw.whereType<Map>()) {
            ids.add(
              gpu['uuid'] is String
                  ? gpu['uuid'] as String
                  : '${row['id']}:${gpu['index']}',
            );
          }
        }
      } else if (!const ['closed', 'failed'].contains(row['status'])) {
        recovering++;
      }
    }
    if (!connected) return '连接中断 · 保留最后读数';
    if (ids.isNotEmpty) {
      return '${ids.length} 张 GPU 实时监测'
          '${recovering > 0 ? ' · $recovering 份资源待恢复' : ''}';
    }
    if (recovering > 0) return '$recovering 份资源等待有效采样';
    return resources.isEmpty ? '等待 GPU 接入' : '资源已结束';
  }

  static List<QueueGpuReading> lastGpus(
    Map<String, dynamic> resource,
    DateTime now,
  ) {
    final at = sampleTime(resource);
    if (at == null || now.difference(at).inSeconds < -5) return [];
    final raw = resource['telemetry']?['gpus'];
    return raw is List
        ? [
            for (final gpu in raw.whereType<Map>())
              QueueGpuReading(gpu, false, historical: true),
          ]
        : [];
  }

  static List<QueueGpuReading> gpus(
    Map<String, dynamic> resource,
    DateTime now, {
    required bool connected,
  }) {
    final raw = resource['telemetry']?['gpus'];
    if (raw is! List) return [];
    final fresh = QueueTarget.fresh(resource, now, connected: connected);
    return [
      for (final gpu in raw.whereType<Map>()) QueueGpuReading(gpu, fresh),
    ];
  }
}

class QueueGpuReading {
  QueueGpuReading(this._gpu, this.fresh, {this.historical = false});
  final Map _gpu;
  final bool fresh;
  final bool historical;
  num? _metric(String key) =>
      fresh || historical ? QueuePresentation._number(_gpu[key]) : null;
  String? get uuid => _gpu['uuid'] is String ? _gpu['uuid'] as String : null;
  double? get utilizationFraction {
    final value = _metric('utilization');
    return fresh && value != null && value <= 100 ? value / 100 : null;
  }

  String get title {
    final index = QueuePresentation._number(_gpu['index']);
    final name = _gpu['name'];
    return 'GPU ${index == null ? '—' : QueuePresentation._decimal(index)} · '
        '${name is String && name.isNotEmpty ? name : '型号未提供'}';
  }

  String get utilization {
    final value = _metric('utilization');
    return value == null || value > 100
        ? '—'
        : '${QueuePresentation._decimal(value)}%';
  }

  String get memory {
    final used = _metric('used_mb'), total = _metric('total_mb');
    String gib(num? value) =>
        value == null ? '—' : (value / 1024).toStringAsFixed(1);
    return '${gib(used)} / ${gib(total)} GiB';
  }

  String get temperature {
    final value = _metric('temperature_c');
    return value == null ? '—' : '${QueuePresentation._decimal(value)} °C';
  }
}
