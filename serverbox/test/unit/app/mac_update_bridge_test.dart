import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/update/mac_update_bridge.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(
    () => messenger.setMockMethodCallHandler(MacUpdateBridge.channel, null),
  );

  test(
    'reads the real running bundle, even with stale generated UI data',
    () async {
      messenger.setMockMethodCallHandler(MacUpdateBridge.channel, (call) async {
        expect(call.method, 'installedBuild');
        return '2004';
      });
      expect(await MacUpdateBridge.installedBuild(), 2004);
    },
  );

  for (final invalid in <String?>[null, '', 'unknown', '0', '-1']) {
    test('fails closed for invalid native build $invalid', () async {
      messenger.setMockMethodCallHandler(
        MacUpdateBridge.channel,
        (_) async => invalid,
      );
      await expectLater(MacUpdateBridge.installedBuild(), throwsStateError);
    });
  }

  test(
    'does not fall back to generated data when the native read fails',
    () async {
      messenger.setMockMethodCallHandler(MacUpdateBridge.channel, (_) async {
        throw PlatformException(code: 'unavailable');
      });
      await expectLater(
        MacUpdateBridge.installedBuild(),
        throwsA(isA<PlatformException>()),
      );
    },
  );
}
