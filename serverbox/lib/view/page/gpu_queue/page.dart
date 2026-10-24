import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/controller.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';
import 'package:server_box/core/route.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/store.dart';
import 'package:server_box/data/ssh/terminal_source.dart';
import 'package:server_box/view/page/server/detail/view.dart';
import 'package:server_box/view/page/ssh/page/page.dart';
import 'package:server_box/view/page/storage/sftp.dart';

/// Native task workspace. Terminal and files are pushed on this tab's own
/// navigator, so Back returns to the same task, filters, focus and scroll.
class GpuQueuePage extends ConsumerStatefulWidget {
  const GpuQueuePage({super.key, this.overview = false, this.serverFilter});
  final bool overview;
  final String? serverFilter;
  @override
  ConsumerState<GpuQueuePage> createState() => _GpuQueuePageState();
}

class _GpuQueuePageState extends ConsumerState<GpuQueuePage>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;
  String? _selected;
  String _query = '', _filter = 'all';
  final _listScroll = ScrollController();
  final _detailScroll = ScrollController();
  @override
  void dispose() {
    _listScroll.dispose();
    _detailScroll.dispose();
    super.dispose();
  }

  String _identity(Spi spi) => jsonEncode([
    spi.sshOn?.ip,
    spi.sshOn?.port,
    spi.sshOn?.user,
    spi.sshOn?.jumpIds,
    spi.sshOn?.proxyCommand,
  ]);
  Map<String, dynamic> _bindings() {
    try {
      return jsonDecode(Stores.setting.gpuQueueBindings.fetch())
          as Map<String, dynamic>;
    } catch (_) {
      return {};
    }
  }

  Spi? _target(
    String service,
    Map<String, dynamic> task,
    Map<String, Spi> servers,
  ) {
    final instance = QueueTarget.instance(task);
    if (instance == null || instance.isEmpty) return null;
    final binding = _bindings()[QueueTarget.key(service, instance)];
    if (binding is! Map) return null;
    final spi = servers[binding['server']];
    final origin = servers[service];
    return spi != null &&
            origin != null &&
            spi.sshOn != null &&
            QueueTarget.bindingMatches(
              binding,
              _identity(spi),
              _identity(origin),
            )
        ? spi
        : null;
  }

  Future<void> _bind(
    String service,
    Map<String, dynamic> task,
    Map<String, Spi> servers,
  ) async {
    final instance = QueueTarget.instance(task);
    if (instance == null || instance.isEmpty) return;
    final chosen = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: Text('关联实例 $instance'),
        children: [
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('请选择此实例实际所属的 SSH 配置。终端、工作目录和产物都将使用该服务器；不会按名称或主机猜测。'),
          ),
          for (final spi in servers.values.where((s) => s.sshOn != null))
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, spi.id),
              child: Text(
                '${spi.name}\n${spi.sshOn!.user}@${spi.sshOn!.ip}:${spi.sshOn!.port}',
              ),
            ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, ''),
            child: const Text('解除关联'),
          ),
        ],
      ),
    );
    if (chosen == null || !mounted) return;
    final bindings = _bindings(), key = QueueTarget.key(service, instance);
    if (chosen.isEmpty) {
      bindings.remove(key);
    } else {
      final spi = servers[chosen], origin = servers[service];
      if (spi == null || origin == null) return;
      bindings[key] = {
        'server': chosen,
        'identity': _identity(spi),
        'origin': _identity(origin),
      };
    }
    Stores.setting.gpuQueueBindings.put(jsonEncode(bindings));
    if (mounted) setState(() {});
  }

  void _message(Object text) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$text')));
    }
  }

  Future<void> _act(
    QueueSession queue,
    Map<String, dynamic> task,
    String action,
  ) async {
    if (action == 'stop') {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('停止这个任务？'),
          content: Text(
            '${task['name']}\n\n结束当前步骤和子进程，后续步骤不再执行，已有产物保留。停止不等于释放 GPU；再次执行需要提交新版本并重新授权。',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('保留任务'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认停止'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    try {
      await queue.action('/api/tasks/${task['id']}/$action', {
        'digest': task['digest'],
      });
      _message(action == 'start' ? '已保存这一版的启动授权' : '停止请求已保存，等待服务器确认');
    } catch (e) {
      _message(e);
    }
  }

  Future<void> _move(
    QueueSession queue,
    Map<String, dynamic> task,
    int direction,
  ) async {
    final ids = queue.tasks
        .where(_reorderable)
        .map((t) => t['id'] as String)
        .toList();
    final index = ids.indexOf(task['id']), next = index + direction;
    if (index < 0 || next < 0 || next >= ids.length) return;
    ids.insert(next, ids.removeAt(index));
    try {
      await queue.action('/api/queue/reorder', {
        'ids': ids,
        'revision': queue.revision,
      });
    } catch (e) {
      _message(e);
    }
  }

  static bool _reorderable(Map<String, dynamic> t) =>
      t['approved_at'] != null &&
      t['claimed_at'] == null &&
      const [
        'queued',
        'waiting_gpu',
        'checking_resources',
      ].contains(t['state']);
  static const _ended = [
    'completed',
    'stopped',
    'cancelled',
    'failed',
    'interrupted',
  ];
  static const _labels = {
    'ready': '待启动',
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
  };
  String _status(Map<String, dynamic> task) =>
      _labels[task['state']] ?? '${task['state']}';

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final servers = ref.watch(serversProvider).servers;
    return ValueListenableBuilder(
      valueListenable: Stores.setting.gpuQueueServer.listenable(),
      builder: (context, _, _) {
        final service = Stores.setting.gpuQueueServer.fetch();
        final available = servers.values.where((s) => s.sshOn != null).toList();
        return Scaffold(
          appBar: AppBar(
            title: Text(
              widget.overview
                  ? '总览'
                  : widget.serverFilter != null
                  ? '关联任务'
                  : '任务',
            ),
          ),
          body: Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 8,
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: DropdownButton<String>(
                        isExpanded: true,
                        value: available.any((s) => s.id == service)
                            ? service
                            : null,
                        hint: const Text('选择任务服务所在的已有服务器'),
                        items: [
                          for (final spi in available)
                            DropdownMenuItem(
                              value: spi.id,
                              child: Text(spi.name),
                            ),
                        ],
                        onChanged: (id) {
                          if (id != null) Stores.setting.gpuQueueServer.put(id);
                        },
                      ),
                    ),
                  ],
                ),
              ),
              if (available.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('请先在「服务器」添加或导入 SSH 配置。密钥与密码继续使用原有安全存储。'),
                ),
              if (available.isNotEmpty && !servers.containsKey(service))
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('选择运行个人任务服务的服务器。应用将复用其 SSH 会话，无需另建网页转发。'),
                ),
              if (servers.containsKey(service) &&
                  servers[service]!.sshOn != null)
                Expanded(child: _workspace(service, servers)),
            ],
          ),
        );
      },
    );
  }

  Widget _workspace(String service, Map<String, Spi> servers) {
    final queue = ref.watch(queueControllerProvider(service));
    final ssh = ref.watch(serverProvider(service)).client;
    return ListenableBuilder(
      listenable: queue,
      builder: (context, _) {
        final connected = queue.connected && ssh != null && !ssh.isClosed;
        final tasks = queue.tasks.where((task) {
          if (widget.serverFilter != null &&
              _target(service, task, servers)?.id != widget.serverFilter) {
            return false;
          }
          if (_filter == 'ready' && task['state'] != 'ready') return false;
          if (_filter == 'history' && !_ended.contains(task['state'])) {
            return false;
          }
          return '${task['name']} ${task['id']} ${task['project']}'
              .toLowerCase()
              .contains(_query.toLowerCase());
        }).toList();
        final task = queue.tasks.where((t) => t['id'] == _selected).firstOrNull;
        return Focus(
          onKeyEvent: (node, event) {
            final keys = HardwareKeyboard.instance;
            if (event is! KeyDownEvent ||
                event.logicalKey != LogicalKeyboardKey.tab ||
                !keys.isShiftPressed ||
                keys.isControlPressed ||
                keys.isAltPressed ||
                keys.isMetaPressed) {
              return KeyEventResult.ignored;
            }
            if (FocusManager.instance.primaryFocus?.context
                        ?.findAncestorWidgetOfExactType<EditableText>() !=
                    null ||
                ModalRoute.of(context)?.isCurrent != true) {
              return KeyEventResult.ignored;
            }
            queue.setAuto(!queue.auto);
            return KeyEventResult.handled;
          },
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      'SSH · ${ssh != null && !ssh.isClosed ? '可用' : '未连接'}',
                    ),
                    Text(
                      '任务服务 · ${queue.loading
                          ? '同步中'
                          : connected
                          ? '可用'
                          : '不可用'}',
                    ),
                    Text(
                      'GPU 采样 · ${queue.resources.any((r) => QueueTarget.fresh(r, DateTime.now(), connected: connected)) ? '实时' : '暂无实时读数'}',
                    ),
                    OutlinedButton(
                      onPressed: queue.loading || queue.acting
                          ? null
                          : () => queue.refresh(connect: true),
                      child: const Text('连接 / 重试'),
                    ),
                    OutlinedButton(
                      onPressed: () => queue.setAuto(!queue.auto),
                      child: Text(
                        '${queue.auto ? 'Auto' : 'Edit'} mode · ⇧Tab',
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 8,
                ),
                child: Text(
                  queue.auto
                      ? '仅监看已授权队列；新任务仍需切回 Edit 并点击开始。'
                      : '提交、连接与切换模式均不会授权任务。点击开始才会执行这一版。',
                ),
              ),
              if (queue.error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          '${queue.error}\n上次数据 · 非实时',
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                      IconButton(
                        tooltip: '复制错误',
                        onPressed: () => Clipboard.setData(
                          ClipboardData(text: queue.error!),
                        ),
                        icon: const Icon(Icons.copy),
                      ),
                    ],
                  ),
                ),
              if (queue.loading) const LinearProgressIndicator(),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, bounds) {
                    final wide = bounds.maxWidth >= 850;
                    final list = Column(
                      children: [
                        if (widget.overview)
                          Padding(
                            padding: const EdgeInsets.all(20),
                            child: Text(
                              '每个实验，都有进展。\n${queue.tasks.where((t) => t['state'] == 'ready').length} 个待启动 · ${queue.tasks.where((t) => t['state'] == 'running').length} 个运行中',
                              style: Theme.of(context).textTheme.headlineSmall
                                  ?.copyWith(
                                    fontFamily: 'Georgia',
                                    fontFamilyFallback: const [
                                      'Songti SC',
                                      'Noto Serif CJK SC',
                                    ],
                                  ),
                            ),
                          ),
                        Padding(
                          padding: const EdgeInsets.all(12),
                          child: TextField(
                            decoration: const InputDecoration(
                              labelText: '搜索任务',
                              prefixIcon: Icon(Icons.search),
                            ),
                            onChanged: (value) =>
                                setState(() => _query = value),
                          ),
                        ),
                        Wrap(
                          spacing: 8,
                          children: [
                            for (final entry in {
                              'all': '全部',
                              'ready': '待启动',
                              'history': '已结束',
                            }.entries)
                              ChoiceChip(
                                label: Text(entry.value),
                                selected: _filter == entry.key,
                                onSelected: (_) =>
                                    setState(() => _filter = entry.key),
                              ),
                          ],
                        ),
                        Expanded(
                          child: tasks.isEmpty
                              ? Center(
                                  child: Text(
                                    queue.loading
                                        ? '正在加载…'
                                        : widget.serverFilter != null
                                        ? '暂无已明确关联此服务器的任务。\n请在任务详情关联实例。'
                                        : '暂无匹配任务。\n通过 gpuq submit 提交后在这里点击开始。',
                                  ),
                                )
                              : ListView.builder(
                                  controller: _listScroll,
                                  itemCount: tasks.length,
                                  itemBuilder: (context, index) {
                                    final task = tasks[index];
                                    return ListTile(
                                      key: ValueKey(task['id']),
                                      selected: _selected == task['id'],
                                      title: Text('${task['name']}'),
                                      subtitle: Text(
                                        '${_status(task)} · ${task['project'] ?? ''}\n${task['id']}',
                                      ),
                                      isThreeLine: true,
                                      trailing: const Icon(Icons.chevron_right),
                                      onTap: () {
                                        setState(() => _selected = task['id']);
                                        if (!wide) {
                                          Navigator.of(context).push(
                                            MaterialPageRoute(
                                              builder: (_) => _MobileDetail(
                                                queue: queue,
                                                taskId: task['id'],
                                                buildDetail: (t) => _detail(
                                                  service,
                                                  queue,
                                                  t,
                                                  servers,
                                                  mobile: true,
                                                ),
                                              ),
                                            ),
                                          );
                                        }
                                      },
                                    );
                                  },
                                ),
                        ),
                        ExpansionTile(
                          title: const Text('服务器与 GPU · 展开监控'),
                          children: [
                            SizedBox(
                              height: 180,
                              child: ListView(
                                children: [
                                  if (queue.resources.isEmpty)
                                    const ListTile(title: Text('尚无 GPU 实例')),
                                  for (final resource in queue.resources)
                                    ListTile(
                                      title: Text(
                                        '${resource['id']} · ${QueueTarget.fresh(resource, DateTime.now(), connected: connected) ? '实时' : '上次采样 · 非实时'}',
                                      ),
                                      subtitle: Text(
                                        '采样时间 ${resource['telemetry']?['at'] ?? '未知'}\n${QueueTarget.fresh(resource, DateTime.now(), connected: connected) ? jsonEncode(resource['telemetry']?['gpus']) : '实时指标不可用'}',
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ],
                    );
                    return wide
                        ? Row(
                            children: [
                              SizedBox(width: 360, child: list),
                              const VerticalDivider(width: 1),
                              Expanded(
                                child: task == null
                                    ? const Center(
                                        child: Text('选择一个任务，查看步骤与结果。'),
                                      )
                                    : _detail(service, queue, task, servers),
                              ),
                            ],
                          )
                        : list;
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _detail(
    String service,
    QueueSession queue,
    Map<String, dynamic> task,
    Map<String, Spi> servers, {
    bool mobile = false,
  }) {
    servers = ref.read(serversProvider).servers;
    final target = _target(service, task, servers),
        directory = QueueTarget.directory(task);
    final resource = queue.resources
        .where((r) => r['id'] == QueueTarget.instance(task))
        .firstOrNull;
    final fresh =
        resource != null &&
        QueueTarget.fresh(resource, DateTime.now(), connected: queue.connected);
    final enabled = queue.connected && !queue.acting && !queue.loading;
    final steps = (task['step_records'] as List? ?? [])
        .cast<Map<String, dynamic>>();
    final names = task['steps'] as List? ?? [];
    return ListView(
      key: PageStorageKey(task['id']),
      controller: mobile ? null : _detailScroll,
      padding: const EdgeInsets.all(24),
      children: [
        Text(_status(task), style: Theme.of(context).textTheme.labelLarge),
        Text(
          '${task['name']}',
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
            fontFamily: 'Georgia',
            fontFamilyFallback: const ['Songti SC', 'Noto Serif CJK SC'],
          ),
        ),
        SelectableText(
          '${task['description'] ?? ''}\n${task['id']} · 固定版本 ${task['version'] ?? task['digest']}\n授权：${task['approved_at'] ?? '等待点击开始'}',
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (task['state'] == 'ready')
              FilledButton(
                onPressed: enabled && !queue.auto
                    ? () => _act(queue, task, 'start')
                    : null,
                child: const Text('开始这一版任务'),
              ),
            if (!_ended.contains(task['state']))
              OutlinedButton(
                onPressed: enabled && task['state'] != 'stopping'
                    ? () => _act(queue, task, 'stop')
                    : null,
                child: Text(task['state'] == 'stopping' ? '等待停止确认…' : '停止任务'),
              ),
            if (_reorderable(task)) ...[
              IconButton(
                tooltip: '队列向前移动',
                onPressed: enabled && !queue.auto
                    ? () => _move(queue, task, -1)
                    : null,
                icon: const Icon(Icons.arrow_upward),
              ),
              IconButton(
                tooltip: '队列向后移动',
                onPressed: enabled && !queue.auto
                    ? () => _move(queue, task, 1)
                    : null,
                icon: const Icon(Icons.arrow_downward),
              ),
            ],
          ],
        ),
        if (task['failureReason'] != null)
          SelectableText(
            '${task['failureReason']}',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        if (task['phase'] != null) Text('${task['phase']}'),
        const Divider(height: 32),
        SelectableText(
          'GPU 实例：${QueueTarget.instance(task) ?? '尚未分配'}\n服务器：${target?.name ?? '尚未关联服务器'}\n工作目录：${directory ?? '等待执行端提供'}',
        ),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            TextButton(
              onPressed: QueueTarget.instance(task) == null
                  ? null
                  : () => _bind(service, task, servers),
              child: const Text('关联 / 更改服务器'),
            ),
            OutlinedButton(
              onPressed: target == null
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) =>
                            ServerDetailPage(args: SpiRequiredArgs(target)),
                      ),
                    ),
              child: const Text('服务器 / GPU'),
            ),
            OutlinedButton(
              onPressed: target == null
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => SSHPage(
                          args: SshPageArgs(
                            source: ServerSource(target),
                            initCmd: directory == null
                                ? null
                                : 'cd -- ${QueueProtocol.quote(directory)}',
                          ),
                        ),
                      ),
                    ),
              child: const Text('SSH 终端'),
            ),
            OutlinedButton(
              onPressed: target == null || directory == null
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => SftpPage(
                          args: SftpPageArgs(spi: target, initPath: directory),
                        ),
                      ),
                    ),
              child: const Text('工作目录 / SFTP'),
            ),
          ],
        ),
        if (resource != null)
          SelectableText(
            'GPU 采样：${fresh ? '实时' : '上次采样 · 非实时'} · ${resource['telemetry']?['at'] ?? '未知时间'}\n${fresh ? jsonEncode(resource['telemetry']?['gpus']) : '实时指标不可用'}',
          ),
        const Divider(height: 32),
        Text('执行步骤与日志', style: Theme.of(context).textTheme.titleLarge),
        for (var index = 0; index < names.length; index++)
          ExpansionTile(
            key: PageStorageKey('${task['id']}:$index'),
            title: Text('${index + 1}. ${names[index]}'),
            subtitle: Text(
              index < steps.length ? '${steps[index]['state']}' : '等待执行',
            ),
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: SelectableText(
                    index < steps.length
                        ? '${steps[index]['log'] ?? '暂无日志'}'
                        : '暂无日志',
                    style: const TextStyle(fontFamily: 'monospace'),
                  ),
                ),
              ),
            ],
          ),
        if (task['entry_log'] != null) SelectableText('${task['entry_log']}'),
        if (task['stop_log'] != null)
          SelectableText('停止日志：${task['stop_log']}'),
        const SizedBox(height: 24),
        Text('结果文件', style: Theme.of(context).textTheme.titleLarge),
        if (steps.every((s) => (s['outputs'] as List? ?? []).isEmpty))
          const Text('尚无已验证产物。成功步骤的结果将出现在这里。'),
        for (final step in steps)
          for (final file in step['outputs'] as List? ?? [])
            ListTile(
              title: Text('${file['name']}'),
              subtitle: SelectableText(
                '${file['path']} · ${file['size']} bytes',
              ),
              trailing: IconButton(
                tooltip: '复制路径',
                onPressed: () =>
                    Clipboard.setData(ClipboardData(text: '${file['path']}')),
                icon: const Icon(Icons.copy),
              ),
              onTap:
                  target == null ||
                      file['path'] is! String ||
                      !(file['path'] as String).startsWith('/')
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => SftpPage(
                          args: SftpPageArgs(
                            spi: target,
                            initPath: (file['path'] as String).substring(
                              0,
                              (file['path'] as String).lastIndexOf('/'),
                            ),
                          ),
                        ),
                      ),
                    ),
            ),
        const SizedBox(height: 24),
        Text('准备检查与事件', style: Theme.of(context).textTheme.titleLarge),
        for (final line in [
          ...(task['checks'] as List? ?? []),
          ...(task['events'] as List? ?? []),
        ])
          Text('· $line'),
      ],
    );
  }
}

class _MobileDetail extends StatelessWidget {
  const _MobileDetail({
    required this.queue,
    required this.taskId,
    required this.buildDetail,
  });
  final QueueSession queue;
  final String taskId;
  final Widget Function(Map<String, dynamic>) buildDetail;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: queue,
    builder: (context, _) {
      final task = queue.tasks.where((t) => t['id'] == taskId).firstOrNull;
      return Scaffold(
        appBar: AppBar(title: const Text('任务详情')),
        body: task == null
            ? const Center(child: Text('此任务已不在当前快照中'))
            : buildDetail(task),
      );
    },
  );
}
