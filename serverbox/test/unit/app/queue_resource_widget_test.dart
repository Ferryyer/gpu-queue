import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/view/page/gpu_queue/resource.dart';

void main() {
  Map<String, dynamic> resource({int age = 10}) => {
    'id': 'fixture-instance',
    'status': 'online',
    'telemetry': {
      'at': DateTime.now().millisecondsSinceEpoch / 1000 - age,
      'gpus': [
        {
          'index': 0,
          'name': 'H100',
          'used_mb': 40960,
          'total_mb': 81920,
          'utilization': 65,
          'temperature_c': 61,
        },
        {
          'index': 1,
          'name': 'H100',
          'used_mb': 0,
          'total_mb': 81920,
          'utilization': 0,
        },
      ],
    },
  };
  Future<void> show(
    WidgetTester tester,
    Map<String, dynamic> data, {
    bool connected = true,
  }) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: QueueResourceView(resource: data, connected: connected),
          ),
        ),
      ),
    );
  }

  testWidgets(
    'multi GPU monitor renders units, missing metrics and opt-in diagnostics at 390px',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await show(tester, resource());
      expect(find.text('GPU 0 · H100'), findsOneWidget);
      expect(find.text('GPU 1 · H100'), findsOneWidget);
      expect(find.text('利用率 65%'), findsOneWidget);
      expect(find.text('利用率 0%'), findsOneWidget);
      expect(find.text('显存已用 / 总量 40.0 / 80.0 GiB'), findsOneWidget);
      expect(find.text('温度 —'), findsOneWidget);
      expect(find.textContaining('temperature_c'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('查看采样时间 / 诊断数据'));
      await tester.pumpAndSettle();
      expect(find.text('采样诊断 · 原始数据'), findsOneWidget);
      expect(find.textContaining('temperature_c'), findsOneWidget);
      await tester.tap(find.text('关闭'));
      await tester.pumpAndSettle();
      expect(find.textContaining('temperature_c'), findsNothing);
    },
  );
  testWidgets(
    'stale and disconnected monitors cannot present cached numbers as live',
    (tester) async {
      addTearDown(() => tester.binding.setSurfaceSize(null));
      for (final connected in [true, false]) {
        await show(
          tester,
          resource(age: connected ? 120 : 10),
          connected: connected,
        );
        expect(find.textContaining('上次采样 · 非实时'), findsOneWidget);
        expect(find.text('利用率 —'), findsNWidgets(2));
        expect(find.text('利用率 65%'), findsNothing);
        expect(find.text('温度 61 °C'), findsNothing);
        expect(tester.takeException(), isNull);
      }
    },
  );
}
