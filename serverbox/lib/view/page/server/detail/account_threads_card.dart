import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/extension/context/locale.dart';
import 'package:server_box/data/res/chart_palette.dart';
import 'package:server_box/view/page/server/detail/focus_parts.dart';
import 'package:server_box/view/page/server/detail/readout.dart';
import 'package:server_box/view/page/server/metric_row.dart';
import 'package:server_box/view/page/server/reading_text.dart';

/// The account sampler's display text, promoted beside the ordinary metrics.
/// The command supplies its own headline and note; no quota is inferred here.
class AccountThreadsCard extends StatelessWidget {
  static const commandName = '账号线程占用';

  const AccountThreadsCard({
    super.key,
    required this.output,
    required this.wide,
    required this.onTap,
    this.staleAt,
  });

  final String output;
  final bool wide;
  final VoidCallback onTap;
  final DateTime? staleAt;

  @override
  Widget build(BuildContext context) {
    final lines = readoutCommandLines(output);
    final headline = lines.first.trim();
    // Old sampler output and shell errors can be long. Keep them in the note
    // and detail instead of pushing the fixed-width metric row off screen.
    final short = headline.isNotEmpty && headline.runes.length <= 16;
    final value = short ? headline : l10n.unavailable;
    final at = staleAt;
    final note = at != null
        ? l10n.atTimeFmt(ReadingFmt.clock(at.millisecondsSinceEpoch))
        : short
        ? (lines.length > 1 ? lines[1] : '')
        : headline;

    if (wide) {
      return MetricRow(
        icon: Icons.account_tree_outlined,
        label: commandName,
        color: ChartPalette.accent,
        value: value,
        note: note,
        onTap: onTap,
      );
    }
    return ServerDetailMetricTile(
      icon: Icons.account_tree_outlined,
      label: commandName,
      value: value,
      note: note,
      selected: false,
      stale: staleAt != null,
      onTap: onTap,
    );
  }
}
