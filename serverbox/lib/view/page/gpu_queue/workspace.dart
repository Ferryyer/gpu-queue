import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';

class QueueWelcome extends StatelessWidget {
  const QueueWelcome({super.key, required this.hasServers, required this.onAdd, required this.onGuide});
  final bool hasServers;
  final VoidCallback onAdd, onGuide;
  @override
  Widget build(BuildContext context) => Center(
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: QueuePanel(child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.hub_outlined, size: 32),
            const SizedBox(height: 16),
            Text('接入你的计算工作台', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 12),
            const Text('使用公司分配给你的个人服务器账号。任务、日志和结果通过自己的 SSH 连接读取。'),
            const SizedBox(height: 20),
            Text('1 · ${hasServers ? '已有服务器：在右上角选择运行任务服务的 CPU 服务器' : '添加个人 CPU 服务器的 SSH 连接'}'),
            const SizedBox(height: 12),
            const Text('2 · 连接并检查个人任务服务；首次接入按员工指南安装'),
            const SizedBox(height: 12),
            const Text('3 · 让 Agent 准备任务，核对需求后由你点击开始'),
            const SizedBox(height: 20),
            Wrap(spacing: 12, runSpacing: 8, children: [
              FilledButton.icon(onPressed: onAdd, icon: const Icon(Icons.add), label: const Text('添加服务器')),
              OutlinedButton(onPressed: onGuide, child: const Text('员工接入指南')),
            ]),
            const SizedBox(height: 16),
            Text('首次使用需要管理员已开通个人账号，并由本人完成飞书授权。', style: Theme.of(context).textTheme.bodySmall),
          ]),
        )),
      ),
    ),
  );
}

class QueueOverview extends StatelessWidget {
  const QueueOverview({super.key, required this.tasks, required this.filter, required this.onFilter});
  final List<Map<String, dynamic>> tasks;
  final String filter;
  final ValueChanged<String> onFilter;
  @override
  Widget build(BuildContext context) => Wrap(spacing: 8, runSpacing: 8, children: [
    for (final entry in const {'ready': '待你开始', 'waiting': '等待资源', 'running': '执行中', 'failed': '需要处理'}.entries)
      ChoiceChip(
        selected: filter == entry.key,
        label: Text('${entry.value} ${tasks.where((t) => QueuePresentation.matches(t, entry.key)).length}'),
        onSelected: (selected) => onFilter(selected ? entry.key : 'all'),
      ),
  ]);
}

class QueuePanel extends StatelessWidget {
  const QueuePanel({super.key, required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => Material(
    color: Theme.of(context).colorScheme.surfaceContainerLow,
    clipBehavior: Clip.antiAlias,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(8),
      side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
    ),
    child: child,
  );
}

class QueueStatusBadge extends StatelessWidget {
  const QueueStatusBadge({super.key, required this.state});
  final Object? state;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final failed = [
      'failed',
      'interrupted',
      'blocked',
      'execution_unknown',
    ].contains(state);
    final done = state == 'completed';
    final color = failed
        ? colors.error
        : done
        ? colors.secondary
        : colors.onSurfaceVariant;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          failed
              ? Icons.error_outline
              : done
              ? Icons.check
              : state == 'running'
              ? Icons.play_circle_outline
              : Icons.schedule,
          size: 14,
          color: color,
        ),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            QueuePresentation.taskStatus(state),
            style: TextStyle(fontSize: 12, color: color),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}

/// The same compact native row is used by the live list and render tests.
class QueueTaskRow extends StatelessWidget {
  const QueueTaskRow({
    super.key,
    required this.task,
    required this.selected,
    required this.onTap,
    this.action,
  });
  final Map<String, dynamic> task;
  final bool selected;
  final VoidCallback onTap;
  final Widget? action;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: selected ? colors.primaryContainer : colors.surfaceContainerLow,
      child: InkWell(
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 64),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
          decoration: BoxDecoration(
            border: Border(
              left: BorderSide(
                color: selected ? colors.primary : Colors.transparent,
                width: 3,
              ),
              bottom: BorderSide(color: colors.outlineVariant),
            ),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Tooltip(
                      message: '${task['name']}',
                      child: Text(
                        '${task['name']}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 14),
                      ),
                    ),
                    LayoutBuilder(
                      builder: (context, bounds) {
                        final style = Theme.of(context).textTheme.bodySmall;
                        final updated = QueuePresentation.taskUpdated(task);
                        final scaler = MediaQuery.textScalerOf(context);
                        final measure = TextPainter(
                          text: TextSpan(text: updated, style: style),
                          textDirection: Directionality.of(context),
                          textScaler: scaler,
                        )..layout();
                        final inline =
                            bounds.maxWidth >=
                            measure.width + scaler.scale(80) + 12;
                        measure.dispose();
                        final metadata = Tooltip(
                          message:
                              '${task['project'] ?? '未提供项目'} · ${QueuePresentation.compactRequirements(task)}',
                          child: Text(
                            '${task['project'] ?? '未提供项目'} · ${QueuePresentation.compactRequirements(task)}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: style,
                          ),
                        );
                        final time = Text(updated, style: style);
                        return inline
                            ? Row(
                                children: [
                                  Expanded(child: metadata),
                                  const SizedBox(width: 12),
                                  time,
                                ],
                              )
                            : Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [metadata, time],
                              );
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 88,
                child: QueueStatusBadge(state: task['state']),
              ),
              if (action != null) ...[const SizedBox(width: 12), action!],
            ],
          ),
        ),
      ),
    );
  }
}

/// Body and tabs retain their independent scroll positions across polling.
class QueueDetailPane extends StatelessWidget {
  const QueueDetailPane({
    super.key,
    required this.task,
    required this.tab,
    required this.onTab,
    required this.onClose,
    required this.child,
  });
  final Map<String, dynamic> task;
  final int tab;
  final ValueChanged<int> onTab;
  final VoidCallback onClose;
  final Widget child;
  @override
  Widget build(BuildContext context) => ColoredBox(
    color: Theme.of(context).colorScheme.surfaceContainerLow,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 12, 12, 0),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '任务详情',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              IconButton(
                tooltip: '关闭详情',
                onPressed: onClose,
                icon: const Icon(Icons.close),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              QueueStatusBadge(state: task['state']),
              const SizedBox(height: 8),
              Text(
                '${task['name']}',
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 4),
              Text(
                '${task['project'] ?? ''}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  for (var i = 0; i < 3; i++)
                    Padding(
                      padding: const EdgeInsets.only(right: 16),
                      child: InkWell(
                        onTap: () => onTab(i),
                        child: Semantics(
                          selected: tab == i,
                          button: true,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              vertical: 10,
                              horizontal: 3,
                            ),
                            decoration: BoxDecoration(
                              border: Border(
                                bottom: BorderSide(
                                  color: tab == i
                                      ? Theme.of(context).colorScheme.primary
                                      : Colors.transparent,
                                  width: 2,
                                ),
                              ),
                            ),
                            child: Text(
                              const ['概览', '日志', '结果'][i],
                              style: TextStyle(
                                fontSize: 13,
                                color: tab == i
                                    ? Theme.of(context).colorScheme.onSurface
                                    : Theme.of(
                                        context,
                                      ).colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
              const Divider(),
            ],
          ),
        ),
        Expanded(child: child),
      ],
    ),
  );
}

class QueueLogView extends StatelessWidget {
  const QueueLogView({super.key, required this.label, required this.text});
  final String label, text;
  @override
  Widget build(BuildContext context) => QueuePanel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 16, right: 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              IconButton(
                tooltip: '复制日志',
                onPressed: () => Clipboard.setData(ClipboardData(text: text)),
                icon: const Icon(Icons.copy_outlined),
              ),
            ],
          ),
        ),
        const Divider(),
        SizedBox(
          height: 300,
          child: Scrollbar(
            child: SingleChildScrollView(
              key: PageStorageKey('log:$label'),
              padding: const EdgeInsets.all(16),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: SelectableText(
                  text,
                  style: const TextStyle(
                    fontFamily: 'Menlo',
                    fontFamilyFallback: ['Noto Sans Mono', 'monospace'],
                    fontSize: 12,
                    height: 19 / 12,
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

/// Expanded by default. Collapsing never hides the settings or other tools.
class QueueSidebar extends StatefulWidget {
  const QueueSidebar({
    super.key,
    required this.selected,
    required this.onSelect,
    required this.onSettings,
    required this.onMore,
    this.settingsOpen = false,
  });
  final int selected;
  final ValueChanged<int> onSelect;
  final VoidCallback onSettings, onMore;
  final bool settingsOpen;
  @override
  State<QueueSidebar> createState() => _QueueSidebarState();
}

class _QueueSidebarState extends State<QueueSidebar> {
  bool _collapsed = false;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    Widget item(String label, IconData icon, bool selected, VoidCallback tap) =>
        Tooltip(
          message: label,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
            child: Material(
              color: selected ? colors.surfaceContainerLow : Colors.transparent,
              borderRadius: BorderRadius.circular(7),
              child: ListTile(
                minTileHeight: 38,
                minLeadingWidth: 18,
                horizontalTitleGap: 12,
                contentPadding: EdgeInsets.symmetric(
                  horizontal: _collapsed ? 5 : 12,
                ),
                leading: Icon(
                  icon,
                  size: 18,
                  color: selected ? colors.onSurface : colors.onSurfaceVariant,
                ),
                title: _collapsed
                    ? null
                    : Text(label, style: const TextStyle(fontSize: 14)),
                selected: selected,
                onTap: tap,
              ),
            ),
          ),
        );
    return Container(
      width: _collapsed ? 64 : 208,
      decoration: BoxDecoration(
        color: colors.surfaceContainerLowest,
        border: Border(right: BorderSide(color: colors.outlineVariant)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 24),
          Padding(
            padding: EdgeInsets.symmetric(horizontal: _collapsed ? 7 : 16),
            child: Row(
              children: [
                if (!_collapsed)
                  Expanded(
                    child: FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'Inspire Queue',
                        style: const TextStyle(
                          fontFamily: 'Georgia',
                          fontSize: 22,
                        ),
                      ),
                    ),
                  ),
                IconButton(
                  tooltip: _collapsed ? '展开侧栏' : '收起侧栏',
                  onPressed: () => setState(() => _collapsed = !_collapsed),
                  icon: const Icon(Icons.view_sidebar_outlined),
                ),
              ],
            ),
          ),
          if (!_collapsed)
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 12, 24),
              child: Text(
                '个人计算工作台',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          Expanded(
            child: ListView(
              children: [
                item(
                  '总览',
                  Icons.grid_view_outlined,
                  !widget.settingsOpen && widget.selected == 0,
                  () => widget.onSelect(0),
                ),
                item(
                  '任务',
                  Icons.article_outlined,
                  !widget.settingsOpen && widget.selected == 1,
                  () => widget.onSelect(1),
                ),
                item(
                  '服务器',
                  Icons.dns_outlined,
                  !widget.settingsOpen && widget.selected == 2,
                  () => widget.onSelect(2),
                ),
                item(
                  '终端',
                  Icons.terminal_outlined,
                  !widget.settingsOpen && widget.selected == 3,
                  () => widget.onSelect(3),
                ),
                Tooltip(
                  message: '文件、分屏工作区与其他工具',
                  child: item(
                    '更多工具',
                    Icons.more_horiz,
                    !widget.settingsOpen && widget.selected > 3,
                    widget.onMore,
                  ),
                ),
              ],
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 24),
            child: Divider(),
          ),
          item(
            '设置',
            Icons.settings_outlined,
            widget.settingsOpen,
            widget.onSettings,
          ),
          const SizedBox(height: 12),
        ],
      ),
    );
  }
}
