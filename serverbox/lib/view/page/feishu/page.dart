import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

const feishuTaskUrl = 'https://uqyv5nolng8.feishu.cn/next/task/my-tasks';

class FeishuTaskPage extends StatefulWidget {
  const FeishuTaskPage({super.key, this.embedded = false, this.onExpand});
  final bool embedded;
  final VoidCallback? onExpand;
  @override
  State<FeishuTaskPage> createState() => _FeishuTaskPageState();
}

class _FeishuTaskPageState extends State<FeishuTaskPage> with AutomaticKeepAliveClientMixin {
  late final Future<String> _script = rootBundle.loadString('assets/feishu/inspire-task.user.js');
  MethodChannel? _channel;
  bool _loading = true, _back = false, _styled = true, _hint = true;
  bool? _dark;
  String? _error;

  @override
  void initState() {
    super.initState();
    _hint = !widget.embedded;
  }

  @override
  bool get wantKeepAlive => true;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final dark = Theme.of(context).brightness == Brightness.dark;
    if (_dark != dark) {
      _dark = dark;
      unawaited(_command('dark', dark));
    }
  }

  Future<void> _command(String method, [Object? argument]) async {
    try {
      await _channel?.invokeMethod<void>(method, argument);
    } on PlatformException {
      if (mounted) setState(() => _error = '无法连接网页视图，请重新打开飞书任务。');
    } on MissingPluginException {
      if (mounted) setState(() => _error = '当前安装版本尚不支持内嵌飞书，请在浏览器中打开。');
    }
  }

  void _created(int id) {
    _channel = MethodChannel('work.inspirequeue/feishu/$id');
    _channel!.setMethodCallHandler((call) async {
      if (!mounted || call.method != 'state' || call.arguments is! Map) return;
      final state = call.arguments as Map;
      setState(() {
        _loading = state['loading'] == true;
        _back = state['canGoBack'] == true;
        _styled = state['enabled'] != false;
        _error = state['error'] as String?;
      });
    });
    unawaited(_command('state'));
    unawaited(_command('dark', _dark));
  }

  Future<void> _openBrowser() async {
    try {
      final opened = await launchUrl(Uri.parse(feishuTaskUrl), mode: LaunchMode.externalApplication);
      if (!opened && mounted) setState(() => _error = '未能打开浏览器，请稍后重试。');
    } catch (_) {
      if (mounted) setState(() => _error = '未能打开浏览器，请稍后重试。');
    }
  }

  @override
  void dispose() {
    _channel?.setMethodCallHandler(null);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final supported = !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS;
    final colors = Theme.of(context).colorScheme;
    return Column(children: [
      SizedBox(height: 56, child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          Expanded(child: Text('飞书任务', maxLines: 1, overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleLarge)),
          if (supported) ...[
            if (!widget.embedded) IconButton(tooltip: '后退', onPressed: _back ? () => _command('back') : null,
              icon: const Icon(Icons.arrow_back)),
            IconButton(tooltip: '刷新', onPressed: () => _command('reload'), icon: const Icon(Icons.refresh)),
          ],
          IconButton(tooltip: '在浏览器打开', onPressed: _openBrowser, icon: const Icon(Icons.open_in_new)),
          if (widget.onExpand != null) IconButton(tooltip: '打开完整飞书任务页',
            onPressed: widget.onExpand, icon: const Icon(Icons.open_in_full)),
          if (supported) PopupMenuButton<String>(
            tooltip: '页面选项',
            onSelected: (value) {
              if (value == 'home') unawaited(_command('home'));
              if (value == 'style') unawaited(_command('appearance', !_styled));
            },
            itemBuilder: (_) => [
              const PopupMenuItem(value: 'home', child: Text('回到我负责的')),
              CheckedPopupMenuItem(value: 'style', checked: _styled, child: const Text('Inspire 风格')),
            ],
          ),
        ]),
      )),
      if (_hint) Container(
        color: colors.surfaceContainerLowest,
        padding: const EdgeInsets.only(left: 16, right: 4),
        child: Row(children: [
          const Expanded(child: Padding(padding: EdgeInsets.symmetric(vertical: 10),
            child: Text('首次使用请在飞书页面登录；登录状态保存在本机。', style: TextStyle(fontSize: 12)))),
          IconButton(tooltip: '收起提示', onPressed: () => setState(() => _hint = false),
            icon: const Icon(Icons.close, size: 16)),
        ]),
      ),
      if (_error != null) Padding(padding: const EdgeInsets.all(12),
        child: Text(_error!, style: TextStyle(color: colors.error))),
      if (supported && _loading && _error == null) const LinearProgressIndicator(minHeight: 2),
      const Divider(height: 1),
      Expanded(child: supported ? FutureBuilder<String>(
        future: _script,
        builder: (context, snapshot) {
          if (snapshot.hasError) return const Center(child: Text('页面资源未能加载，请重新打开应用。'));
          if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
          return AppKitView(
            viewType: 'work.inspirequeue/feishu',
            layoutDirection: TextDirection.ltr,
            creationParams: {'script': snapshot.data, 'dark': _dark ?? false},
            creationParamsCodec: const StandardMessageCodec(),
            onPlatformViewCreated: _created,
          );
        },
      ) : Center(child: FilledButton.icon(onPressed: _openBrowser,
        icon: const Icon(Icons.open_in_new), label: const Text('在浏览器打开飞书任务')))),
    ]);
  }
}
