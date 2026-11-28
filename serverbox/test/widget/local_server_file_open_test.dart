import 'dart:io';

import 'package:fl_lib/fl_lib.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/extension/context/locale.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/misc.dart';
import 'package:server_box/data/res/status.dart';
import 'package:server_box/data/res/store.dart';
import 'package:server_box/data/store/history.dart';
import 'package:server_box/data/store/setting.dart';
import 'package:server_box/generated/l10n/l10n.dart';
import 'package:server_box/view/page/storage/file_browser.dart';
import 'package:server_box/view/page/storage/server_file.dart';
import 'package:server_box/view/page/storage/sftp.dart';

import '../helpers/test_db.dart';

const _spi = Spi(name: 'Test device', id: 'test-local', local: true);
const _largeName = 'oversized.txt';

class _LocalServerNotifier extends ServerNotifier {
  @override
  ServerState build(String id) =>
      ServerState(spi: _spi, status: InitStatus.status);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory directory;
  late File report;

  setUp(() async {
    directory = await Directory.systemTemp.createTemp('local-server-file-');
    report = await File(
      '${directory.path}/report.txt',
    ).writeAsString('Example report');
    final oversized = await File(
      '${directory.path}/$_largeName',
    ).open(mode: FileMode.write);
    await oversized.truncate(Miscs.editorMaxSize + 1);
    await oversized.close();
    await Directory('${directory.path}/folder').create();
    await openTestDb();
    getIt.registerSingleton<SettingStore>(SettingStore('setting_test'));
    getIt.registerSingleton<HistoryStore>(HistoryStore('history_test'));
  });

  tearDown(() async {
    await getIt.reset();
    await closeTestDb();
    await directory.delete(recursive: true);
  });

  Future<void> pumpBrowser(WidgetTester tester, {bool isSelect = false}) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          serverProvider(_spi.id).overrideWith(_LocalServerNotifier.new),
        ],
        child: MaterialApp(
          localizationsDelegates: appLocalizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: ServerFilePage(
            args: SftpPageArgs(
              spi: _spi,
              initPath: directory.path.replaceAll(r'\', '/'),
              isSelect: isSelect,
            ),
          ),
        ),
      ),
    );
    // Wait for both real filesystem I/O and the widgets driven by fake time.
    final row = find.text(_largeName);
    final wait = Stopwatch()..start();
    const interval = Duration(milliseconds: 20);
    while (row.evaluate().isEmpty &&
        wait.elapsed < const Duration(seconds: 5)) {
      await tester.runAsync(() => Future<void>.delayed(interval));
      await tester.pump(interval);
    }
    expect(row, findsOneWidget);
    await tester.pumpAndSettle();
  }

  String sizeWarning() => l10n.fileTooLarge(
    _largeName,
    (Miscs.editorMaxSize + 1).bytes2Str,
    Miscs.editorMaxSize.bytes2Str,
  );

  testWidgets('a local file opens the editor and has file menu actions', (
    tester,
  ) async {
    await pumpBrowser(tester);
    final browser = tester.widget<FileBrowserPage>(
      find.byType(FileBrowserPage),
    );
    expect(browser.args.onOpenFile, isNotNull);
    expect(browser.args.entryActions, isNotNull);

    final row = find.text('report.txt');
    await tester.longPress(row);
    await tester.pumpAndSettle();
    expect(find.text(libL10n.open), findsOneWidget);
    expect(find.text(libL10n.edit), isMobile ? findsOneWidget : findsNothing);
    Navigator.of(tester.element(find.text(libL10n.open))).pop();
    await tester.pumpAndSettle();

    await tester.longPress(find.text('folder'));
    await tester.pumpAndSettle();
    expect(find.text(libL10n.open), findsNothing);
    expect(find.text(libL10n.edit), findsNothing);
    Navigator.of(tester.element(find.byType(FileBrowserPage))).pop();
    await tester.pumpAndSettle();

    await tester.tap(row);
    await tester.pump();
    await tester.pump(Durations.long4);
    expect(
      tester.widget<EditorPage>(find.byType(EditorPage)).args?.path,
      report.path,
    );
  });

  testWidgets('opening an oversized local file shows its size and limit', (
    tester,
  ) async {
    await pumpBrowser(tester);

    await tester.tap(find.text(_largeName));
    await tester.pumpAndSettle();

    expect(find.text(sizeWarning()), findsOneWidget);
    expect(find.byType(EditorPage), findsNothing);
  });

  testWidgets('directory selection leaves file taps and menus inert', (
    tester,
  ) async {
    await pumpBrowser(tester, isSelect: true);
    final row = find.text(_largeName);

    await tester.tap(row);
    await tester.longPress(row);
    await tester.pumpAndSettle();

    expect(find.text(sizeWarning()), findsNothing);
    expect(find.text(libL10n.open), findsNothing);
    expect(find.byType(EditorPage), findsNothing);
    expect(find.byTooltip(libL10n.ok), findsOneWidget);
  });
}
