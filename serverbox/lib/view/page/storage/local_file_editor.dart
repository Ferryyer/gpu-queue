import 'package:fl_lib/fl_lib.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/extension/context/locale.dart';
import 'package:server_box/core/utils/local_file_backend.dart';
import 'package:server_box/data/model/file/file_backend.dart';
import 'package:server_box/data/res/misc.dart';
import 'package:server_box/data/res/store.dart';
import 'package:server_box/view/page/storage/file_browser.dart';

List<ContextMenuAction> localFileEntryActions(
  BuildContext context,
  FileBrowserHandle handle,
  FileEntry entry,
  String fullPath,
) => [
  if (!entry.isDir) ...[
    if (isMobile)
      ContextMenuAction(
        icon: Icons.edit,
        text: libL10n.edit,
        onTap: () => openLocalFileEditor(context, handle, entry, fullPath),
      ),
    ContextMenuAction(
      icon: Icons.open_in_new,
      text: libL10n.open,
      onTap: () =>
          Pfs.sharePaths(paths: [LocalFileBackend.nativePath(fullPath)]),
    ),
  ],
];

Future<void> openLocalFileEditor(
  BuildContext context,
  FileBrowserHandle handle,
  FileEntry entry,
  String fullPath,
) async {
  final size = entry.size ?? (await handle.backend.stat(fullPath))?.size ?? 0;
  if (!context.mounted) return;
  if (size > Miscs.editorMaxSize) {
    await context.showRoundDialog(
      title: libL10n.attention,
      child: Text(
        l10n.fileTooLarge(
          entry.name,
          size.bytes2Str,
          Miscs.editorMaxSize.bytes2Str,
        ),
      ),
    );
    return;
  }

  final settings = Stores.setting;
  final font = settings.editorFontFamily.fetch();
  await EditorPage.route.go(
    context,
    args: EditorPageArgs(
      path: LocalFileBackend.nativePath(fullPath),
      onSave: (_) {
        Toast.show(libL10n.saved);
        handle.refresh();
      },
      closeAfterSave: settings.closeAfterSave.fetch(),
      softWrap: settings.editorSoftWrap.fetch(),
      enableHighlight: settings.editorHighlight.fetch(),
      lightTheme: HighlightTheme.fromThemeMapKey(settings.editorTheme.fetch()),
      darkTheme: HighlightTheme.fromThemeMapKey(
        settings.editorDarkTheme.fetch(),
      ),
      fontFamily: font.isEmpty ? null : font,
    ),
  );
}
