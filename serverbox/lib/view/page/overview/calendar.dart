import 'dart:async';
import 'dart:io';

import 'package:fl_lib/fl_lib.dart' show Paths;

import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:url_launcher/url_launcher.dart';

class DailyCalendarPanel extends StatefulWidget {
  const DailyCalendarPanel({super.key});
  @override
  State<DailyCalendarPanel> createState() => _DailyCalendarPanelState();
}

class _DailyCalendarPanelState extends State<DailyCalendarPanel> with WidgetsBindingObserver {
  late final _updater = CalendarUpdater(LocalCalendar(Directory('${Paths.doc}/daily-calendar')));
  Timer? _timer;
  CalendarReading? _reading;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_refresh());
  }

  Future<void> _refresh({bool force = false}) async {
    if (_loading) return;
    _timer?.cancel();
    setState(() => _loading = true);
    try {
      await _updater.loadCache(DateTime.now());
      if (!mounted) return;
      if (_updater.reading != _reading) setState(() => _reading = _updater.reading);
      await _updater.update(DateTime.now(), force: force);
      if (!mounted) return;
      setState(() {
        _reading = _updater.reading;
        _error = _reading?.updatedToday(DateTime.now()) == true ? null
          : _reading == null ? '今日单向历暂不可用，将自动重试。'
          : '暂未取得今日图片，保留 ${_reading!.date} 的单向历，稍后自动重试。';
      });
    } catch (_) {
      if (mounted) setState(() => _error = '暂时无法更新单向历，稍后自动重试。');
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        final delay = _updater.nextCheck(DateTime.now());
        _timer = Timer(delay < const Duration(minutes: 1) ? const Duration(minutes: 1) : delay,
          () => unawaited(_refresh()));
      }
    }
  }

  void _expand({bool notes = false}) {
    final reading = _reading;
    if (reading == null) return;
    showDialog<void>(context: context, builder: (dialogContext) => Dialog(
      child: SizedBox(width: notes ? 720 : 560, height: MediaQuery.sizeOf(context).height * .85,
        child: Column(children: [
          ListTile(title: Text(notes ? '单向历 · 图片来源' : '单向历'),
            subtitle: Text(reading.date),
            trailing: IconButton(tooltip: '关闭', onPressed: () => Navigator.of(dialogContext, rootNavigator: true).pop(), icon: const Icon(Icons.close))),
          const Divider(height: 1),
          Expanded(child: notes ? Markdown(
            data: reading.notes ?? '作者与作品出处见原图署名。', selectable: true,
            onTapLink: (_, href, _) {
              final uri = Uri.tryParse(href ?? '');
              if (uri != null && const ['https', 'http'].contains(uri.scheme)) {
                unawaited(launchUrl(uri, mode: LaunchMode.externalApplication));
              }
            },
          ) : InteractiveViewer(child: Image.memory(reading.bytes, fit: BoxFit.contain,
              errorBuilder: (_, _, _) => const Center(child: Text('图片无法解码，请重试更新'))))),
        ])),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final reading = _reading;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(padding: const EdgeInsets.fromLTRB(16, 12, 4, 4), child: Row(children: [
        Expanded(child: Text('单向历', style: Theme.of(context).textTheme.titleLarge)),
        IconButton(tooltip: '更新单向历', onPressed: _loading ? null : () => _refresh(force: true), icon: const Icon(Icons.refresh, size: 20)),
      ])),
      if (_error != null) Padding(padding: const EdgeInsets.all(12), child: Text(_error!, style: Theme.of(context).textTheme.bodySmall)),
      const SizedBox(height: 8),
      Expanded(child: reading == null
        ? Center(child: _loading ? const CircularProgressIndicator() : const Icon(Icons.auto_stories_outlined, size: 48))
        : Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: InkWell(
            onTap: _expand, child: Image.memory(reading.bytes, fit: BoxFit.contain,
              errorBuilder: (_, _, _) => const Center(child: Text('图片无法解码，请重试更新')))))),
      Padding(padding: const EdgeInsets.all(8), child: Wrap(alignment: WrapAlignment.center, children: [
        TextButton.icon(onPressed: reading == null ? null : _expand,
          icon: const Icon(Icons.open_in_full, size: 16), label: const Text('看大图')),
        TextButton.icon(onPressed: reading?.notes == null ? null : () => _expand(notes: true),
          icon: const Icon(Icons.menu_book_outlined, size: 16), label: const Text('图片来源')),
      ])),
    ]);
  }
}
