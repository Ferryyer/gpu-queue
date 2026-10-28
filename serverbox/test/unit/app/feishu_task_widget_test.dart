import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/utils/gpu_queue_theme.dart';
import 'package:server_box/view/page/feishu/page.dart';

void main() {
  testWidgets('Mac task header and options fit narrow and wide windows', (tester) async {
    final messenger = tester.binding.defaultBinaryMessenger;
    messenger.setMockMessageHandler('flutter/assets', (message) async {
      return ByteData.sublistView(Uint8List.fromList('/* fixture script */'.codeUnits));
    });
    messenger.setMockMethodCallHandler(SystemChannels.platform_views, (_) async => null);
    addTearDown(() {
      messenger.setMockMessageHandler('flutter/assets', null);
      messenger.setMockMethodCallHandler(SystemChannels.platform_views, null);
    });
    for (final width in [360.0, 768.0, 1200.0]) {
      await tester.binding.setSurfaceSize(Size(width, 700));
      await tester.pumpWidget(MaterialApp(theme: gpuQueueTheme(ThemeData()),
        home: const Scaffold(body: FeishuTaskPage())));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byType(AppKitView), findsOneWidget);
      expect((tester.widget<AppKitView>(find.byType(AppKitView)).creationParams as Map)['embedded'], isFalse);
      expect(find.text('飞书任务'), findsOneWidget);
      expect(find.byTooltip('在浏览器打开'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byTooltip('页面选项'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Inspire 风格'), findsOneWidget);
      await tester.tap(find.text('回到我负责的'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.takeException(), isNull);
    }
    await tester.pumpWidget(const SizedBox());
    await tester.binding.setSurfaceSize(null);
  }, variant: TargetPlatformVariant({TargetPlatform.macOS}));

  testWidgets('other platforms offer the same task URL in the browser', (tester) async {
    await tester.pumpWidget(MaterialApp(home: const Scaffold(body: FeishuTaskPage())));
    expect(find.byType(AppKitView), findsNothing);
    expect(find.text('在浏览器打开飞书任务'), findsOneWidget);
    await tester.tap(find.byTooltip('收起提示'));
    await tester.pump();
    expect(find.textContaining('首次使用'), findsNothing);
  }, variant: TargetPlatformVariant({TargetPlatform.windows}));
}
