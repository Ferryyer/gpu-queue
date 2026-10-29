import 'package:fl_lib/fl_lib.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/service/diagnostics_upload.dart';
import 'package:server_box/data/model/app/diagnostics_level.dart';
import 'package:server_box/data/res/store.dart';
import 'package:server_box/data/store/setting.dart';

import '../../helpers/test_db.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    await openTestDb();
    getIt.registerSingleton<SettingStore>(SettingStore('setting_test'));
    Stores.setting.diagnosticsConsentVer.put(kDiagnosticsConsentVer);
  });

  tearDown(() async {
    Stores.setting.diagnosticsLevel.put(DiagnosticsLevel.none.name);
    await DiagnosticsUpload.sync();
    await getIt.reset();
    await SqliteDb.close();
  });

  test('old upload choices and consent cannot reactivate transmission', () async {
    for (final choice in ['basic', 'full']) {
      Stores.setting.diagnosticsLevel.put(choice);
      Stores.setting.diagnosticsConsentVer.put(kDiagnosticsConsentVer);
      await Future.wait([DiagnosticsUpload.sync(), DiagnosticsUpload.sync()]);
      expect(DiagnosticsUpload.availableInBuild, isFalse);
      expect(DiagnosticsUpload.dsn, isEmpty);
      expect(DiagnosticsUpload.uploading, isFalse);
      expect(DiagnosticsUpload.level, DiagnosticsLevel.none);
      expect(Stores.setting.diagnosticsLevel.fetch(), 'none');
      expect(Stores.setting.diagnosticsConsentVer.fetch(), 0);
    }
  });
}
