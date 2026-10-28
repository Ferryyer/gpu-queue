import 'dart:async';

import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:url_launcher/url_launcher.dart';

class DailyCalendarPanel extends StatefulWidget {
  const DailyCalendarPanel({super.key});
  @override
  State<DailyCalendarPanel> createState() => _DailyCalendarPanelState();
}

class _DailyCalendarPanelState extends State<DailyCalendarPanel> {
  final _source = LocalCalendar.desktop();
  CalendarReading? _reading;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
  }

  Future<void> _refresh() async {
    if (_loading) return;
    setState(() => _loading = true);
    try {
      final reading = await _source?.read().timeout(const Duration(seconds: 8));
      if (!mounted) return;
      setState(() {
        _reading = reading;
        _error = reading == null ? '暂时无法找到本机桌面目录' : null;
      });
    } catch (_) {
      if (mounted) {
        setState(() => _error = _reading == null
          ? '等待桌面的今日单向历.jpg；请确认每日任务已更新文件，并允许应用读取桌面。'
          : '暂时无法读取更新，正在显示上次成功读取的图片。');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _expand({bool notes = false}) {
    final reading = _reading;
    if (reading == null) return;
    showDialog<void>(context: context, builder: (dialogContext) => Dialog(
      child: SizedBox(width: notes ? 720 : 560, height: MediaQuery.sizeOf(context).height * .85,
        child: Column(children: [
          ListTile(title: Text(notes ? '单向历 · 出处笔记' : '单向历'),
            subtitle: Text('${notes ? '笔记' : '图片'}文件更新于 ${CalendarReading.day((notes ? reading.notesModified : reading.modified) ?? reading.modified)}'),
            trailing: IconButton(tooltip: '关闭', onPressed: () => Navigator.of(dialogContext, rootNavigator: true).pop(), icon: const Icon(Icons.close))),
          const Divider(height: 1),
          Expanded(child: notes ? Markdown(
            data: reading.notes ?? '尚未生成出处笔记。', selectable: true,
            onTapLink: (_, href, _) {
              final uri = Uri.tryParse(href ?? '');
              if (uri != null && const ['https', 'http'].contains(uri.scheme)) {
                unawaited(launchUrl(uri, mode: LaunchMode.externalApplication));
              }
            },
          ) : InteractiveViewer(child: Image.memory(reading.bytes, fit: BoxFit.contain,
              errorBuilder: (_, _, _) => const Center(child: Text('图片无法解码，请更新桌面文件'))))),
        ])),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final reading = _reading;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(padding: const EdgeInsets.fromLTRB(16, 12, 4, 4), child: Row(children: [
        Expanded(child: Text('单向历', style: Theme.of(context).textTheme.titleLarge)),
        IconButton(tooltip: '刷新桌面日历', onPressed: _loading ? null : _refresh, icon: const Icon(Icons.refresh, size: 20)),
      ])),
      if (_error != null) Padding(padding: const EdgeInsets.all(12), child: Text(_error!, style: Theme.of(context).textTheme.bodySmall)),
      const SizedBox(height: 8),
      Expanded(child: reading == null
        ? Center(child: _loading ? const CircularProgressIndicator() : const Icon(Icons.auto_stories_outlined, size: 48))
        : Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: InkWell(
            onTap: _expand, child: Image.memory(reading.bytes, fit: BoxFit.contain,
              errorBuilder: (_, _, _) => const Center(child: Text('图片无法解码，请更新桌面文件')))))),
      Padding(padding: const EdgeInsets.all(8), child: Wrap(alignment: WrapAlignment.center, children: [
        TextButton.icon(onPressed: reading == null ? null : _expand,
          icon: const Icon(Icons.open_in_full, size: 16), label: const Text('看大图')),
        TextButton.icon(onPressed: reading?.notes == null ? null : () => _expand(notes: true),
          icon: const Icon(Icons.menu_book_outlined, size: 16), label: const Text('出处笔记')),
      ])),
    ]);
  }
}
