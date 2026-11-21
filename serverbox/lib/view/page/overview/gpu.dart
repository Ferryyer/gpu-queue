import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/controller.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';
import 'package:server_box/data/model/app/tab.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/provider/app/session_requests.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/store.dart';

class GpuSummaryPanel extends ConsumerWidget {
  const GpuSummaryPanel({super.key});

  void _open(WidgetRef ref, AppTab tab) => ref.read(homeTabRequestProvider.notifier).go(tab);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final servers = ref.watch(serversProvider).servers;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(padding: const EdgeInsets.fromLTRB(16, 12, 8, 4), child: Row(children: [
        Expanded(child: Text('GPU 任务', style: Theme.of(context).textTheme.titleLarge)),
        IconButton(tooltip: '打开完整 GPU 任务页', onPressed: () => _open(ref, AppTab.tasks),
          icon: const Icon(Icons.open_in_full, size: 20)),
      ])),
      Expanded(child: ValueListenableBuilder(
        valueListenable: Stores.setting.gpuQueueServer.listenable(),
        builder: (context, _, _) {
          final service = Stores.setting.gpuQueueServer.fetch();
          final available = servers.values.where((s) => s.sshOn != null).toList();
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: DropdownButton<String>(
              value: available.any((s) => s.id == service) ? service : null,
              isExpanded: true, hint: const Text('选择个人任务服务'),
              items: [for (final server in available) DropdownMenuItem(value: server.id,
                child: Text(server.name, overflow: TextOverflow.ellipsis))],
              onChanged: (id) { if (id != null) Stores.setting.gpuQueueServer.put(id); },
            )),
            Expanded(child: available.any((s) => s.id == service)
              ? _GpuTasks(service: service, onOpen: () => _open(ref, AppTab.tasks))
              : Center(child: Padding(padding: const EdgeInsets.all(20), child: Column(
                  mainAxisSize: MainAxisSize.min, children: [
                    const Text('连接个人 CPU 上的任务服务后，在这里查看 GPU 任务进度。'),
                    const SizedBox(height: 12),
                    OutlinedButton(onPressed: () => _open(ref, AppTab.server), child: const Text('前往服务器')),
                  ])))),
          ]);
        },
      )),
    ]);
  }
}

class _GpuTasks extends ConsumerWidget {
  const _GpuTasks({required this.service, required this.onOpen});
  final String service;
  final VoidCallback onOpen;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final queue = ref.watch(queueControllerProvider(service));
    final ssh = ref.watch(serverProvider(service)).client;
    return ListenableBuilder(listenable: queue, builder: (context, _) {
      final connected = queue.hasSnapshot && queue.connected && ssh != null && !ssh.isClosed;
      final tasks = [...queue.tasks];
      int priority(Map<String, dynamic> task) => QueuePresentation.attentionStates.contains(task['state']) ? 0
        : task['state'] == 'ready' ? 1 : QueuePresentation.runningStates.contains(task['state']) ? 2
        : QueuePresentation.waitingStates.contains(task['state']) ? 3 : 4;
      tasks.sort((a, b) {
        final order = priority(a).compareTo(priority(b));
        return order != 0 ? order : (QueuePresentation.taskSortTime(b)?.millisecondsSinceEpoch ?? 0)
          .compareTo(QueuePresentation.taskSortTime(a)?.millisecondsSinceEpoch ?? 0);
      });
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Row(children: [
          Icon(connected ? Icons.check_circle_outline : Icons.cloud_off_outlined, size: 16),
          const SizedBox(width: 6),
          Expanded(child: Text(connected ? '已连接 · ${tasks.length} 个任务'
            : queue.loading ? '正在同步…' : queue.hasSnapshot ? '连接中断 · 显示上次记录' : '任务服务尚未连接',
            style: Theme.of(context).textTheme.bodySmall)),
          IconButton(tooltip: '同步 GPU 任务', onPressed: queue.loading ? null : () => queue.refresh(connect: true),
            icon: const Icon(Icons.refresh, size: 18)),
        ])),
        if (queue.hasSnapshot) Padding(padding: const EdgeInsets.fromLTRB(16, 4, 16, 8), child: Wrap(spacing: 8, runSpacing: 6, children: [
          for (final entry in const {'running': '执行中', 'waiting': '等待资源', 'failed': '需处理'}.entries)
            Text('${entry.value} ${tasks.where((t) => QueuePresentation.matches(t, entry.key)).length}',
              style: Theme.of(context).textTheme.labelMedium),
        ])),
        const Divider(height: 1),
        Expanded(child: tasks.isEmpty ? Center(child: Padding(padding: const EdgeInsets.all(20),
          child: Text(queue.hasSnapshot ? '当前没有 GPU 任务' : '点击同步，或前往 GPU 任务页检查连接。')))
          : ListView.separated(padding: const EdgeInsets.symmetric(vertical: 4),
              itemCount: tasks.length.clamp(0, 5),
              separatorBuilder: (_, _) => const Divider(height: 1, indent: 16, endIndent: 16),
              itemBuilder: (context, index) {
                final task = tasks[index];
                return ListTile(dense: true, onTap: onOpen,
                  title: Text('${task['name'] ?? task['id'] ?? '未命名任务'}', maxLines: 2, overflow: TextOverflow.ellipsis),
                  subtitle: Text(QueuePresentation.taskStatus(task['state'])),
                  trailing: const Icon(Icons.chevron_right, size: 18));
              })),
        Align(alignment: Alignment.centerRight, child: TextButton(onPressed: onOpen, child: const Text('查看全部任务 →'))),
      ]);
    });
  }
}
