import 'dart:convert';

import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';

/// Shared by the monitor and task detail; JSON is available only on request.
class QueueResourceView extends StatelessWidget {
  const QueueResourceView({
    super.key,
    required this.resource,
    required this.connected,
  });
  final Map<String, dynamic> resource;
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final fresh = QueueTarget.fresh(resource, now, connected: connected);
    final gpus = QueuePresentation.gpus(resource, now, connected: connected);
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${resource['id']} · ${fresh ? '实时采样' : '上次采样 · 非实时'}'),
          Tooltip(
            message: QueuePresentation.sampleAbsolute(resource),
            child: Text(QueuePresentation.sampleAge(resource, now)),
          ),
          if (!fresh) const Text('实时指标不可用，等待有效采样'),
          if (gpus.isEmpty) const Text('尚无 GPU 采样'),
          for (final gpu in gpus) ...[
            const SizedBox(height: 12),
            Text(gpu.title, style: Theme.of(context).textTheme.titleSmall),
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: [
                Text('利用率 ${gpu.utilization}'),
                Text('显存已用 / 总量 ${gpu.memory}'),
                Text('温度 ${gpu.temperature}'),
              ],
            ),
          ],
          TextButton(
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
        ],
      ),
    );
  }
}
