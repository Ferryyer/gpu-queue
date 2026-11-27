import 'dart:async';

import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:url_launcher/url_launcher.dart';

class DailyCalendarPanel extends StatefulWidget {
  const DailyCalendarPanel({
    super.key,
    required this.updater,
    this.active = true,
  });
  final bool active;
  final CalendarUpdater updater;
  @override
  State<DailyCalendarPanel> createState() => _DailyCalendarPanelState();
}

class _DailyCalendarPanelState extends State<DailyCalendarPanel>
    with WidgetsBindingObserver {
  late final _updater = widget.updater;
  Timer? _timer;
  CalendarReading? _reading;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_refresh(force: true));
  }

  @override
  void didUpdateWidget(covariant DailyCalendarPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) unawaited(_refresh(force: true));
  }

  bool? _tickerEnabled;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final enabled = TickerMode.of(context);
    if (enabled && _tickerEnabled == false && widget.active) {
      unawaited(_refresh(force: true));
    }
    _tickerEnabled = enabled;
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_refresh(force: true));
  }

  Future<void> _refresh({bool force = false}) async {
    if (_loading) {
      if (force) {
        try {
          await _updater.update(DateTime.now(), force: true);
        } on Exception {
          /* The owning refresh displays the failure. */
        }
      }
      return;
    }
    _timer?.cancel();
    setState(() => _loading = true);
    try {
      await _updater.loadCache(DateTime.now());
      if (!mounted) return;
      if (_updater.reading != _reading)
        setState(() => _reading = _updater.reading);
      await _updater.update(DateTime.now(), force: force);
      if (!mounted) return;
      setState(() {
        _reading = _updater.reading;
        _error =
            _updater.latestCheckSucceeded &&
                _reading?.updatedToday(DateTime.now()) == true
            ? null
            : _reading == null
            ? '今日单向历暂不可用，将自动重试。'
            : '本次未确认最新单向历，显示 ${_reading!.date} 的缓存，稍后自动重试。';
      });
    } catch (_) {
      if (mounted) setState(() => _error = '暂时无法更新单向历，稍后自动重试。');
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        final delay = _updater.nextCheck(DateTime.now());
        _timer = Timer(
          delay < const Duration(minutes: 1)
              ? const Duration(minutes: 1)
              : delay,
          () => unawaited(_refresh()),
        );
      }
    }
  }

  void _expand({bool notes = false}) {
    final reading = _reading;
    if (reading == null) return;
    showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog(
        child: SizedBox(
          width: notes ? 720 : 560,
          height: MediaQuery.sizeOf(context).height * .85,
          child: Column(
            children: [
              ListTile(
                title: Text(notes ? '单向历 · 出处笔记' : '单向历'),
                subtitle: Text(reading.date),
                trailing: IconButton(
                  tooltip: '关闭',
                  onPressed: () =>
                      Navigator.of(dialogContext, rootNavigator: true).pop(),
                  icon: const Icon(Icons.close),
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: notes
                    ? Markdown(
                        data: reading.hasResearchNotes
                            ? '${reading.imageSource ?? "作者与作品出处见原图署名。"}\n\n'
                                  '出处笔记按日期发布；同日图片修订时，请以原图署名为准。\n\n${reading.notes!}'
                            : '${reading.notes ?? "作者与作品出处见原图署名。"}\n\n当天出处笔记尚未发布或暂时无法获取，稍后自动检查。',
                        selectable: true,
                        imageBuilder: (_, _, _) => const SizedBox.shrink(),
                        onTapLink: (_, href, _) {
                          final uri = Uri.tryParse(href ?? '');
                          if (uri != null &&
                              uri.scheme == 'https' &&
                              uri.userInfo.isEmpty) {
                            unawaited(
                              launchUrl(
                                uri,
                                mode: LaunchMode.externalApplication,
                              ),
                            );
                          }
                        },
                      )
                    : InteractiveViewer(
                        child: Image.memory(
                          reading.bytes,
                          fit: BoxFit.contain,
                          errorBuilder: (_, _, _) =>
                              const Center(child: Text('图片无法解码，请重试更新')),
                        ),
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final reading = _reading;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 4, 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '单向历',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              IconButton(
                tooltip: _loading ? '正在更新，点击再次检查' : '更新单向历',
                onPressed: () => _refresh(force: true),
                icon: const Icon(Icons.refresh, size: 20),
              ),
            ],
          ),
        ),
        if (reading != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              '图面日期：${reading.date}${_loading ? " · 正在检查最新内容…" : ""}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(_error!, style: Theme.of(context).textTheme.bodySmall),
          ),
        const SizedBox(height: 8),
        Expanded(
          child: reading == null
              ? Center(
                  child: _loading
                      ? const CircularProgressIndicator()
                      : const Icon(Icons.auto_stories_outlined, size: 48),
                )
              : Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: InkWell(
                    onTap: _expand,
                    child: Image.memory(
                      reading.bytes,
                      fit: BoxFit.contain,
                      errorBuilder: (_, _, _) =>
                          const Center(child: Text('图片无法解码，请重试更新')),
                    ),
                  ),
                ),
        ),
        Padding(
          padding: const EdgeInsets.all(8),
          child: Wrap(
            alignment: WrapAlignment.center,
            children: [
              TextButton.icon(
                onPressed: reading == null ? null : _expand,
                icon: const Icon(Icons.open_in_full, size: 16),
                label: const Text('看大图'),
              ),
              TextButton.icon(
                onPressed: reading?.notes == null
                    ? null
                    : () => _expand(notes: true),
                icon: const Icon(Icons.menu_book_outlined, size: 16),
                label: const Text('出处笔记'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
