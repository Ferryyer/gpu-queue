import 'package:flutter/gestures.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/gpu_queue/swipe_delete.dart';
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

  testWidgets('swipe reveals pale red delete but never deletes without a click', (tester) async {
    for (final dark in [false, true]) {
      var deleted = 0, opened = 0;
      await show(tester, Align(alignment: Alignment.topCenter, child: QueueSwipeDelete(
        key: ValueKey(dark),
        onDelete: () => deleted++,
        child: QueueTaskRow(task: task, selected: false, onTap: () => opened++),
      )), size: const Size(390, 600), dark: dark);
      final button = find.widgetWithText(TextButton, '删除');
      expect(button.hitTestable(), findsNothing);
      await tester.drag(find.byType(QueueTaskRow), const Offset(-350, 0));
      await tester.pumpAndSettle();
      expect(deleted, 0);
      expect(button.hitTestable(), findsOneWidget);
      await tester.tap(button);
      expect(deleted, 1);
      expect(opened, 0);
      await tester.drag(find.byType(QueueSwipeDelete), const Offset(120, 0));
      await tester.pumpAndSettle();
      expect(button.hitTestable(), findsNothing);
      expect(tester.takeException(), isNull);
    }
  });

  testWidgets('trackpad horizontal scroll reveals deletion; vertical scroll does not', (tester) async {
    await show(tester, Align(alignment: Alignment.topCenter, child: QueueSwipeDelete(
      onDelete: () {}, child: QueueTaskRow(task: task, selected: false, onTap: () {}),
    )), size: const Size(390, 600));
    final point = tester.getCenter(find.byType(QueueTaskRow));
    final button = find.widgetWithText(TextButton, '删除');
    await tester.sendEventToBinding(PointerScrollEvent(position: point, scrollDelta: const Offset(0, 80)));
    await tester.pumpAndSettle();
    expect(button.hitTestable(), findsNothing);
    await tester.sendEventToBinding(PointerScrollEvent(position: point, scrollDelta: const Offset(12, 0)));
    await tester.pumpAndSettle();
    expect(button.hitTestable(), findsOneWidget);
  });

  testWidgets('a running task can reveal only a disabled delete action', (tester) async {
    await show(tester, Align(alignment: Alignment.topCenter, child: QueueSwipeDelete(
      onDelete: null, disabledReason: '请先停止任务并等待服务器确认',
      child: QueueTaskRow(task: {...task, 'state': 'running'}, selected: false, onTap: () {}),
    )), size: const Size(390, 600));
    await tester.drag(find.byType(QueueTaskRow), const Offset(-180, 0));
    await tester.pumpAndSettle();
    expect(tester.widget<TextButton>(find.widgetWithText(TextButton, '删除')).onPressed, isNull);
    expect(find.byTooltip('请先停止任务并等待服务器确认'), findsOneWidget);
  });

  testWidgets('employee welcome and overview work with large text on narrow screens', (tester) async {
    for (final dark in [false, true]) {
      var adds = 0, guides = 0;
      await show(tester, QueueWelcome(hasServers: false, onAdd: () => adds++, onGuide: () => guides++), size: const Size(390, 600), scale: 1.5, dark: dark);
      await tester.ensureVisible(find.text('添加服务器'));
      await tester.tap(find.text('添加服务器'));
      await tester.tap(find.text('员工接入指南'));
      expect(adds, 1);
      expect(guides, 1);
      expect(tester.takeException(), isNull);
      String? filter;
      await show(tester, QueueOverview(tasks: [
        {'state': 'execution_unknown'}, {'state': 'waiting_gpu'}, {'state': 'completed'},
      ], filter: 'all', onFilter: (value) => filter = value), size: const Size(390, 600), scale: 1.5, dark: dark);
      expect(find.text('需要处理 1'), findsOneWidget);
      expect(find.text('等待资源 1'), findsOneWidget);
      await tester.tap(find.text('需要处理 1'));
      expect(filter, 'failed');
      expect(tester.takeException(), isNull);
    }
  });

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
      await tester.tap(find.text('终端'));
      expect(destination, 3);
      await tester.tap(find.text('文件'));
      expect(destination, 4);
      await tester.tap(find.text('飞书任务'));
      expect(destination, 5);
      expect(find.text('GPU 任务'), findsOneWidget);
      await tester.tap(find.byTooltip('收起侧栏'));
      await tester.pumpAndSettle();
      expect(tester.getSize(find.byType(QueueSidebar)).width, 64);
      await tester.tap(find.byIcon(Icons.terminal_outlined));
      expect(destination, 3);
      await tester.tap(find.byIcon(Icons.folder_open));
      expect(destination, 4);
      await tester.tap(find.byIcon(Icons.settings_outlined));
      expect(settings, 1);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byTooltip('展开侧栏'));
      await tester.pumpAndSettle();
      expect(find.text('GPU 任务'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('terminal is selected independently of more tools in a small window', (tester) async {
    for (final selected in [0, 3, 4, 5, 6]) {
      await show(tester, Row(children: [
        QueueSidebar(selected: selected, onSelect: (_) {}, onSettings: () {}, onMore: () {}),
        const Expanded(child: SizedBox()),
      ]), size: const Size(760, 600), scale: 1.5);
      for (final entry in {'总览': 0, '终端': 3, '文件': 4, '飞书任务': 5, '更多工具': 6}.entries) {
        final tile = tester.widget<ListTile>(find.ancestor(of: find.text(entry.key), matching: find.byType(ListTile)));
        expect(tile.selected, selected == entry.value);
      }
      expect(tester.takeException(), isNull);
    }
  });

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
