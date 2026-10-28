import 'package:flutter/gestures.dart';
import 'package:flutter/semantics.dart';
import 'package:material_ui/material_ui.dart';

/// Swiping only reveals the action. Even a full swipe never deletes a row.
class QueueSwipeDelete extends StatefulWidget {
  const QueueSwipeDelete({super.key, required this.child, required this.onDelete, this.disabledReason});
  final Widget child;
  final VoidCallback? onDelete;
  final String? disabledReason;

  @override
  State<QueueSwipeDelete> createState() => _QueueSwipeDeleteState();
}

class _QueueSwipeDeleteState extends State<QueueSwipeDelete> {
  static const _extent = 88.0;
  double _reveal = 0;
  bool _dragging = false;
  void _move(double delta) => setState(() => _reveal = (_reveal + delta).clamp(0.0, _extent));
  void _toggle() => setState(() => _reveal = _reveal > 0 ? 0 : _extent);

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final open = _reveal >= _extent - 1;
    return Semantics(
      customSemanticsActions: {CustomSemanticsAction(label: open ? '收起删除' : '显示删除'): _toggle},
      child: Listener(
        onPointerSignal: (event) {
          if (event is PointerScrollEvent && event.scrollDelta.dx.abs() > event.scrollDelta.dy.abs()) {
            GestureBinding.instance.pointerSignalResolver.register(event, (_) => _move(event.scrollDelta.dx > 0 ? _extent : -_extent));
          }
        },
        child: GestureDetector(
          onSecondaryTap: _toggle,
          onHorizontalDragStart: (_) => setState(() => _dragging = true),
          onHorizontalDragUpdate: (details) => _move(-details.delta.dx),
          onHorizontalDragEnd: (details) => setState(() {
            _dragging = false;
            _reveal = details.primaryVelocity! < -200 ||
                (details.primaryVelocity! <= 200 && _reveal > _extent / 2) ? _extent : 0;
          }),
          onHorizontalDragCancel: () => setState(() { _dragging = false; _reveal = 0; }),
          onTap: _reveal > 0 ? () => setState(() => _reveal = 0) : null,
          child: ClipRect(child: Stack(children: [
            Positioned.fill(child: Align(
              alignment: Alignment.centerRight,
              child: SizedBox(width: _extent, height: double.infinity,
                child: ExcludeSemantics(excluding: !open,
                  child: IgnorePointer(ignoring: !open,
                    child: Tooltip(message: widget.disabledReason ?? '删除任务记录，保留文件与产物',
                      child: TextButton(
                        onPressed: widget.onDelete,
                        style: TextButton.styleFrom(
                          backgroundColor: Color(dark ? 0xFF472C2C : 0xFFFBE9E7),
                          foregroundColor: Color(dark ? 0xFFFFB4AB : 0xFFA73830),
                          shape: const RoundedRectangleBorder(),
                          padding: EdgeInsets.zero,
                        ),
                        child: const Column(mainAxisSize: MainAxisSize.min, children: [
                          Icon(Icons.delete_outline, size: 18),
                          SizedBox(height: 4),
                          Text('删除'),
                        ]),
                      ),
                    ),
                  ),
                ),
              ),
            )),
            TweenAnimationBuilder<double>(
              tween: Tween(end: _reveal),
              duration: _dragging ? Duration.zero : const Duration(milliseconds: 160),
              builder: (_, value, child) => Transform.translate(offset: Offset(-value, 0), child: child),
              child: AbsorbPointer(absorbing: _reveal > 0, child: widget.child),
            ),
          ])),
        ),
      ),
    );
  }
}
