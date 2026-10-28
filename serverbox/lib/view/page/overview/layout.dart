import 'package:material_ui/material_ui.dart';

/// Three persistent sections, arranged by the space available to the page.
class OverviewLayout extends StatefulWidget {
  const OverviewLayout({super.key, required this.gpu, required this.feishu, required this.calendar});
  final Widget gpu, feishu, calendar;

  @override
  State<OverviewLayout> createState() => _OverviewLayoutState();
}

class _OverviewLayoutState extends State<OverviewLayout> {
  // Reparent the same native WebKit document across breakpoints. Recreating it
  // during resize loses navigation and can strand an in-flight platform view.
  final _gpuKey = GlobalKey(), _feishuKey = GlobalKey(), _calendarKey = GlobalKey();

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
    const gap = SizedBox(width: 16, height: 16);
    Widget panel(Widget child) => Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(16),
      ),
      clipBehavior: Clip.antiAlias,
      child: child,
    );
    final gpuPanel = panel(KeyedSubtree(key: _gpuKey, child: widget.gpu));
    final feishuPanel = panel(KeyedSubtree(key: _feishuKey, child: widget.feishu));
    final calendarPanel = panel(KeyedSubtree(key: _calendarKey, child: widget.calendar));
    return SingleChildScrollView(
      key: const PageStorageKey('overview-scroll'),
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
      child: box.maxWidth >= 1340
        ? SizedBox(height: (box.maxHeight - 32).clamp(660.0, 1000.0), child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [SizedBox(width: 300, child: gpuPanel), gap,
              Expanded(child: feishuPanel), gap, SizedBox(width: 280, child: calendarPanel)],
          ))
        : box.maxWidth >= 680
          ? Column(children: [
              SizedBox(height: 430, child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Expanded(child: gpuPanel), gap, SizedBox(width: 260, child: calendarPanel),
              ])),
              gap, SizedBox(height: 580, child: feishuPanel),
            ])
          : Column(children: [
              SizedBox(height: 360, child: gpuPanel), gap,
              SizedBox(height: 560, child: feishuPanel), gap,
              SizedBox(height: 580, child: calendarPanel),
            ]),
    );
  });
}
