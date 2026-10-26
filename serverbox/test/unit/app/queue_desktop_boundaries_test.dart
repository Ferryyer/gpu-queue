import 'dart:io';

import 'package:flutter/gestures.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/gpu_queue/workspace.dart';

void main() {
  // Supply an actual CJK font for the desktop geometry audit on Linux.
  // No Mac font claims are made by these CPU widget tests.
  setUpAll(() async {
    final path = Platform.environment['QUEUE_TEST_CJK_FONT'];
    if (path == null) return;
    for (final family in ['.AppleSystemUIFont', 'PingFang SC', 'Roboto']) {
      await (FontLoader(
        family,
      )..addFont(File(path).readAsBytes().then(ByteData.sublistView))).load();
    }
  });
  final task = <String, dynamic>{
    'id': 'boundary-task',
    'name': '时间折叠 · MiniMax H3 四幕60秒电影',
    'project': 'folded-time-gpuq',
    'resources': {'gpus': 1, 'memory_gb': 80},
    'updated_at': '2026-10-26T15:00:00+08:00',
  };
  Future<void> show(
    WidgetTester tester,
    Widget body,
    Size size, {
    double scale = 1,
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: gpuQueueTheme(ThemeData(platform: TargetPlatform.macOS)),
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

  testWidgets('desktop rows expose status, resources and single-line actions', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();

    for (final width in [300.0, 390.0, 560.0, 656.0, 900.0]) {
      for (final scale in [1.0, 1.5]) {
        for (final state in [
          'ready',
          'waiting_gpu',
          'checking_resources',
          'execution_unknown',
        ]) {
          var actions = 0;
          final label = state == 'ready' ? '开始' : '查看日志';
          await show(
            tester,
            Align(
              alignment: Alignment.topLeft,
              child: QueueTaskRow(
                task: {...task, 'state': state},
                selected: false,
                onTap: () {},
                action: TextButton(
                  onPressed: () => actions++,
                  child: Text(label, maxLines: 1, softWrap: false),
                ),
              ),
            ),
            Size(width, 800),
            scale: scale,
          );
          for (final text in [
            QueuePresentation.compactTaskStatus(state),
            '1 GPU / 80 GB',
            label,
          ]) {
            final paragraph = tester.renderObject<RenderParagraph>(
              find.text(text),
            );
            expect(
              paragraph.didExceedMaxLines,
              isFalse,
              reason: '$width / $scale / $state / $text',
            );
            final boxes = paragraph.getBoxesForSelection(
              TextSelection(baseOffset: 0, extentOffset: text.length),
            );
            expect(
              boxes.map((b) => b.top).toSet().length,
              1,
              reason: '$text should fit on one line',
            );
            final row = tester.getRect(find.byType(QueueTaskRow));
            expect(
              row.contains(tester.getRect(find.text(text)).center),
              isTrue,
            );
          }
          expect(
            find.bySemanticsLabel(RegExp('执行状态待核查')),
            state == 'execution_unknown' ? findsOneWidget : findsNothing,
          );
          expect(find.byTooltip('更新 2026-10-26 07:00:00 UTC'), findsOneWidget);
          await tester.tap(find.text(label));
          expect(actions, 1);
          expect(tester.takeException(), isNull);
        }
      }
    }
    semantics.dispose();
  });

  testWidgets('short detail keeps tabs, log body and final actions reachable', (
    tester,
  ) async {
    for (final width in [300.0, 416.0]) {
      for (final height in [236.0, 300.0, 400.0, 600.0, 800.0]) {
        for (final scale in [1.0, 1.5]) {
          var tab = 1, actions = 0;
          await show(
            tester,
            StatefulBuilder(
              builder: (context, update) => QueueDetailPane(
                task: {...task, 'state': 'failed'},
                tab: tab,
                onTab: (i) => update(() => tab = i),
                onClose: () {},
                child: ListView(
                  children: [
                    const QueueLogView(
                      label: '步骤 1 · 推理 · 失败',
                      text: 'Traceback:\n    run_step()\nKeyboardInterrupt',
                    ),
                    TextButton(
                      onPressed: () => actions++,
                      child: const Text('末尾操作'),
                    ),
                  ],
                ),
              ),
            ),
            Size(width, height),
            scale: scale,
          );
          expect(tester.takeException(), isNull);
          final tabsBottom = tester.getRect(find.text('日志')).bottom;
          expect(height - tabsBottom, greaterThan(64));
          await tester.tap(find.text('结果'));
          await tester.pumpAndSettle();
          expect(tab, 2);
          await tester.tap(find.text('日志'));
          await tester.pumpAndSettle();
          final body = find.byType(ListView);
          await tester.drag(body, const Offset(0, -500));
          await tester.pumpAndSettle();
          await tester.ensureVisible(find.text('末尾操作'));
          await tester.tap(find.text('末尾操作'));
          expect(actions, 1);
          // Exercise keyboard activation of a tab while the header is short.
          Focus.of(tester.element(find.text('概览'))).requestFocus();
          await tester.pump();
          await tester.sendKeyEvent(LogicalKeyboardKey.enter);
          await tester.pumpAndSettle();
          expect(tab, 0);
          expect(tester.takeException(), isNull);
        }
      }
    }
  });

  testWidgets(
    'macOS logs scroll independently and retain both axes on refresh and tabs',
    (tester) async {
      final text = List.generate(
        100,
        (i) => '    line $i ${'column ' * 50}',
      ).join('\n');
      var revision = 0, tab = 0;
      late StateSetter refresh;
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
      await show(
        tester,
        StatefulBuilder(
          builder: (context, update) {
            refresh = update;
            return IndexedStack(
              index: tab,
              children: [
                ListView(
                  children: [
                    for (var i = 0; i < 2; i++)
                      QueueLogView(
                        key: ValueKey(i),
                        label: '步骤 $i · 刷新 $revision',
                        text: '$text\n    refresh $revision',
                      ),
                  ],
                ),
                const Text('另一个页签'),
              ],
            );
          },
        ),
        const Size(416, 800),
      );
      ScrollController controller(int i, Axis axis) => tester
          .widgetList<SingleChildScrollView>(
            find.descendant(
              of: find.byType(QueueLogView).at(i),
              matching: find.byType(SingleChildScrollView),
            ),
          )
          .singleWhere((view) => view.scrollDirection == axis)
          .controller!;
      final first = controller(0, Axis.vertical),
          second = controller(1, Axis.vertical);
      final horizontal = controller(0, Axis.horizontal);
      expect(first, isNot(same(second)));
      tester.binding.handlePointerEvent(
        const PointerScrollEvent(
          position: Offset(180, 160),
          scrollDelta: Offset(0, 130),
        ),
      );
      await tester.pumpAndSettle();
      expect(first.offset, greaterThan(0));
      expect(second.offset, 0);
      // Drag the visible vertical scrollbar thumb with a mouse.
      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      await mouse.addPointer(location: const Offset(410, 95));
      await tester.pump(const Duration(milliseconds: 200));
      final beforeDrag = first.offset;
      await mouse.down(const Offset(410, 95));
      await mouse.moveBy(const Offset(0, 90));
      await mouse.up();
      await tester.pumpAndSettle();
      expect(first.offset, greaterThan(beforeDrag));
      // A trackpad pan must reach the same scroll position.
      final beforePan = first.offset;
      final trackpad = await tester.createGesture(
        kind: PointerDeviceKind.trackpad,
      );
      await trackpad.panZoomStart(const Offset(180, 160));
      await trackpad.panZoomUpdate(
        const Offset(180, 160),
        pan: const Offset(0, -80),
      );
      await tester.pump(const Duration(milliseconds: 16));
      await trackpad.panZoomUpdate(
        const Offset(180, 160),
        pan: const Offset(0, -160),
      );
      await trackpad.panZoomEnd();
      await tester.pumpAndSettle();
      expect(first.offset, greaterThan(beforePan));
      tester.binding.handlePointerEvent(
        const PointerScrollEvent(
          position: Offset(180, 160),
          scrollDelta: Offset(150, 0),
        ),
      );
      await tester.pumpAndSettle();
      expect(horizontal.offset, greaterThan(0));
      final y = first.offset, x = horizontal.offset;
      refresh(() => revision++);
      await tester.pumpAndSettle();
      expect(controller(0, Axis.vertical), same(first));
      expect(first.offset, y);
      expect(horizontal.offset, x);
      refresh(() => tab = 1);
      await tester.pumpAndSettle();
      refresh(() => tab = 0);
      await tester.pumpAndSettle();
      expect(first.offset, y);
      expect(horizontal.offset, x);
      expect(second.offset, 0);
      await tester.tap(find.byTooltip('复制日志').first);
      expect(copied, '$text\n    refresh $revision');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    },
  );
}
