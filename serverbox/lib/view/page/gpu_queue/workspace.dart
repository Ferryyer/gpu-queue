import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';

/// Native surfaces shared by the live workspace and its CPU render checks.
class QueuePanel extends StatelessWidget {
  const QueuePanel({
    super.key,
    required this.child,
    this.padding = EdgeInsets.zero,
  });
  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: colors.outlineVariant),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Padding(padding: padding, child: child),
    );
  }
}

class QueueStatusBadge extends StatelessWidget {
  const QueueStatusBadge({super.key, required this.state});
  final String state;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final active = ['running', 'completed'].contains(state);
    final error = [
      'failed',
      'interrupted',
      'blocked',
      'execution_unknown',
    ].contains(state);
    final color = error
        ? colors.error
        : active
        ? colors.secondary
        : colors.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: error
            ? colors.errorContainer
            : active
            ? colors.secondaryContainer
            : colors.surfaceContainer,
        borderRadius: BorderRadius.circular(5),
      ),
      child: Text(
        QueuePresentation.taskStatus(state),
        style: Theme.of(context).textTheme.labelMedium?.copyWith(color: color),
      ),
    );
  }
}

class QueueConnectionIndicator extends StatelessWidget {
  const QueueConnectionIndicator({
    super.key,
    required this.label,
    required this.available,
  });
  final String label;
  final bool available;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          available ? Icons.check_circle_outline : Icons.circle_outlined,
          size: 14,
          color: available ? colors.secondary : colors.onSurfaceVariant,
        ),
        const SizedBox(width: 6),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}

class QueueWorkspaceHeading extends StatelessWidget {
  const QueueWorkspaceHeading({super.key});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 20),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'GPU QUEUE / 个人计算工作台',
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
            letterSpacing: 1.5,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '每个实验，都有进展。',
          style: Theme.of(
            context,
          ).textTheme.headlineMedium?.copyWith(fontSize: 28, height: 1.35),
        ),
        const SizedBox(height: 6),
        Text('查看准备情况，安排顺序，再开始。', style: Theme.of(context).textTheme.bodySmall),
      ],
    ),
  );
}

class QueueStats extends StatelessWidget {
  const QueueStats({super.key, required this.tasks, this.compact = false});
  final List<Map<String, dynamic>> tasks;
  final bool compact;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final entries = [
      ('待你启动', ['ready'], Icons.schedule_outlined, colors.onSurface),
      (
        '执行队列',
        ['queued', 'waiting_gpu', 'checking_resources', 'dispatching'],
        Icons.format_list_numbered,
        colors.onSurface,
      ),
      (
        '正在运行',
        ['running', 'starting', 'stopping'],
        Icons.play_circle_outline,
        colors.secondary,
      ),
      (
        '需要处理',
        ['failed', 'interrupted', 'blocked', 'execution_unknown'],
        Icons.error_outline,
        colors.error,
      ),
    ];
    return LayoutBuilder(
      builder: (context, bounds) {
        final columns = bounds.maxWidth >= 600 ? 4 : 2;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final (label, states, icon, color) in entries)
              SizedBox(
                width: (bounds.maxWidth - (columns - 1) * 12) / columns,
                child: QueuePanel(
                  padding: EdgeInsets.all(compact ? 12 : 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              label,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                          Icon(icon, size: 18, color: color),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        tasks
                            .where((task) => states.contains(task['state']))
                            .length
                            .toString()
                            .padLeft(2, '0'),
                        style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          fontFamily: null,
                          fontSize: compact ? 25 : 30,
                          color: color,
                          fontFeatures: const [FontFeature.tabularFigures()],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class QueueTaskTile extends StatelessWidget {
  const QueueTaskTile({
    super.key,
    required this.task,
    required this.selected,
    required this.onTap,
  });
  final Map<String, dynamic> task;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context), colors = theme.colorScheme;
    final id = '${task['id'] ?? ''}';
    final steps = task['steps'] as List? ?? [];
    final stage = (task['stage'] is num ? (task['stage'] as num).toInt() : 0)
        .clamp(0, steps.length);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: selected ? colors.primaryContainer : colors.surfaceContainerLow,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(
            color: selected ? colors.primary : colors.outlineVariant,
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        '${task['name'] ?? '未命名任务'}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium,
                      ),
                    ),
                    const SizedBox(width: 12),
                    QueueStatusBadge(state: '${task['state']}'),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  '${task['project'] ?? '未指定项目'} · ${id.length > 14 ? '…${id.substring(id.length - 10)}' : id}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall,
                ),
                if (steps.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    steps.join('  →  '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: colors.secondary,
                    ),
                  ),
                ],
                if (task['state'] == 'running' && steps.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  LinearProgressIndicator(
                    value: stage / steps.length,
                    minHeight: 3,
                    color: colors.secondary,
                    backgroundColor: colors.secondaryContainer,
                  ),
                ],
                const SizedBox(height: 10),
                Row(
                  children: [
                    if (task['agent'] != null)
                      Text(
                        '${task['agent']}',
                        style: theme.textTheme.labelSmall,
                      ),
                    const Spacer(),
                    Text(
                      '查看详情',
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: colors.primary,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(Icons.arrow_forward, size: 16, color: colors.primary),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Keeps task scrolling independent of the detail on desktop; on small/short
/// windows the heading, counts and tasks share one scrollable column.
class QueueWorkspaceView extends StatelessWidget {
  const QueueWorkspaceView({
    super.key,
    required this.tasks,
    required this.allTasks,
    required this.onSelect,
    required this.onQuery,
    required this.filter,
    required this.onFilter,
    required this.controller,
    required this.detail,
    required this.monitor,
    this.selected,
    this.overview = false,
    this.loading = false,
  });
  final List<Map<String, dynamic>> tasks, allTasks;
  final String? selected;
  final bool overview, loading;
  final String filter;
  final void Function(Map<String, dynamic> task, bool wide) onSelect;
  final ValueChanged<String> onQuery, onFilter;
  final ScrollController controller;
  final Widget detail, monitor;

  Widget _filters(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      TextField(
        key: const ValueKey('queue-search'),
        decoration: const InputDecoration(
          hintText: '搜索任务、项目…',
          prefixIcon: Icon(Icons.search),
        ),
        onChanged: onQuery,
      ),
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 6,
        children: [
          for (final entry in {
            'all': '全部任务',
            'queue': '执行队列',
            'ready': '待启动',
            'history': '已结束',
          }.entries)
            ChoiceChip(
              label: Text(entry.value),
              selected: filter == entry.key,
              onSelected: (_) => onFilter(entry.key),
            ),
        ],
      ),
      const SizedBox(height: 16),
    ],
  );

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, bounds) {
      final wide = bounds.maxWidth >= 960 && bounds.maxHeight >= 520;
      final space = bounds.maxWidth < 600 ? 16.0 : 24.0;
      Widget list({required bool intro}) => CustomScrollView(
        controller: controller,
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (intro) ...[
                  if (overview) const QueueWorkspaceHeading(),
                  QueueStats(tasks: allTasks, compact: true),
                  const SizedBox(height: 20),
                ],
                _filters(context),
              ],
            ),
          ),
          if (tasks.isEmpty)
            SliverToBoxAdapter(
              child: QueuePanel(
                padding: const EdgeInsets.all(24),
                child: Column(
                  children: [
                    Icon(
                      loading ? Icons.sync : Icons.inbox_outlined,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      loading ? '正在同步任务…' : '暂无匹配任务',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      allTasks.isEmpty
                          ? '新提交的任务会出现在这里，准备好后由你点击开始。'
                          : '试试其他筛选条件或搜索词。',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ),
          SliverList.builder(
            itemCount: tasks.length,
            findChildIndexCallback: (key) {
              final index = tasks.indexWhere(
                (task) => ValueKey(task['id']) == key,
              );
              return index < 0 ? null : index;
            },
            itemBuilder: (context, index) {
              final task = tasks[index];
              return QueueTaskTile(
                key: ValueKey(task['id']),
                task: task,
                selected: selected == task['id'],
                onTap: () => onSelect(task, wide),
              );
            },
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.only(top: 12, bottom: 24),
              child: monitor,
            ),
          ),
        ],
      );
      return Padding(
        padding: EdgeInsets.fromLTRB(space, 16, space, 0),
        child: wide
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (overview && bounds.maxHeight >= 740)
                    const QueueWorkspaceHeading(),
                  QueueStats(tasks: allTasks, compact: bounds.maxHeight < 740),
                  const SizedBox(height: 20),
                  Expanded(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SizedBox(
                          width: (bounds.maxWidth * .46).clamp(360.0, 540.0),
                          child: list(intro: false),
                        ),
                        const SizedBox(width: 20),
                        Expanded(child: QueuePanel(child: detail)),
                      ],
                    ),
                  ),
                ],
              )
            : list(intro: true),
      );
    },
  );
}

class QueueTaskHeading extends StatelessWidget {
  const QueueTaskHeading({super.key, required this.task});
  final Map<String, dynamic> task;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      QueueStatusBadge(state: '${task['state']}'),
      const SizedBox(height: 12),
      Text(
        '${task['name']}',
        style: Theme.of(context).textTheme.headlineSmall?.copyWith(height: 1.4),
      ),
      const SizedBox(height: 8),
      Text(
        '${task['description'] ?? ''}',
        style: Theme.of(context).textTheme.bodyMedium,
      ),
      const SizedBox(height: 8),
      SelectableText(
        '${task['id']}',
        style: Theme.of(context).textTheme.bodySmall,
      ),
      const SizedBox(height: 20),
      QueuePanel(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('申请资源需求', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 6),
            SelectableText(QueuePresentation.requirements(task)),
            const SizedBox(height: 8),
            SelectableText(
              '固定版本：${QueuePresentation.version(task)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            Text(
              task['approved_at'] == null ? '等待你点击开始' : '这一版已授权',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
      const SizedBox(height: 16),
    ],
  );
}
