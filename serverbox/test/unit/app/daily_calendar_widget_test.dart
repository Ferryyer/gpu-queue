import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:server_box/view/page/overview/calendar.dart';

void main() {
  late Directory dir;
  late CalendarUpdater updater;
  late String day;
  var calls = 0;
  var online = true;
  Completer<void>? gate;

  Future<void> writeImage() async {
    // Synthetic JPEG, including a harmless comment that changes per request.
    final bytes = base64Decode(
      '/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjI4LjEwMwD/2wBDAAgEBAQEBAUFBQUFBQYGBgYGBgYGBgYGBgYHBwcICAgHBwcGBgcHCAgICAkJCQgICAgJCQoKCgwMCwsODg4RERT/xABKAAEAAAAAAAAAAAAAAAAAAAAAAQEAAAAAAAAAAAAAAAAAAAAAEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAAAAAAAAAAAAAAAAAA/8AAEQgAEAAQAwEiAAIRAAMRAP/aAAwDAQACEQMRAD8AAA//2Q==',
    );
    await File('${dir.path}/$day.jpg').writeAsBytes([
      ...bytes.take(2),
      0xff,
      0xfe,
      0,
      3,
      calls,
      ...bytes.skip(2),
    ]);
  }

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('calendar-panel-test-');
    day = CalendarReading.day(DateTime.now());
    calls = 0;
    online = true;
    gate = null;
    await writeImage();
    updater = CalendarUpdater(
      LocalCalendar(dir),
      downloadNotes: (_) async => null,
      download: (_, _) async {
        calls++;
        final pending = gate;
        gate = null;
        if (pending != null) await pending.future;
        if (!online) return false;
        await writeImage();
        return true;
      },
    );
  });
  tearDown(() async {
    await dir.delete(recursive: true);
  });

  Widget app({bool active = true}) => MaterialApp(
    home: Scaffold(
      body: SizedBox(
        width: 400,
        height: 600,
        child: DailyCalendarPanel(updater: updater, active: active),
      ),
    ),
  );

  Future<void> finishIO(WidgetTester tester) async {
    // The production panel reads actual temporary files, outside fake time.
    for (var i = 0; i < 200; i++) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 2)),
      );
      await tester.pump();
      if (find.byTooltip('更新单向历').evaluate().isNotEmpty) return;
    }
    fail('calendar refresh did not finish');
  }

  testWidgets(
    'open and every manual refresh check the network with today cached',
    (tester) async {
      await tester.pumpWidget(app());
      await finishIO(tester);
      expect(calls, 1);
      expect(find.text('图面日期：$day'), findsOneWidget);
      expect(find.textContaining('本次未确认'), findsNothing);
      await tester.tap(find.byTooltip('更新单向历'));
      await finishIO(tester);
      expect(calls, 2);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'failed check shows a warning even for today; refresh immediately recovers',
    (tester) async {
      online = false;
      await tester.pumpWidget(app());
      await finishIO(tester);
      expect(find.textContaining('本次未确认最新单向历'), findsOneWidget);
      expect(find.text('图面日期：$day'), findsOneWidget);
      online = true;
      await tester.tap(find.byTooltip('更新单向历'));
      await finishIO(tester);
      expect(calls, 2);
      expect(find.textContaining('本次未确认'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'refresh during a download remains actionable and queues another check',
    (tester) async {
      await tester.pumpWidget(app());
      await finishIO(tester);
      final blocked = Completer<void>();
      gate = blocked;
      await tester.tap(find.byTooltip('更新单向历'));
      for (var i = 0; i < 200 && calls < 2; i++) {
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 2)),
        );
        await tester.pump();
      }
      expect(calls, 2);
      await tester.tap(find.byTooltip('正在更新，点击再次检查'));
      blocked.complete();
      await finishIO(tester);
      expect(calls, 3);
      expect(updater.reading!.bytes[6], 3);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'returning to overview and resuming bypass the failure cooldown',
    (tester) async {
      online = false;
      await tester.pumpWidget(app());
      await finishIO(tester);
      expect(calls, 1);
      await tester.pumpWidget(app(active: false));
      await tester.pumpWidget(app());
      await finishIO(tester);
      expect(calls, 2);
      online = true;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await finishIO(tester);
      expect(calls, 3);
      expect(find.textContaining('本次未确认'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('uncovering the main page after settings checks again', (
    tester,
  ) async {
    await tester.pumpWidget(TickerMode(enabled: true, child: app()));
    await finishIO(tester);
    expect(calls, 1);
    await tester.pumpWidget(TickerMode(enabled: false, child: app()));
    await tester.pumpWidget(TickerMode(enabled: true, child: app()));
    await finishIO(tester);
    expect(calls, 2);
    await tester.pumpWidget(const SizedBox());
  });
}
