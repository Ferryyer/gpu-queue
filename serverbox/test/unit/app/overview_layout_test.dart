import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/feishu/page.dart';
import 'package:server_box/view/page/overview/layout.dart';

void main() {
  testWidgets('all three sections remain reachable at small and large sizes', (tester) async {
    for (final width in [360.0, 680.0, 900.0, 1340.0, 1600.0]) {
      await tester.binding.setSurfaceSize(Size(width, 800));
      await tester.pumpWidget(MaterialApp(theme: gpuQueueTheme(ThemeData()), home: const Scaffold(
        body: OverviewLayout(gpu: Text('GPU area'), feishu: Text('Feishu area'), calendar: Text('Calendar area')))));
      await tester.pump();
      expect(find.text('GPU area'), findsOneWidget);
      expect(find.text('Feishu area'), findsOneWidget);
      expect(find.text('Calendar area'), findsOneWidget);
      await tester.ensureVisible(find.text('Calendar area'));
      await tester.pump();
      expect(tester.takeException(), isNull);
    }
    await tester.pumpWidget(const SizedBox());
    await tester.binding.setSurfaceSize(null);
  });

  testWidgets('embedded Feishu keeps native view and expands without login hint overflow', (tester) async {
    final messenger = tester.binding.defaultBinaryMessenger;
    messenger.setMockMessageHandler('flutter/assets', (_) async => ByteData.sublistView(Uint8List.fromList('/* test */'.codeUnits)));
    messenger.setMockMethodCallHandler(SystemChannels.platform_views, (_) async => null);
    addTearDown(() {
      messenger.setMockMessageHandler('flutter/assets', null);
      messenger.setMockMethodCallHandler(SystemChannels.platform_views, null);
    });
    var expanded = false;
    await tester.binding.setSurfaceSize(const Size(360, 700));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: OverviewLayout(
      gpu: const Text('GPU'), calendar: const Text('Calendar'),
      feishu: FeishuTaskPage(embedded: true, onExpand: () => expanded = true),
    ))));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byType(AppKitView), findsOneWidget);
    expect((tester.widget<AppKitView>(find.byType(AppKitView)).creationParams as Map)['embedded'], isTrue);
    expect(find.textContaining('首次使用'), findsNothing);
    await tester.ensureVisible(find.byTooltip('打开完整飞书任务页'));
    await tester.tap(find.byTooltip('打开完整飞书任务页'));
    expect(expanded, isTrue);
    expect(tester.takeException(), isNull);
    final webState = tester.state(find.byType(AppKitView));
    for (final width in [900.0, 1600.0, 360.0, 900.0]) {
      await tester.binding.setSurfaceSize(Size(width, 800));
      await tester.pump();
      expect(tester.state(find.byType(AppKitView)), same(webState),
        reason: 'Resizing must not recreate the authenticated native document');
      expect(tester.takeException(), isNull);
    }
    await tester.pumpWidget(const SizedBox());
    await tester.binding.setSurfaceSize(null);
  }, variant: TargetPlatformVariant({TargetPlatform.macOS}));
}
