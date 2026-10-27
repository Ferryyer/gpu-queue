import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/controller.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';
import 'package:server_box/core/route.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/store.dart';
import 'package:server_box/data/ssh/terminal_source.dart';
import 'package:server_box/view/page/gpu_queue/resource.dart';
import 'package:server_box/view/page/gpu_queue/workspace.dart';
import 'package:server_box/view/page/server/detail/view.dart';
import 'package:server_box/view/page/server/edit/edit.dart';
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
  String _query = '', _filter = 'all', _sort = 'latest';
  int _detailTab = 0;
  final _search = TextEditingController();
  final _listScroll = ScrollController();
  @override
  void initState() {
    super.initState();
    if (widget.overview) _sort = 'attention';
  }

  void _guide() => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('员工接入指南'),
      content: const SingleChildScrollView(child: SelectableText(
        '① 请管理员开通个人 CPU 账号，取得自己的 SSH 连接信息。不要导入其他同事的密钥或应用数据库。\n\n'
        '② 在「服务器」添加或导入自己的连接；此处选择 CPU 上的任务服务，不是临时 GPU 实例。\n\n'
        '③ 让 Agent 阅读发布包中的 EMPLOYEE-SETUP.md，在本人 HOME 安装个人服务，完成本人飞书授权。已有服务无需重复安装。\n\n'
        '④ 点击连接诊断，确认服务账号与你的 SSH 用户一致。连接成功后让 Agent 使用 gpuq submit 准备任务；准备完成不会自动占卡。\n\n'
        '⑤ 在任务详情核对资源和版本，点击开始。失败时可复制诊断交给 Agent，修复后提交新版本。\n\n'
        '在线指南：https://github.com/Ferryyer/gpu-queue/blob/v2.0.2007/docs/EMPLOYEE-SETUP.md',
      )),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('知道了'))],
    ),
  );

  void _policy(QueueSession queue) => showDialog<void>(
                  context: context,
                  builder: (context) => ListenableBuilder(
                    listenable: queue,
                    builder: (context, _) => AlertDialog(
                      title: const Text('队列策略与连接状态'),
                      content: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SwitchListTile(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('自动监看已授权队列'),
                            value: queue.auto,
                            onChanged: queue.setAuto,
                          ),
                          const Text('仅监看已授权队列，不授权新任务。关闭后可手动点击开始或调整顺序。'),
                        ],
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('关闭'),
                        ),
                      ],
                    ),
                  ),
                );

  Future<void> _diagnostics(String service, QueueSession queue) async {
    unawaited(queue.diagnose());
    await showDialog<void>(context: context, builder: (context) => ListenableBuilder(
      listenable: queue,
      builder: (context, _) {
        final server = ref.read(serverProvider(service));
        final sshReady = server.client != null && !server.client!.isClosed;
        final heartbeat = queue.hasSnapshot ? queue.snapshot['heartbeat'] : null;
        final at = heartbeat is Map ? QueuePresentation.taskTime(heartbeat['at'] ?? heartbeat['updated_at']) : null;
        final age = at == null ? null : DateTime.now().toUtc().difference(at).inSeconds;
        final heartbeatFresh = age != null && age >= -5 && age < 120;
        final schedulerError = heartbeat is Map ? heartbeat['error'] : null;
        final schedulerReady = heartbeatFresh && schedulerError == null;
        final owner = queue.health?['owner'];
        final ownerMatches = owner != null && owner == server.spi.sshOn?.user;
        return AlertDialog(
          title: const Text('连接诊断'),
          content: SizedBox(width: 480, child: SingleChildScrollView(child: Column(
            mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('1 · SSH 连接：${sshReady ? '已连接' : '未连接'}'),
              Text('2 · 个人任务服务：${queue.diagnosing ? '检查中…' : queue.health == null ? '未确认' : '已响应'}'),
              if (owner != null) Text('服务账号：$owner · ${ownerMatches ? '与 SSH 用户一致' : '与 SSH 用户不一致，请核对连接'}'),
              Text('3 · 调度心跳：${schedulerReady ? '正常' : at == null ? '未收到' : !heartbeatFresh ? '已过期' : '在线，但处理任务时出错'}'),
              Text('最近同步：${queue.sampledAt?.toLocal().toString().split('.').first ?? '尚未成功同步'}'),
              const SizedBox(height: 16),
              Text(!sshReady ? '先连接个人 CPU 服务器；检查网络、SSH 配置和主机指纹。'
                : queue.health == null ? 'SSH 可用时，任务服务可能尚未安装或未启动。按员工指南检查个人服务，切勿重复提交任务。'
                : !heartbeatFresh ? '任务网页能响应，但调度器没有新鲜心跳。请在本人 CPU 终端检查 mf-services status。'
                : !schedulerReady ? '调度器仍在线，但最近处理发生错误。请检查本人飞书授权、平台回执与个人服务日志；不要重复提交任务。'
                : '连接链路正常。等待 GPU 时以平台回执为准，不会自动重复启动任务。'),
              if (queue.diagnosticError != null || queue.error != null) ...[
                const SizedBox(height: 12),
                SelectableText(queue.diagnosticError ?? queue.error!),
              ],
            ],
          ))),
          actions: [
            TextButton(onPressed: _guide, child: const Text('接入指南')),
            TextButton(onPressed: queue.diagnosing ? null : () => queue.diagnose(), child: const Text('重新检查')),
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('关闭')),
          ],
        );
      },
    ));
  }

  @override
  void dispose() {
    _search.dispose();
    _listScroll.dispose();
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
        title: const Text('关联访问服务器'),
        children: [
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('请选择能访问该任务目录的个人 SSH 服务器。可选择 GPU 实例，或能访问共享 HOME 的个人 CPU。此关联决定终端和文件访问目标，不代表 GPU 实际所在主机。'),
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
  Widget _serverSelector(String service, Map<String, Spi> servers) => SizedBox(
    width: MediaQuery.sizeOf(context).width < 500 ? 120 : MediaQuery.sizeOf(context).width < 1000 ? 150 : 204,
    child: DropdownButtonFormField<String>(
      key: ValueKey(service),
      initialValue: servers[service]?.sshOn != null ? service : null,
      isExpanded: true,
      decoration: const InputDecoration(
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      ),
      hint: const Text('选择任务服务', style: TextStyle(fontSize: 13)),
      items: [
        for (final spi in servers.values.where((s) => s.sshOn != null))
          DropdownMenuItem(
            value: spi.id,
            child: Text(
              spi.name,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 13),
            ),
          ),
      ],
      onChanged: (id) {
        if (id == null) return;
        setState(() {
          _selected = null;
          _detailTab = 0;
        });
        Stores.setting.gpuQueueServer.put(id);
      },
    ),
  );

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final servers = ref.watch(serversProvider).servers;
    return ValueListenableBuilder(
      valueListenable: Stores.setting.gpuQueueServer.listenable(),
      builder: (context, _, _) {
        final service = Stores.setting.gpuQueueServer.fetch();
        if (servers[service]?.sshOn != null) {
          return _workspace(service, servers);
        }
        return Scaffold(
          appBar: AppBar(
            title: const Text('任务'),
            actions: [
              _serverSelector(service, servers),
              const SizedBox(width: 24),
            ],
          ),
          body: QueueWelcome(
            hasServers: servers.values.any((s) => s.sshOn != null),
            onAdd: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ServerEditPage())),
            onGuide: _guide,
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
        final connected = queue.hasSnapshot && queue.connected && ssh != null && !ssh.isClosed;
        final sshAvailable = ssh != null && !ssh.isClosed;
        final fresh = queue.resources.any(
          (r) => QueueTarget.fresh(r, DateTime.now(), connected: connected),
        );
        final tasks = queue.tasks.where((task) {
          if (widget.serverFilter != null &&
              _target(service, task, servers)?.id != widget.serverFilter) {
            return false;
          }
          if (!QueuePresentation.matches(task, _filter)) return false;
          return '${task['name']} ${task['id']} ${task['project']}'
              .toLowerCase()
              .contains(_query.toLowerCase());
        }).toList();
        if (_sort == 'name') {
          tasks.sort((a, b) => '${a['name']}'.compareTo('${b['name']}'));
        } else {
          int timestamp(Map<String, dynamic> t) =>
              QueuePresentation.taskSortTime(t)?.millisecondsSinceEpoch ?? 0;

          int priority(Map<String, dynamic> t) => QueuePresentation.attentionStates.contains(t['state']) ? 0
              : t['state'] == 'ready' ? 1 : QueuePresentation.runningStates.contains(t['state']) ? 2
              : QueuePresentation.waitingStates.contains(t['state']) ? 3 : 4;
          tasks.sort((a, b) {
            final group = _sort == 'attention' ? priority(a).compareTo(priority(b)) : 0;
            return group != 0 ? group : timestamp(b).compareTo(timestamp(a));
          });
        }
        final task = queue.tasks.where((t) => t['id'] == _selected).firstOrNull;
        return Scaffold(
          appBar: AppBar(
            title: Text(
              widget.overview
                  ? '总览'
                  : widget.serverFilter != null
                  ? '关联任务'
                  : '任务',
            ),
            actions: [
              _serverSelector(service, servers),
              const SizedBox(width: 16),
              Tooltip(
                message:
                    'SSH：${sshAvailable ? '已连接' : '未连接'}\n任务服务：${connected ? '已连接' : '不可用'}\nGPU 采样：${fresh ? '实时' : '暂无数据'}',
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      connected
                          ? Icons.check_circle_outline
                          : Icons.error_outline,
                      size: 14,
                      color: connected
                          ? Theme.of(context).colorScheme.secondary
                          : Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: 6),
                    if (MediaQuery.sizeOf(context).width >= 1000)
                      Text(
                        connected
                            ? '已连接'
                            : queue.loading
                            ? '连接中'
                            : '连接失败',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                  ],
                ),
              ),
              IconButton(
                tooltip: '重试连接',
                onPressed: queue.loading || queue.acting
                    ? null
                    : () => queue.refresh(connect: true),
                icon: const Icon(Icons.refresh),
              ),
              if (MediaQuery.sizeOf(context).width < 900)
                PopupMenuButton<String>(
                  tooltip: '连接与帮助',
                  onSelected: (value) {
                    if (value == 'diagnose') _diagnostics(service, queue);
                    if (value == 'guide') _guide();
                    if (value == 'policy') _policy(queue);
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'diagnose', child: Text('连接诊断')),
                    PopupMenuItem(value: 'guide', child: Text('员工接入指南')),
                    PopupMenuItem(value: 'policy', child: Text('队列策略')),
                  ],
                )
              else ...[
              IconButton(
                tooltip: '连接诊断',
                onPressed: () => _diagnostics(service, queue),
                icon: const Icon(Icons.health_and_safety_outlined),
              ),
              IconButton(
                tooltip: '员工接入指南',
                onPressed: _guide,
                icon: const Icon(Icons.help_outline),
              ),
              IconButton(
                tooltip: '队列策略与连接状态',
                onPressed: () => _policy(queue),
                icon: const Icon(Icons.tune),
              ),
              ],
              const SizedBox(width: 12),
            ],
          ),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Divider(),
              if (queue.error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 8,
                  ),
                  child: Row(
                    children: [
                      Icon(
                        Icons.error_outline,
                        size: 16,
                        color: Theme.of(context).colorScheme.error,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          queue.hasSnapshot ? '连接中断 · 显示上次快照（非实时） · ${queue.sampledAt?.toLocal().toString().split('.').first ?? ''}' : '尚未连接个人任务服务 · 请连接服务器或查看接入指南',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                      TextButton(
                        onPressed: () => showDialog<void>(
                          context: context,
                          builder: (context) => AlertDialog(
                            title: const Text('连接错误'),
                            content: SelectableText(queue.error!),
                            actions: [
                              TextButton(
                                onPressed: () => Clipboard.setData(
                                  ClipboardData(text: queue.error!),
                                ),
                                child: const Text('复制错误'),
                              ),
                              TextButton(
                                onPressed: () => Navigator.pop(context),
                                child: const Text('关闭'),
                              ),
                            ],
                          ),
                        ),
                        child: const Text('查看错误'),
                      ),
                    ],
                  ),
                ),
              SizedBox(
                height: 2,
                child: queue.loading
                    ? const LinearProgressIndicator(minHeight: 2)
                    : null,
              ),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, bounds) {
                    final wide = bounds.maxWidth >= 850;
                    final showDetail = wide && task != null;
                    final list = Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: TextField(
                                  controller: _search,
                                  style: const TextStyle(fontSize: 13),
                                  decoration: InputDecoration(
                                    hintText: '搜索任务或项目',
                                    prefixIcon: const Icon(
                                      Icons.search,
                                      size: 18,
                                    ),
                                    suffixIcon: _query.isEmpty
                                        ? null
                                        : IconButton(
                                            tooltip: '清除搜索',
                                            onPressed: () {
                                              _search.clear();
                                              setState(() => _query = '');
                                            },
                                            icon: const Icon(
                                              Icons.close,
                                              size: 16,
                                            ),
                                          ),
                                  ),
                                  onChanged: (value) =>
                                      setState(() => _query = value),
                                ),
                              ),
                              const SizedBox(width: 12),
                              DropdownButton<String>(
                                value: _filter,
                                underline: const SizedBox.shrink(),
                                items: [
                                  for (final e in const {
                                    'all': '所有状态',
                                    'ready': '待开始',
                                    'waiting': '等待资源',
                                    'running': '运行中',
                                    'failed': '需要处理',
                                    'history': '已结束',
                                  }.entries)
                                    DropdownMenuItem(
                                      value: e.key,
                                      child: Text(
                                        e.value,
                                        style: const TextStyle(fontSize: 13),
                                      ),
                                    ),
                                ],
                                onChanged: (value) =>
                                    setState(() => _filter = value!),
                              ),
                              const SizedBox(width: 12),
                              DropdownButton<String>(
                                value: _sort,
                                underline: const SizedBox.shrink(),
                                items: const [
                                  DropdownMenuItem(value: 'attention', child: Text('待办优先', style: TextStyle(fontSize: 13))),
                                  DropdownMenuItem(
                                    value: 'latest',
                                    child: Text(
                                      '最新',
                                      style: TextStyle(fontSize: 13),
                                    ),
                                  ),
                                  DropdownMenuItem(
                                    value: 'name',
                                    child: Text(
                                      '名称',
                                      style: TextStyle(fontSize: 13),
                                    ),
                                  ),
                                ],
                                onChanged: (value) =>
                                    setState(() => _sort = value!),
                              ),
                            ],
                          ),
                          if (widget.overview) ...[
                            const SizedBox(height: 12),
                            QueueOverview(tasks: queue.tasks, filter: _filter, onFilter: (value) => setState(() => _filter = value)),
                          ],
                          const SizedBox(height: 20),
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  widget.overview ? '优先处理' : '全部任务',
                                  style: Theme.of(
                                    context,
                                  ).textTheme.titleMedium,
                                ),
                              ),
                              Text(
                                '${queue.tasks.where((t) => t['state'] == 'ready').length} 个待开始 · ${queue.tasks.where((t) => QueuePresentation.attentionStates.contains(t['state'])).length} 个需处理',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            ],
                          ),
                          const SizedBox(height: 16),
                          Expanded(
                            child: tasks.isEmpty
                                ? Center(
                                    child: Column(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Text(
                                          queue.loading ? '正在加载…' : !queue.hasSnapshot ? '尚未获取任务' : queue.tasks.isEmpty ? '准备你的第一个任务' : '暂无匹配任务',
                                          style: Theme.of(
                                            context,
                                          ).textTheme.headlineSmall,
                                        ),
                                        const SizedBox(height: 8),
                                        Text(
                                          widget.serverFilter != null
                                              ? '请在任务详情关联实际服务器。'
                                              : _query.isNotEmpty ||
                                                    _filter != 'all'
                                              ? '试试其他关键词或状态。'
                                              : !queue.hasSnapshot ? '连接成功后将显示个人任务。' : '让 Agent 使用 gpuq submit 准备任务，再由你点击开始。',
                                          style: Theme.of(
                                            context,
                                          ).textTheme.bodySmall,
                                        ),
                                      ],
                                    ),
                                  )
                                : QueuePanel(
                                    child: Column(
                                      children: [
                                        Padding(
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 20,
                                            vertical: 9,
                                          ),
                                          child: Row(
                                            children: [
                                              Expanded(
                                                child: Text(
                                                  '任务名称 / 项目',
                                                  style: Theme.of(
                                                    context,
                                                  ).textTheme.bodySmall,
                                                ),
                                              ),
                                              Text(
                                                '状态',
                                                style: Theme.of(
                                                  context,
                                                ).textTheme.bodySmall,
                                              ),
                                              if (!showDetail &&
                                                  bounds.maxWidth > 650)
                                                const SizedBox(width: 130),
                                            ],
                                          ),
                                        ),
                                        const Divider(),
                                        Expanded(
                                          child: ListView.builder(
                                            key: PageStorageKey(
                                              'tasks:$service',
                                            ),
                                            controller: _listScroll,
                                            itemCount: tasks.length,
                                            itemBuilder: (context, index) {
                                              final current = tasks[index];
                                              return QueueTaskRow(
                                                key: ValueKey(current['id']),
                                                task: current,
                                                selected:
                                                    _selected == current['id'],
                                                action:
                                                    !showDetail &&
                                                        bounds.maxWidth > 650
                                                    ? SizedBox(
                                                        width: 100,
                                                        child:
                                                            current['state'] ==
                                                                'ready'
                                                            ? Tooltip(
                                                                message:
                                                                    queue.auto
                                                                    ? '请在队列策略中关闭自动监看后开始'
                                                                    : '点击才授权当前版本',
                                                                child: FilledButton(
                                                                  onPressed:
                                                                      connected &&
                                                                          !queue
                                                                              .acting &&
                                                                          !queue
                                                                              .loading &&
                                                                          !queue
                                                                              .auto
                                                                      ? () => _act(
                                                                          queue,
                                                                          current,
                                                                          'start',
                                                                        )
                                                                      : null,
                                                                  child:
                                                                      const Text(
                                                                        '开始',
                                                                      ),
                                                                ),
                                                              )
                                                            : TextButton(
                                                                onPressed: () =>
                                                                    _openTask(
                                                                      current,
                                                                      service,
                                                                      queue,
                                                                      servers,
                                                                      wide,
                                                                    ),
                                                                child: Text(
                                                                  current['state'] ==
                                                                          'completed'
                                                                      ? '打开结果'
                                                                      : '查看日志',
                                                                ),
                                                              ),
                                                      )
                                                    : null,
                                                onTap: () => _openTask(
                                                  current,
                                                  service,
                                                  queue,
                                                  servers,
                                                  wide,
                                                ),
                                              );
                                            },
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                          ),
                          const SizedBox(height: 12),
                          Text(
                            '共 ${tasks.length} 个任务 · 任务 ID 与工作目录在详情中查看',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                          const SizedBox(height: 20),
                          QueuePanel(
                            child: ExpansionTile(
                              title: const Text(
                                'GPU',
                                style: TextStyle(fontSize: 14),
                              ),
                              subtitle: Text(
                                fresh
                                    ? '实时采样'
                                    : '暂无数据 · 上次采样：${queue.resources.isEmpty ? '未提供' : QueuePresentation.sampleAbsolute(queue.resources.first)}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                              children: [
                                SizedBox(
                                  height: 180,
                                  child: ListView(
                                    children: [
                                      for (final resource in queue.resources)
                                        QueueResourceView(
                                          resource: resource,
                                          connected: connected,
                                        ),
                                      if (queue.resources.isEmpty)
                                        const ListTile(title: Text('暂无数据')),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    );
                    return Row(
                      children: [
                        Expanded(child: list),
                        if (showDetail) ...[
                          const VerticalDivider(width: 1),
                          SizedBox(
                            width: 416,
                            child: _detail(service, queue, task, servers),
                          ),
                        ],
                      ],
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  void _openTask(
    Map<String, dynamic> task,
    String service,
    QueueSession queue,
    Map<String, Spi> servers,
    bool wide,
  ) {
    setState(() {
      if (_selected != task['id']) {
        _detailTab = task['state'] == 'failed'
            ? 1
            : task['state'] == 'completed'
            ? 2
            : 0;
      }
      _selected = task['id'];
    });
    if (!wide) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => _MobileDetail(
            queue: queue,
            taskId: task['id'],
            buildDetail: (t) =>
                _detail(service, queue, t, servers, mobile: true),
          ),
        ),
      );
    }
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
    final enabled = queue.connected && !queue.acting && !queue.loading;
    final steps = (task['step_records'] as List? ?? [])
        .cast<Map<String, dynamic>>();
    final names = task['steps'] as List? ?? [];
    Widget page(String name, List<Widget> children) => ListView(
      key: PageStorageKey('${task['id']}:$name'),
      padding: const EdgeInsets.all(24),
      children: children,
    );
    return StatefulBuilder(
      builder: (context, updateDetail) => QueueDetailPane(
        task: task,
        tab: _detailTab,
        onTab: (tab) {
          setState(() => _detailTab = tab);
          updateDetail(() {});
        },
        onClose: () {
          if (mobile) {
            Navigator.pop(context);
          } else {
            setState(() => _selected = null);
          }
        },
        child: IndexedStack(
          index: _detailTab,
          children: [
            page('overview', [
              SelectableText(
                '${task['name']}\n任务 ID：${task['id']}\n授权：${task['approved_at'] ?? '等待点击开始'}\n${task['description'] ?? ''}',
                style: const TextStyle(fontSize: 12),
              ),
              const SizedBox(height: 12),
              Text(QueuePresentation.nextAction(task)),
              TextButton.icon(
                onPressed: () { Clipboard.setData(ClipboardData(text: QueuePresentation.handoff(task))); _message('已复制任务诊断摘要；不包含日志与文件路径'); },
                icon: const Icon(Icons.copy_outlined), label: const Text('复制给 Agent 排查'),
              ),
              const SizedBox(height: 16),
              Text('申请资源需求', style: Theme.of(context).textTheme.titleMedium),
              SelectableText(QueuePresentation.requirements(task)),
              SelectableText('固定版本：${QueuePresentation.version(task)}'),
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
                      child: Text(
                        task['state'] == 'stopping' ? '等待停止确认…' : '停止任务',
                      ),
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
              if (task['phase'] != null && !_ended.contains(task['state']))
                Text('${task['phase']}'),
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
                              builder: (_) => ServerDetailPage(
                                args: SpiRequiredArgs(target),
                              ),
                            ),
                          ),
                    child: const Text('关联服务器监控'),
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
                                args: SftpPageArgs(
                                  spi: target,
                                  initPath: directory,
                                ),
                              ),
                            ),
                          ),
                    child: const Text('工作目录 / SFTP'),
                  ),
                ],
              ),
              if (resource != null)
                QueueResourceView(
                  resource: resource,
                  connected: queue.connected,
                ),
              const SizedBox(height: 24),
              Text('准备检查与事件', style: Theme.of(context).textTheme.titleLarge),
              for (final line in [
                ...(task['checks'] as List? ?? []),
                ...(task['events'] as List? ?? []),
              ])
                Text('· $line'),
            ]),
            page('logs', [
              Text(
                QueuePresentation.compactRequirements(task),
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 16),
              for (var index = 0; index < names.length; index++) ...[
                QueueLogView(
                  key: ValueKey('${task['id']}:$index'),
                  label:
                      '步骤 ${index + 1} · ${names[index]} · ${QueuePresentation.stepStatus(index < steps.length ? steps[index]['state'] : null)}',
                  text: index < steps.length
                      ? '${steps[index]['log'] ?? '暂无日志'}'
                      : '暂无日志',
                ),
                const SizedBox(height: 16),
              ],
              if (names.isEmpty) const Text('暂无步骤日志'),
              if (task['entry_log'] != null)
                QueueLogView(label: '入口日志', text: '${task['entry_log']}'),
              if (task['stop_log'] != null)
                QueueLogView(label: '停止日志', text: '${task['stop_log']}'),
              if (task['failureReason'] != null) ...[
                const SizedBox(height: 16),
                SelectableText(
                  '${task['failureReason']}',
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                TextButton(
                  onPressed: () => Clipboard.setData(
                    ClipboardData(text: '${task['failureReason']}'),
                  ),
                  child: const Text('复制错误'),
                ),
              ],
              const SizedBox(height: 16),
              SelectableText(
                '固定版本：${QueuePresentation.version(task)}',
                style: const TextStyle(fontFamily: 'Menlo', fontSize: 12),
              ),
            ]),
            page('results', [
              if (target == null) ...[
                const Text('打开结果文件前，请关联能访问这些文件的个人服务器。文件在共享 HOME 时可选择个人 CPU 服务器。'),
                TextButton(onPressed: QueueTarget.instance(task) == null ? null : () => _bind(service, task, servers), child: const Text('关联结果服务器')),
              ],
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
                      onPressed: () => Clipboard.setData(
                        ClipboardData(text: '${file['path']}'),
                      ),
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
            ]),
          ],
        ),
      ),
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
