import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/gpu_queue/presentation.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/gpu_queue/resource.dart';

void main() {
  final now = DateTime.utc(2026, 10, 26, 7);
  final seconds = now.millisecondsSinceEpoch / 1000;
  Map<String, dynamic> resource(
    String id,
    String model,
    int index, {
    String status = 'online',
    num age = 10,
    num? load = 78,
  }) => {
    'id': id,
    'type': model.contains('4090') ? '4090联网' : 'H卡离线',
    'status': status,
    'telemetry': {
      'at': seconds - age,
      'gpus': [
        {
          'index': index,
          'uuid': 'GPU-example-$id',
          'name': model,
          'utilization': load,
          'used_mb': model.contains('4090') ? 16384 : 40960,
          'total_mb': model.contains('4090') ? 24576 : 81920,
          'temperature_c': 63,
        },
      ],
    },
  };
  final rows = [
    resource('h100', 'NVIDIA H100 80GB HBM3', 0, load: 0),
    resource('4090', 'NVIDIA GeForce RTX 4090', 0),
  ];
  Future<void> show(
    WidgetTester tester,
    Widget body, {
    Size size = const Size(1100, 800),
    bool dark = false,
    double scale = 1,
  }) async {
    await tester.binding.setSurfaceSize(size);
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
          child: Scaffold(body: SingleChildScrollView(child: body)),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  test(
    'summary counts actual GPUs across models, sorts current first and keeps history distinct',
    () {
      final history = resource('old', 'Old GPU', 0, status: 'closed');
      final stale = resource('stale', 'A100', 0, age: 120, status: 'unknown');
      expect(
        QueuePresentation.monitorSummary(
          [...rows, stale, history],
          now,
          connected: true,
        ),
        '2 张 GPU 实时监测 · 1 份资源待恢复',
      );
      expect(
        QueuePresentation.orderedResources(
          [history, ...rows],
          now,
          connected: true,
        ).last['id'],
        'old',
      );
      expect(
        QueuePresentation.monitorSummary(rows, now, connected: false),
        '连接中断 · 保留最后读数',
      );
      expect(
        QueuePresentation.monitorSummary(
          [rows.first, rows.first],
          now,
          connected: true,
        ),
        '1 张 GPU 实时监测',
      );
    },
  );

  testWidgets(
    'native monitor is expanded, shows mixed models, and replaces a GPU on allocation switch',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await show(
        tester,
        QueueMonitorView(resources: rows, connected: true, now: now),
      );
      expect(find.text('GPU 占用监测'), findsOneWidget);
      expect(find.text('2 张 GPU 实时监测'), findsOneWidget);
      expect(find.text('GPU 0 · NVIDIA H100 80GB HBM3'), findsOneWidget);
      expect(find.text('GPU 0 · NVIDIA GeForce RTX 4090'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNWidgets(2));
      await show(
        tester,
        QueueMonitorView(resources: [rows.last], connected: true, now: now),
      );
      expect(find.text('GPU 0 · NVIDIA H100 80GB HBM3'), findsNothing);
      expect(find.text('1 张 GPU 实时监测'), findsOneWidget);
    },
  );

  testWidgets(
    'disconnect keeps explicitly historical counters; recovered sample becomes live',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final data = rows.last;
      await show(
        tester,
        QueueResourceView(resource: data, connected: false, now: now),
      );
      expect(find.text('连接中断'), findsOneWidget);
      expect(find.textContaining('最后读数'), findsOneWidget);
      expect(find.text('利用率 78%'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNothing);
      await show(
        tester,
        QueueResourceView(resource: data, connected: true, now: now),
      );
      expect(find.text('实时采样'), findsOneWidget);
      expect(find.textContaining('最后读数'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
    },
  );

  testWidgets(
    'retry state, process-query failure and unsupported readings are distinct from idle',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final data = resource(
        'retry',
        'NVIDIA A100',
        0,
        status: 'unknown',
        age: 120,
        load: null,
      );
      data['monitor'] = {'state': 'retry', 'retry_at': seconds + 30};
      data['telemetry']['apps_known'] = false;
      await show(
        tester,
        QueueResourceView(resource: data, connected: true, now: now),
      );
      expect(find.text('自动恢复中'), findsOneWidget);
      expect(find.textContaining('秒后重试'), findsOneWidget);
      expect(find.text('利用率 —'), findsOneWidget);
      expect(find.textContaining('暂不复用'), findsOneWidget);
      final historical = QueuePresentation.lastGpus(data, now).single;
      expect(historical.fresh, false);
      expect(historical.historical, true);
      data['telemetry']['at'] = seconds + 20;
      expect(QueuePresentation.lastGpus(data, now), isEmpty);
    },
  );

  testWidgets(
    'native GPU cards fit narrow and large-text layouts in light and dark modes',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      for (final width in [390.0, 900.0]) {
        for (final scale in [1.0, 1.5]) {
          for (final dark in [false, true]) {
            await show(
              tester,
              Column(
                children: [
                  for (final r in rows)
                    QueueResourceView(resource: r, connected: true, now: now),
                ],
              ),
              size: Size(width, 900),
              dark: dark,
              scale: scale,
            );
            expect(tester.takeException(), isNull);
            expect(find.text('利用率 0%'), findsOneWidget);
          }
        }
      }
    },
  );

  testWidgets('capture production native GPU cards when explicitly requested', (
    tester,
  ) async {
    final directory = Platform.environment['GPU_MONITOR_SCREENSHOT_DIR'];
    if (directory == null) return;
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final fontPath = Platform.environment['GPU_MONITOR_SCREENSHOT_FONT'];
    if (fontPath != null) {
      final bytes = File(fontPath).readAsBytesSync();
      for (final family in [
        '.AppleSystemUIFont',
        'Roboto',
        'Ahem',
        'CupertinoSystemText',
        'CupertinoSystemDisplay',
        '.SF Pro Text',
        '.SF Pro Display',
        '.SF UI Text',
      ]) {
        final loader = FontLoader(family)
          ..addFont(Future.value(ByteData.sublistView(bytes)));
        await tester.runAsync(loader.load);
      }
    }
    final key = GlobalKey();
    for (final width in [1100.0, 390.0]) {
      await show(
        tester,
        RepaintBoundary(
          key: key,
          child: ColoredBox(
            color: const Color(0xFFFAF9F6),
            child: Column(
              children: [
                const Padding(
                  padding: EdgeInsets.all(20),
                  child: Text('GPU 占用监测 · App 示例数据'),
                ),
                for (final r in rows)
                  QueueResourceView(resource: r, connected: true, now: now),
              ],
            ),
          ),
        ),
        size: Size(width, 900),
      );
      final boundary =
          key.currentContext!.findRenderObject() as RenderRepaintBoundary;
      await tester.runAsync(() async {
        final image = await boundary.toImage(pixelRatio: 1);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        Directory(directory).createSync(recursive: true);
        File(
          '$directory/app-gpu-${width.toInt()}.png',
        ).writeAsBytesSync(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
  });
}
