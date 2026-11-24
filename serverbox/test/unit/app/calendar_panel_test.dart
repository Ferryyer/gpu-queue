import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/notes.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:server_box/view/page/overview/calendar.dart';

void main() {
  late Directory cache;
  late CalendarUpdater updater;
  late bool online;
  late int requests;
  Completer<void>? block;
  final today = CalendarReading.day(DateTime.now());
  // A small JPEG exercises Flutter's real image decoder.
  final jpeg = base64Decode(
    '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAABgf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCVAAB//9k=',
  );

  setUp(() async {
    cache = await Directory.systemTemp.createTemp('calendar-panel-test-');
    online = false;
    requests = 0;
    block = null;
    await File('${cache.path}/$today.jpg').writeAsBytes(jpeg);
    updater = CalendarUpdater(
      LocalCalendar(cache),
      downloadNotes: (_) async => null,
      download: (_, _) async {
        requests++;
        if (block != null) await block!.future;
        return online;
      },
    );
  });
  tearDown(() async {
    await cache.delete(recursive: true);
  });

  Widget app({bool active = true, bool ticking = true}) => MaterialApp(
    home: Scaffold(
      body: TickerMode(
        enabled: ticking,
        child: DailyCalendarPanel(updater: updater, active: active),
      ),
    ),
  );

  Future<void> settle(
    WidgetTester tester,
    int expectedRequests, {
    bool idle = true,
  }) async {
    // Filesystem I/O uses the real event loop, while Flutter timers stay fake.
    for (var i = 0; i < 200; i++) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 5)),
      );
      await tester.pump();
      if (requests >= expectedRequests &&
          (!idle || find.textContaining('正在检查更新').evaluate().isEmpty))
        return;
    }
    fail('Calendar did not reach the requested refresh state');
  }

  testWidgets(
    'open rechecks today; failed refresh says cached, recovered refresh clears it',
    (tester) async {
      await tester.pumpWidget(app());
      await settle(tester, 1);
      expect(requests, 1);
      expect(find.textContaining('本次尚未取得最新内容'), findsOneWidget);
      expect(find.text(today), findsOneWidget);
      online = true;
      await tester.tap(find.byTooltip('更新单向历'));
      await settle(tester, 2);
      expect(requests, 2);
      expect(find.textContaining('本次尚未取得最新内容'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'return to overview, return from settings and resume bypass failure cooldown',
    (tester) async {
      await tester.pumpWidget(app());
      await settle(tester, 1);
      await tester.pumpWidget(app(active: false));
      await tester.pumpWidget(app());
      await settle(tester, 2);
      expect(requests, 2);
      expect(find.textContaining('本次尚未取得最新内容'), findsOneWidget);
      await tester.pumpWidget(app(ticking: false));
      await tester.pumpWidget(app());
      await settle(tester, 3);
      expect(requests, 3);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await settle(tester, 4);
      expect(requests, 4);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'CAL-A-001: source dialog falls back to B source when cached notes identify A',
    (tester) async {
      const sourceB =
          'https://img.owspace.com/Public/uploads/Download/2026/1030.jpg';
      final digestB = sha256.convert(jpeg).toString();
      await tester.runAsync(() async {
        await File('${cache.path}/$today.$digestB.jpg').writeAsBytes(jpeg);
        await File('${cache.path}/$today.json').writeAsString(
          jsonEncode({'date': today, 'sha256': digestB, 'source': sourceB}),
        );
        await File('${cache.path}/$today.notes.md').writeAsString(
          '${CalendarNotes.marker(today)}\n${CalendarNotes.imageMarker('0' * 64)}\n# Old attribution A\n',
        );
      });
      await tester.pumpWidget(app());
      await settle(tester, 1);
      await tester.tap(find.text('出处笔记'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Old attribution A'), findsNothing);
      expect(
        find.textContaining('当前图片对应的出处笔记尚未发布、尚未核对或暂时无法获取'),
        findsOneWidget,
      );
      expect(updater.reading!.notes, contains(sourceB));
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'refresh stays actionable while loading and queues a real followup',
    (tester) async {
      block = Completer<void>();
      await tester.pumpWidget(app());
      await settle(tester, 1, idle: false);
      expect(requests, 1);
      await tester.tap(find.byTooltip('更新单向历'));
      await tester.tap(find.byTooltip('更新单向历'));
      online = true;
      block!.complete();
      await settle(tester, 2);
      expect(requests, 2);
      expect(find.textContaining('本次尚未取得最新内容'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
