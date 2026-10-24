import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/gpu_queue/workspace.dart';

void main() {
  final tasks = <Map<String, dynamic>>[
    {
      'id': 'GQ-fixture00000001',
      'name': '视觉模型 · 第一阶段训练',
      'project': '视觉实验',
      'state': 'running',
      'agent': 'Codex',
      'steps': ['训练', '评测', '导出'],
      'stage': 1,
    },
    {
      'id': 'GQ-fixture00000002',
      'name': '文本检索 · 验证集评测',
      'project': '检索实验',
      'state': 'queued',
      'agent': 'Claude',
      'steps': ['准备', '评测', '汇总'],
    },
    {
      'id': 'GQ-fixture00000003',
      'name': '多模态长标题与中文 English 混排的任务，用于验证窄屏换行与状态按钮',
      'description': '代码与配置已固定，准备好后由你决定何时开始。',
      'project': '多模态实验',
      'state': 'ready',
      'agent': 'Codex',
      'steps': ['训练', '评测', '推理'],
      'resources': {'gpus': 1, 'memory_gb': 24},
      'version': 'fixture-a1b2c3',
    },
  ];

  setUpAll(() async {
    // Optional Linux fonts for review artifacts; production loads no test fonts.
    for (final entry in {
      'WenQuanYi Micro Hei': Platform.environment['GPU_QUEUE_TEST_CJK_FONT'],
      'DejaVu Serif': Platform.environment['GPU_QUEUE_TEST_SERIF_FONT'],
      'Roboto': Platform.environment['GPU_QUEUE_TEST_ROBOTO_FONT'],
      'MaterialIcons': Platform.environment['GPU_QUEUE_TEST_ICON_FONT'],
    }.entries) {
      if (entry.value == null) continue;
      final loader = FontLoader(entry.key)
        ..addFont(
          File(
            entry.value!,
          ).readAsBytes().then((bytes) => ByteData.sublistView(bytes)),
        );
      await loader.load();
    }
  });

  Future<void> capture(WidgetTester tester, GlobalKey key, String name) async {
    final dir = Platform.environment['GPU_QUEUE_EVIDENCE_DIR'];
    if (dir == null) return;
    // Real production widgets rendered by the Flutter CPU engine, not a Mac app capture.
    final image =
        await (key.currentContext!.findRenderObject() as RenderRepaintBoundary)
            .toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    await File('$dir/$name.png').writeAsBytes(bytes!.buffer.asUint8List());
    image.dispose();
  }

  testWidgets(
    'native workspace reflows at small, short, wide and enlarged text sizes in both themes',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      for (final brightness in [Brightness.light, Brightness.dark]) {
        for (final (size, scale) in [
          (const Size(390, 844), 1.0),
          (const Size(320, 640), 1.5),
          (const Size(1440, 1000), 1.0),
          (const Size(1100, 500), 1.0),
          (const Size(1100, 800), 2.0),
        ]) {
          await tester.binding.setSurfaceSize(size);
          final scroll = ScrollController(), captureKey = GlobalKey();
          var selections = 0;
          final base = ThemeData(
            platform: TargetPlatform.linux,
            brightness: brightness,
            fontFamily: Platform.environment['GPU_QUEUE_TEST_CJK_FONT'] == null
                ? null
                : 'WenQuanYi Micro Hei',
          );
          await tester.pumpWidget(
            MaterialApp(
              theme: gpuQueueTheme(base),
              home: MediaQuery(
                data: MediaQueryData(
                  size: size,
                  textScaler: TextScaler.linear(scale),
                ),
                child: RepaintBoundary(
                  key: captureKey,
                  child: Scaffold(
                    appBar: AppBar(title: const Text('GPU Queue · 原生组件预览')),
                    body: QueueWorkspaceView(
                      tasks: tasks,
                      allTasks: tasks,
                      selected: tasks.last['id'],
                      overview: true,
                      controller: scroll,
                      onSelect: (_, _) => selections++,
                      onQuery: (_) {},
                      filter: 'all',
                      onFilter: (_) {},
                      detail: ListView(
                        padding: const EdgeInsets.all(24),
                        children: [
                          QueueTaskHeading(task: tasks.last),
                          FilledButton(
                            onPressed: () {},
                            child: const Text('开始这一版任务'),
                          ),
                          const SizedBox(height: 24),
                          Text(
                            '执行步骤与日志',
                            style: gpuQueueTheme(base).textTheme.titleLarge,
                          ),
                          for (final step in ['训练', '评测', '推理'])
                            ListTile(
                              leading: const Icon(Icons.circle_outlined),
                              title: Text(step),
                              subtitle: const Text('等待执行'),
                            ),
                        ],
                      ),
                      monitor: const ExpansionTile(
                        title: Text('服务器与 GPU'),
                        subtitle: Text('按需展开监控'),
                        children: [Text('示例数据 · 非实时')],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
          await tester.pumpAndSettle();
          expect(
            tester.takeException(),
            isNull,
            reason: '$brightness $size $scale',
          );
          if (scale == 1 && size.width != 1100) {
            await tester.runAsync(
              () => capture(
                tester,
                captureKey,
                'native-${size.width.toInt()}-${brightness.name}',
              ),
            );
          }
          await tester.scrollUntilVisible(
            find.text('视觉模型 · 第一阶段训练'),
            180,
            scrollable: find.byType(Scrollable).first,
          );
          await tester.ensureVisible(find.text('视觉模型 · 第一阶段训练'));
          await tester.pumpAndSettle();
          await tester.tap(find.text('视觉模型 · 第一阶段训练'));
          await tester.pumpAndSettle();
          expect(selections, 1);
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox.shrink());
          scroll.dispose();
        }
      }
    },
  );

  testWidgets(
    'task tile remains keyboard operable without a direct start action',
    (tester) async {
      var selected = false;
      var task = tasks.last;
      late StateSetter refresh;
      await tester.pumpWidget(
        MaterialApp(
          theme: gpuQueueTheme(ThemeData()),
          home: StatefulBuilder(
            builder: (context, setState) {
              refresh = setState;
              return Scaffold(
                body: QueueTaskTile(
                  key: ValueKey(task['id']),
                  task: task,
                  selected: false,
                  onTap: () => selected = true,
                ),
              );
            },
          ),
        ),
      );
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      final focused = FocusManager.instance.primaryFocus;
      refresh(() => task = {...task, 'state': 'queued'});
      await tester.pumpAndSettle();
      expect(FocusManager.instance.primaryFocus, same(focused));
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(selected, isTrue);
      expect(find.text('开始这一版任务'), findsNothing);
    },
  );
}
