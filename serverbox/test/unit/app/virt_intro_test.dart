import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/app.dart';
import 'package:server_box/data/res/store.dart';
import 'package:server_box/data/store/setting.dart';

import '../../helpers/test_db.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() async {
    await openTestDb();
    getIt.registerSingleton<SettingStore>(SettingStore('setting_test'));
  });
  tearDown(() async { await getIt.reset(); await closeTestDb(); });

  test('existing users do not get the removed virtualization introduction', () async {
    Stores.setting.introVer.put(2011);
    Stores.setting.featureIntroVer.put(1);
    expect(await introBuilders(), isEmpty);
  });

  test('SSH setup is available on first launch without changing diagnostics consent', () async {
    Stores.setting.introVer.put(0);
    Stores.setting.featureIntroVer.put(2);
    final consent = Stores.setting.diagnosticsConsentVer.fetch();
    expect(await introBuilders(), hasLength(1));
    expect(Stores.setting.diagnosticsConsentVer.fetch(), consent);
  });
}
