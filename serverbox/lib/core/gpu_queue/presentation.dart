import 'package:server_box/core/gpu_queue/protocol.dart';

/// Human-readable queue data. Missing values stay missing, and historical GPU
/// readings never become live metrics merely because an SSH session is open.
abstract final class QueuePresentation {
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

  static String version(Map<String, dynamic> task) {
    final value = task['version'] ?? task['digest'];
    return value is String && value.trim().isNotEmpty ? value : '未提供';
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
  QueueGpuReading(this._gpu, this.fresh);
  final Map _gpu;
  final bool fresh;
  num? _metric(String key) =>
      fresh ? QueuePresentation._number(_gpu[key]) : null;
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
