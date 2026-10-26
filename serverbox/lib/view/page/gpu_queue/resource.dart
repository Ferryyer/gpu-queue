import 'dart:convert';

import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';

/// Shared native GPU cards. Historical readings are explicitly labelled.
class QueueResourceView extends StatelessWidget {
  const QueueResourceView({
    super.key,
    required this.resource,
    required this.connected,
    this.now,
  });
  final Map<String, dynamic> resource;
  final bool connected;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final at = now ?? DateTime.now();
    final fresh = QueueTarget.fresh(resource, at, connected: connected);
    final gpus = fresh
        ? QueuePresentation.gpus(resource, at, connected: connected)
        : QueuePresentation.lastGpus(resource, at);
    final theme = Theme.of(context);
    final status = QueuePresentation.resourceStatus(
      resource,
      at,
      connected: connected,
    );
    final retry = QueuePresentation.taskTime(
      resource['monitor']?['retry_at'] ?? resource['probe_retry_at'],
    );
    final telemetry = resource['telemetry'];
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              Text(
                status,
                style: theme.textTheme.titleSmall?.copyWith(
                  color: fresh
                      ? theme.colorScheme.secondary
                      : theme.colorScheme.onSurfaceVariant,
                ),
              ),
              Text(
                QueuePresentation.sampleAge(resource, at),
                style: theme.textTheme.bodySmall,
              ),
            ],
          ),
          if (resource['type'] is String)
            Text(resource['type'] as String, style: theme.textTheme.bodySmall),
          Tooltip(
            message: QueuePresentation.sampleAbsolute(resource),
            child: Text(
              '申请 ${resource['id'] ?? '未提供'}',
              style: theme.textTheme.bodySmall,
            ),
          ),
          if (!fresh && gpus.isNotEmpty) const Text('上次采样 · 非实时，下方为最后读数'),
          if (gpus.isEmpty) const Text('尚无 GPU 采样'),
          for (final gpu in gpus) ...[
            const SizedBox(height: 12),
            DecoratedBox(
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerLow,
                border: Border.all(color: theme.colorScheme.outlineVariant),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(gpu.title, style: theme.textTheme.titleSmall),
                    if (gpu.uuid != null)
                      Text(gpu.uuid!, style: theme.textTheme.bodySmall),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 16,
                      runSpacing: 8,
                      children: [
                        Text('利用率 ${gpu.utilization}'),
                        Text('显存已用 / 总量 ${gpu.memory}'),
                        Text('温度 ${gpu.temperature}'),
                      ],
                    ),
                    if (gpu.utilizationFraction != null) ...[
                      const SizedBox(height: 8),
                      LinearProgressIndicator(value: gpu.utilizationFraction),
                    ],
                  ],
                ),
              ),
            ),
          ],
          if (resource['error'] is String) ...[
            const SizedBox(height: 8),
            Text(resource['error'] as String, style: theme.textTheme.bodySmall),
          ],
          if (retry != null && retry.isAfter(at))
            Text(
              '约 ${retry.difference(at).inSeconds + 1} 秒后重试',
              style: theme.textTheme.bodySmall,
            ),
          if (telemetry is Map && telemetry['apps_known'] == false)
            const Text('进程占用信息不可用，暂不复用此资源。'),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (context) => AlertDialog(
                  title: const Text('采样诊断 · 原始数据'),
                  content: SingleChildScrollView(
                    child: SelectableText(
                      '采样时间：${QueuePresentation.sampleAbsolute(resource)}\n'
                      '${const JsonEncoder.withIndent('  ').convert(resource)}',
                    ),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('关闭'),
                    ),
                  ],
                ),
              ),
              child: const Text('查看采样时间 / 诊断数据'),
            ),
          ),
        ],
      ),
    );
  }
}

/// Visible across allocation/model changes; independent of selected task.
class QueueMonitorView extends StatelessWidget {
  const QueueMonitorView({
    super.key,
    required this.resources,
    required this.connected,
    this.now,
  });
  final List<Map<String, dynamic>> resources;
  final bool connected;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final at = now ?? DateTime.now();
    final rows = QueuePresentation.orderedResources(
      resources,
      at,
      connected: connected,
    );
    final current = rows.where(
      (r) => !const ['closed', 'failed'].contains(r['status']),
    );
    final history = rows
        .where((r) => const ['closed', 'failed'].contains(r['status']))
        .toList();
    return ExpansionTile(
      key: const PageStorageKey('gpu-occupancy-monitor'),
      initiallyExpanded: true,
      title: const Text('GPU 占用监测', style: TextStyle(fontSize: 14)),
      subtitle: Text(
        QueuePresentation.monitorSummary(rows, at, connected: connected),
      ),
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 260),
          child: ListView(
            shrinkWrap: true,
            children: [
              for (final resource in current)
                QueueResourceView(
                  key: ValueKey(resource['id']),
                  resource: resource,
                  connected: connected,
                  now: at,
                ),
              if (current.isEmpty)
                const ListTile(title: Text('GPU 接入后持续更新，任务结束后继续监测')),
              if (history.isNotEmpty)
                ExpansionTile(
                  key: const PageStorageKey('gpu-occupancy-history'),
                  title: Text('已结束资源 · ${history.length}'),
                  children: [
                    for (final resource in history)
                      QueueResourceView(
                        resource: resource,
                        connected: connected,
                        now: at,
                      ),
                  ],
                ),
            ],
          ),
        ),
      ],
    );
  }
}
