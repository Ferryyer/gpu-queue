import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';

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
  const QueueStatusBadge({
    super.key,
    required this.state,
    this.compact = false,
  });
  final Object? state;
  final bool compact;
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
    return Tooltip(
      message: QueuePresentation.taskStatus(state),
      child: Semantics(
        label: QueuePresentation.taskStatus(state),
        excludeSemantics: true,
        child: Row(
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
                compact
                    ? QueuePresentation.compactTaskStatus(state)
                    : QueuePresentation.taskStatus(state),
                style: TextStyle(fontSize: 12, color: color),
              ),
            ),
          ],
        ),
      ),
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
          child: LayoutBuilder(
            builder: (context, bounds) {
              final scaler = MediaQuery.textScalerOf(context);
              final status = QueuePresentation.compactTaskStatus(task['state']);
              final statusText = TextPainter(
                text: TextSpan(
                  text: status,
                  style: DefaultTextStyle.of(
                    context,
                  ).style.copyWith(fontSize: 12),
                ),
                textDirection: Directionality.of(context),
                textScaler: scaler,
              )..layout();
              final statusWidth = statusText.width.ceilToDouble() + 22;
              statusText.dispose();
              final badge = SizedBox(
                width: statusWidth,
                child: QueueStatusBadge(state: task['state'], compact: true),
              );
              final name = Tooltip(
                message: '${task['name']}',
                child: Text(
                  '${task['name']}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 14),
                ),
              );
              final metadata = _QueueTaskMetadata(task: task);
              // Give text and actions room to grow with the system text size.
              // Narrow rows put the action below the metadata, never over it.
              final stacked =
                  bounds.maxWidth <
                  scaler.scale(200) +
                      statusWidth +
                      (action == null ? 12 : scaler.scale(100) + 24);
              if (stacked) {
                return Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    name,
                    metadata,
                    const SizedBox(height: 4),
                    Row(children: [badge, const Spacer(), ?action]),
                  ],
                );
              }
              return Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [name, metadata],
                    ),
                  ),
                  const SizedBox(width: 12),
                  badge,
                  if (action != null) ...[const SizedBox(width: 12), action!],
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

/// Resource requirements remain readable before project names or timestamps.
class _QueueTaskMetadata extends StatelessWidget {
  const _QueueTaskMetadata({required this.task});
  final Map<String, dynamic> task;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, bounds) {
      final style = Theme.of(context).textTheme.bodySmall;
      final project = Tooltip(
        message: '${task['project'] ?? '未提供项目'}',
        child: Text(
          '${task['project'] ?? '未提供项目'}',
          style: style,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
      );
      final resources = Text(
        QueuePresentation.compactRequirements(task),
        style: style,
      );
      final time = Tooltip(
        message: QueuePresentation.taskUpdated(task),
        child: Semantics(
          label: QueuePresentation.taskUpdated(task),
          excludeSemantics: true,
          child: Text(QueuePresentation.compactTaskUpdated(task), style: style),
        ),
      );
      // Measure the two pieces that must not be ellipsized. Project can use
      // the remaining space; at narrower widths the row grows vertically.
      final measure = TextPainter(
        text: TextSpan(
          text:
              '${QueuePresentation.compactRequirements(task)}'
              '${QueuePresentation.compactTaskUpdated(task)}',
          style: style,
        ),
        textDirection: Directionality.of(context),
        textScaler: MediaQuery.textScalerOf(context),
      )..layout();
      final inline = bounds.maxWidth >= measure.width + 110;
      measure.dispose();
      if (inline) {
        return Row(
          children: [
            Expanded(child: project),
            const SizedBox(width: 12),
            resources,
            const SizedBox(width: 12),
            time,
          ],
        );
      }
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(spacing: 12, runSpacing: 2, children: [resources, time]),
          project,
        ],
      );
    },
  );
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
    child: LayoutBuilder(
      builder: (context, bounds) {
        final compactHeader = bounds.maxHeight < 400;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ConstrainedBox(
              constraints: BoxConstraints(maxHeight: bounds.maxHeight * .4),
              child: SingleChildScrollView(
                key: PageStorageKey('${task['id']}:detail-header'),
                primary: false,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(24, 12, 12, 0),
                      child: Row(
                        children: [
                          Expanded(
                            child: Tooltip(
                              message: '${task['name']}',
                              child: Text(
                                compactHeader ? '${task['name']}' : '任务详情',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: compactHeader
                                    ? Theme.of(context).textTheme.bodyMedium
                                    : Theme.of(context).textTheme.bodySmall,
                              ),
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
                          if (!compactHeader) ...[
                            const SizedBox(height: 8),
                            Tooltip(
                              message: '${task['name']}',
                              child: Text(
                                '${task['name']}',
                                maxLines: 3,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.titleLarge,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${task['project'] ?? ''}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
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
                                          ? Theme.of(
                                              context,
                                            ).colorScheme.primary
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
                                        ? Theme.of(
                                            context,
                                          ).colorScheme.onSurface
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
        );
      },
    ),
  );
}

class QueueLogView extends StatefulWidget {
  const QueueLogView({super.key, required this.label, required this.text});
  final String label, text;
  @override
  State<QueueLogView> createState() => _QueueLogViewState();
}

class _QueueLogViewState extends State<QueueLogView> {
  final _vertical = ScrollController();
  final _horizontal = ScrollController();

  @override
  void dispose() {
    _vertical.dispose();
    _horizontal.dispose();
    super.dispose();
  }

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
                  widget.label,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              IconButton(
                tooltip: '复制日志',
                onPressed: () =>
                    Clipboard.setData(ClipboardData(text: widget.text)),
                icon: const Icon(Icons.copy_outlined),
              ),
            ],
          ),
        ),
        const Divider(),
        SizedBox(
          height: 300,
          child: ScrollConfiguration(
            behavior: ScrollConfiguration.of(
              context,
            ).copyWith(scrollbars: false),
            child: Scrollbar(
              controller: _vertical,
              child: Scrollbar(
                controller: _horizontal,
                scrollbarOrientation: ScrollbarOrientation.bottom,
                notificationPredicate: (notification) =>
                    notification.metrics.axis == Axis.horizontal,
                child: SingleChildScrollView(
                  key: PageStorageKey(
                    'log:${widget.key ?? widget.label}:vertical',
                  ),
                  controller: _vertical,
                  primary: false,
                  padding: const EdgeInsets.all(16),
                  child: SingleChildScrollView(
                    key: PageStorageKey(
                      'log:${widget.key ?? widget.label}:horizontal',
                    ),
                    controller: _horizontal,
                    primary: false,
                    scrollDirection: Axis.horizontal,
                    child: SelectableText(
                      widget.text,
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
                    child: Text(
                      'GPU Queue',
                      style: const TextStyle(
                        fontFamily: 'Georgia',
                        fontSize: 22,
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
                Tooltip(
                  message: '终端、文件与其他工具',
                  child: item(
                    '更多工具',
                    Icons.more_horiz,
                    !widget.settingsOpen && widget.selected > 2,
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
