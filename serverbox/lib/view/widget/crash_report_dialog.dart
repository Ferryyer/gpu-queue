import 'package:fl_lib/fl_lib.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/extension/context/locale.dart';
import 'package:server_box/core/service/crash_report.dart';

/// Shows a local crash record. No upload or issue-submission action is exposed.
abstract final class CrashReportDialog {
  /// Opens the report, and answers whether it is still on the device after.
  ///
  /// False only when the user dropped it, which is what the caller needs to
  /// know: the row that opened this stops existing at that point.
  static Future<bool> show(BuildContext context, String report) async {
    final action = await context.showRoundDialog<_ReportAction>(
      title: l10n.crashReportTitle,
      child: _ReportBody(report: report),
      actionsBuilder: (ctx) => [
        Btn.text(
          text: libL10n.delete,
          onTap: () => ctx.popDialog(_ReportAction.drop),
        ),
        Btn.text(
          text: libL10n.copy,
          onTap: () => ctx.popDialog(_ReportAction.copy),
        ),
      ],
    );

    // The work happens here rather than in the buttons: a callback on a dialog
    // button has to pop the right navigator itself, and doing the work there
    // too is how that gets forgotten.
    switch (action) {
      case null:
        return true;
      case _ReportAction.drop:
        await CrashReport.dropSaved();
        return false;
      case _ReportAction.copy:
        Pfs.copy(report);
        return true;
    }
  }
}

enum _ReportAction { drop, copy }

/// The report, above the sentence asking the user to read it.
class _ReportBody extends StatelessWidget {
  const _ReportBody({required this.report});

  final String report;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '崩溃记录只保存在本机，不会发送。你可以查看、复制或删除。',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        UIs.height13,
        // Bounded, because the log is up to 24k of text and an unbounded
        // column in a dialog lays all of it out.
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 320),
          child: SingleChildScrollView(
            child: SelectableText(
              report,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
            ),
          ),
        ),
      ],
    );
  }
}
