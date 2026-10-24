import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/gpu_queue/workspace.dart';

void main() {
  final task = <String, dynamic>{
    'id': 'private-task-id',
    'name': '长任务名称 · ${'实验比较与日志检查' * 12}',
    'project': 'project-one',
    'state': 'failed',
    'resources': {'gpus': 1, 'memory_gb': 80},
  };
  Future<void> show(
    WidgetTester tester,
    Widget body, {
    Size size = const Size(1280, 800),
    bool dark = false,
    double scale = 1,
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: gpuQueueTheme(
          ThemeData(brightness: dark ? Brightness.dark : Brightness.light),
        ),
        home: MediaQuery(
          data: MediaQueryData(
            size: size,
            textScaler: TextScaler.linear(scale),
          ),
          child: Scaffold(body: body),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'real update survives narrow rows, long names and 1.5x text with usable actions',
    (tester) async {
      for (final width in [390.0, 560.0, 900.0]) {
        for (final scale in [1.0, 1.5]) {
          var starts = 0;
          await show(
            tester,
            Align(
              alignment: Alignment.topLeft,
              child: SizedBox(
                width: width,
                child: QueueTaskRow(
                  task: {...task, 'updated_at': '2026-10-24T20:00:00+08:00'},
                  selected: false,
                  onTap: () {},
                  action: SizedBox(
                    width: 100,
                    child: FilledButton(
                      onPressed: () => starts++,
                      child: const Text('开始'),
                    ),
                  ),
                ),
              ),
            ),
            scale: scale,
          );
          expect(find.text('更新 2026-10-24 12:00:00 UTC'), findsOneWidget);
          expect(find.text('失败'), findsOneWidget);
          final row = tester.getRect(find.byType(QueueTaskRow));
          for (final item in [
            find.text('更新 2026-10-24 12:00:00 UTC'),
            find.text('失败'),
            find.byType(FilledButton),
          ]) {
            final rect = tester.getRect(item);
            expect(row.contains(rect.topLeft), isTrue);
            expect(
              row.contains(rect.bottomRight - const Offset(0.01, 0.01)),
              isTrue,
            );
          }
          if (width == 900 && scale == 1) {
            expect(row.height, closeTo(64, 2));
          }
          await tester.tap(find.byType(FilledButton));
          expect(starts, 1);
          expect(tester.takeException(), isNull);
        }
      }
    },
  );

  testWidgets(
    'compact rows keep long names, textual failure and no private IDs in both themes',
    (tester) async {
      for (final dark in [false, true]) {
        var selected = 0;
        await show(
          tester,
          Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: 560,
              child: QueueTaskRow(
                task: task,
                selected: true,
                onTap: () => selected++,
              ),
            ),
          ),
          dark: dark,
        );
        expect(
          tester.getSize(find.byType(QueueTaskRow)).height,
          closeTo(64, 2),
        );
        expect(find.text('失败'), findsOneWidget);
        expect(find.byIcon(Icons.error_outline), findsOneWidget);
        expect(find.textContaining('private-task-id'), findsNothing);
        expect(find.textContaining('1 GPU / 80 GB'), findsOneWidget);
        await tester.tap(find.byType(QueueTaskRow));
        await tester.pump();
        expect(selected, 1);
        expect(tester.takeException(), isNull);
      }
    },
  );

  testWidgets(
    'sidebar collapses without overflow and retains settings and navigation',
    (tester) async {
      var destination = -1, settings = 0;
      await show(
        tester,
        Row(
          children: [
            QueueSidebar(
              selected: 1,
              onSelect: (i) => destination = i,
              onSettings: () => settings++,
              onMore: () {},
            ),
            const Expanded(child: SizedBox()),
          ],
        ),
      );
      expect(tester.getSize(find.byType(QueueSidebar)).width, 208);
      await tester.tap(find.text('服务器'));
      expect(destination, 2);
      await tester.tap(find.byTooltip('收起侧栏'));
      await tester.pumpAndSettle();
      expect(tester.getSize(find.byType(QueueSidebar)).width, 64);
      await tester.tap(find.byIcon(Icons.settings_outlined));
      expect(settings, 1);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byTooltip('展开侧栏'));
      await tester.pumpAndSettle();
      expect(find.text('任务'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'right pane tabs, long title, log indentation and clipboard work at 416px',
    (tester) async {
      const log = 'Traceback:\n    run_step()\n        raise RuntimeError()';
      String? copied;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copied = (call.arguments as Map)['text'] as String;
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      var tab = 0, closed = false;
      await show(
        tester,
        Align(
          alignment: Alignment.centerRight,
          child: SizedBox(
            width: 416,
            child: StatefulBuilder(
              builder: (context, update) => QueueDetailPane(
                task: {...task, 'name': '任务失败 · 保留列表上下文'},
                tab: tab,
                onTab: (i) => update(() => tab = i),
                onClose: () => closed = true,
                child: tab == 1
                    ? const SingleChildScrollView(
                        child: QueueLogView(label: '步骤 1 · 运行日志', text: log),
                      )
                    : const Text('概览内容'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('日志'));
      await tester.pumpAndSettle();
      expect(tab, 1);
      expect(find.text(log), findsOneWidget);
      await tester.tap(find.byTooltip('复制日志'));
      await tester.pump();
      expect(copied, log);
      await tester.tap(find.byTooltip('关闭详情'));
      expect(closed, true);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'poll rebuild preserves focus, selection and scroll and scales task rows',
    (tester) async {
      final scroll = ScrollController();
      final query = TextEditingController();
      addTearDown(scroll.dispose);
      addTearDown(query.dispose);
      var selected = 10;
      late StateSetter refresh;
      await show(
        tester,
        StatefulBuilder(
          builder: (context, update) {
            refresh = update;
            return Column(
              children: [
                TextField(controller: query),
                Expanded(
                  child: ListView.builder(
                    controller: scroll,
                    itemCount: 40,
                    itemBuilder: (context, i) => QueueTaskRow(
                      key: ValueKey(i),
                      task: {...task, 'name': '任务 $i'},
                      selected: selected == i,
                      onTap: () => update(() => selected = i),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
        size: const Size(640, 800),
        scale: 1.5,
      );
      await tester.enterText(find.byType(TextField), '保留关键词');
      scroll.jumpTo(400);
      await tester.pump();
      final focus = FocusManager.instance.primaryFocus;
      final offset = scroll.offset;
      refresh(() {});
      await tester.pumpAndSettle();
      expect(query.text, '保留关键词');
      expect(FocusManager.instance.primaryFocus, same(focus));
      expect(scroll.offset, offset);
      expect(selected, 10);
      expect(tester.takeException(), isNull);
    },
  );
}
