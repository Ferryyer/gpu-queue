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
    final type = resources['type'];
    return '${type is String && type.isNotEmpty ? '资源类型：$type\n' : ''}'
        '申请 GPU：${_requirement(resources['gpus'], '张 GPU')} · '
        '每卡显存：${_requirement(resources['memory_gb'] ?? task['memory'], 'GB')}';
  }

  static String compactRequirements(Map<String, dynamic> task) {
    final resources = task['resources'] is Map
        ? task['resources'] as Map
        : const {};
    final type = resources['type'];
    final memory = _number(resources['memory_gb'] ?? task['memory']);
    return '${type is String && type.isNotEmpty ? '$type · ' : ''}'
        '${_requirement(resources['gpus'], 'GPU')}'
        '${memory != null && memory > 0 ? ' / ${_decimal(memory)} GB' : ' · 显存未指定'}';
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

  static DateTime? taskSortTime(Map<String, dynamic> task) {
    final times = [
      for (final key in ['updated_at', 'created_at', 'approved_at', 'claimed_at', 'stop_requested_at', 'stopped_at'])
        taskTime(task[key]),
      for (final step in (task['step_records'] as List? ?? []).whereType<Map>()) ...[
        taskTime(step['started_at']), taskTime(step['finished_at']),
      ],
    ].whereType<DateTime>().toList()..sort();
    return times.lastOrNull;
  }

  static String taskUpdated(Map<String, dynamic> task) {
    final at = taskTime(task['updated_at']) ?? taskSortTime(task);
    if (at == null) return '时间未提供';
    final label = taskTime(task['updated_at']) != null ? '更新'
        : at == taskTime(task['created_at']) ? '提交' : '活动';
    String two(int value) => value.toString().padLeft(2, '0');
    return '$label ${at.year}-${two(at.month)}-${two(at.day)} '
        '${two(at.hour)}:${two(at.minute)}:${two(at.second)} UTC';
  }

  static const attentionStates = {'failed', 'interrupted', 'blocked', 'execution_unknown'};
  static const waitingStates = {'queued', 'waiting_gpu', 'checking_resources', 'dispatching'};
  static const runningStates = {'running', 'starting', 'stopping'};

  static bool matches(Map<String, dynamic> task, String filter) => switch (filter) {
    'ready' => task['state'] == 'ready',
    'waiting' => waitingStates.contains(task['state']),
    'running' => runningStates.contains(task['state']),
    'failed' => attentionStates.contains(task['state']),
    'history' => {'completed', 'stopped', 'cancelled', 'failed', 'interrupted'}.contains(task['state']),
    _ => true,
  };

  static String nextAction(Map<String, dynamic> task) => switch (task['state']) {
    'ready' => '检查资源需求和固定版本后，点击开始。准备完成的任务不会占用 GPU。',
    'queued' => '已收到启动授权，等待调度。无需重复提交。',
    'waiting_gpu' => '正在等待满足资源条件，具体原因见任务阶段。请核对申请回执、显存与已有任务；回执不明时不要重复申请。',
    'checking_resources' => '正在检查已有 GPU 的可用性。查询超时不代表实例已释放。',
    'dispatching' || 'starting' => '启动授权已交给执行端，正在确认运行状态。请勿重复提交。',
    'running' => '正在执行。可以查看各步骤日志和已经生成的结果。',
    'stopping' => '停止请求已记录，等待执行端确认。停止任务不等于释放 GPU。',
    'completed' => '流程已完成，可查看结果。GPU 是否释放以平台回执为准。',
    'failed' || 'interrupted' => '查看失败步骤与日志，修复后提交新版本，再手动开始。',
    'blocked' || 'execution_unknown' => '先核对申请和执行端状态，避免重复申请或重复运行。',
    'stopped' || 'cancelled' => '这一版已结束；如需再运行，请提交新版本。已有产物保留。',
    _ => '服务返回了尚未识别的状态，请在连接诊断中核对版本并联系维护者。',
  };

  /// Deliberately excludes logs, paths, hostnames and credentials.
  static String handoff(Map<String, dynamic> task) =>
      '请检查 GPU Queue 任务 ${task['id']}（版本 ${version(task)}）。\n'
      '状态：${taskStatus(task['state'])}\n'
      '资源：${compactRequirements(task)}\n'
      '${taskUpdated(task)}\n'
      '下一步：${nextAction(task)}\n'
      '请先只读核查；不要直接申请 GPU、重跑任务或改写启动授权。修复后提交新版本，等待我点击开始。';

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
