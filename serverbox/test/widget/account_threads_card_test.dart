import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/extension/context/locale.dart';
import 'package:server_box/view/page/server/detail/account_threads_card.dart';
import 'package:server_box/view/page/server/detail/focus_parts.dart';
import 'package:server_box/view/page/server/metric_row.dart';

void main() {
  setUpAll(() => initializeDateFormatting('en'));
  const output = '470 个线程\n92 个进程 · linlishuo · 北京时间 10-23 19:36:00\n'
      'codex: 184 / 8 · 最大 PID 2347799 (47)\n';

  Future<void> pump(
    WidgetTester tester, {
    bool wide = true,
    String text = output,
    VoidCallback? onTap,
    DateTime? staleAt,
  }) async {
    tester.view.physicalSize = Size(wide ? 1200 : 320, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AccountThreadsCard(
        output: text,
        wide: wide,
        staleAt: staleAt,
        onTap: onTap ?? () {},
      )),
    ));
  }

  testWidgets('uses the ordinary wide metric row and opens detail', (tester) async {
    var taps = 0;
    await pump(tester, onTap: () => taps++);
    expect(find.byType(MetricRow), findsOneWidget);
    expect(find.text(AccountThreadsCard.commandName), findsOneWidget);
    expect(find.text('470 个线程'), findsOneWidget);
    expect(find.textContaining('92 个进程'), findsOneWidget);
    await tester.tap(find.text('470 个线程'));
    expect(taps, 1);
  });

  testWidgets('uses the narrow metric tile and updates on refresh', (tester) async {
    await pump(tester, wide: false);
    expect(find.byType(ServerDetailMetricTile), findsOneWidget);
    expect(tester.takeException(), isNull);
    await pump(tester, wide: false, text: output.replaceFirst('470', '481'));
    expect(find.text('481 个线程'), findsOneWidget);
    expect(find.text('470 个线程'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('disconnected values show the last reading time', (tester) async {
    await pump(tester, wide: false, staleAt: DateTime(2026, 10, 23, 19, 36));
    final tile = tester.widget<ServerDetailMetricTile>(
      find.byType(ServerDetailMetricTile),
    );
    expect(tile.stale, isTrue);
    expect(tile.note, contains('19:36'));
    expect(tile.note, isNot(contains('92 个进程')));
  });

  testWidgets('empty and long command errors do not become zero or overflow', (tester) async {
    await pump(tester, wide: false, text: '');
    expect(find.text(l10n.unavailable), findsOneWidget);
    expect(find.text('0 个线程'), findsNothing);
    await pump(tester, wide: false, text: '/usr/bin/python3: cannot read process status because permission was denied\n');
    expect(find.text(l10n.unavailable), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
