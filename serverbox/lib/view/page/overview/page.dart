import 'dart:io';

import 'package:fl_lib/fl_lib.dart' show Paths;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:server_box/data/model/app/tab.dart';
import 'package:server_box/data/provider/app/session_requests.dart';
import 'package:server_box/view/page/feishu/page.dart';
import 'package:server_box/view/page/overview/calendar.dart';
import 'package:server_box/view/page/overview/gpu.dart';
import 'package:server_box/view/page/overview/layout.dart';

class WorkOverviewPage extends ConsumerStatefulWidget {
  const WorkOverviewPage({super.key});
  @override
  ConsumerState<WorkOverviewPage> createState() => _WorkOverviewPageState();
}

class _WorkOverviewPageState extends ConsumerState<WorkOverviewPage>
    with AutomaticKeepAliveClientMixin {
  late final _calendarUpdater = CalendarUpdater.shared(
    LocalCalendar(Directory('${Paths.doc}/daily-calendar')),
  );
  @override
  bool get wantKeepAlive => true;
  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Scaffold(
      appBar: AppBar(title: const Text('总览')),
      body: OverviewLayout(
        gpu: const GpuSummaryPanel(),
        feishu: FeishuTaskPage(
          embedded: true,
          onExpand: () =>
              ref.read(homeTabRequestProvider.notifier).go(AppTab.feishu),
        ),
        calendar: DailyCalendarPanel(
          updater: _calendarUpdater,
          active: ref.watch(currentHomeTabProvider) == AppTab.overview,
        ),
      ),
    );
  }
}
