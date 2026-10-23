library;

import 'package:circle_chart/circle_painter.dart';
import 'package:material_ui/material_ui.dart';

class CircleChart extends StatefulWidget {
  final double progressNumber;
  final int maxNumber;
  final double width;
  final double height;
  final Duration animationDuration;
  final Color? progressColor;
  final Color? backgroundColor;
  final List<Widget> children;

  const CircleChart({
    super.key,
    required this.progressNumber,
    required this.maxNumber,
    this.animationDuration = const Duration(seconds: 1),
    this.backgroundColor,
    this.progressColor,
    this.width = 128,
    this.height = 128,
    this.children = const <Widget>[],
  })  : assert(maxNumber > 0, 'maxNumber must be greater than 0'),
        assert(progressNumber >= 0 && progressNumber < maxNumber,
            'progressNumber must be greater than or equal to 0 and less than maxNumber');

  @override
  State<StatefulWidget> createState() => CircleChartState();
}

class CircleChartState extends State<CircleChart>
    with SingleTickerProviderStateMixin {
  late Animation<double> _animation;
  late AnimationController _controller;
  double _lastProgressNumber = 0.0;

  @override
  void initState() {
    super.initState();
    _controller =
        AnimationController(duration: widget.animationDuration, vsync: this);
    _animation = Tween(begin: 0.0, end: 1.0)
        .chain(CurveTween(curve: Curves.fastEaseInToSlowEaseOut))
        .animate(_controller);
    // The first frame paints the number it was given, rather than sweeping up
    // to it from zero.
    //
    // A widget is built again for reasons that have nothing to do with its
    // value: a window resized, a column layout that swapped one list for
    // another, a tab returned to. Sweeping from zero each time reads as the
    // value having dropped and recovered — one that was showing 50% blinked to
    // 0% and climbed back. What is worth animating is a change, and
    // [didUpdateWidget] animates those, from the old value to the new one.
    _lastProgressNumber = widget.progressNumber;
    _controller.value = 1.0;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(CircleChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.progressNumber != widget.progressNumber) {
      _lastProgressNumber = oldWidget.progressNumber;
      _controller.reset();
      _controller.forward();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.center,
      width: widget.width,
      height: widget.height,
      child: AspectRatio(
        aspectRatio: 1.0,
        child: Stack(
          alignment: Alignment.center,
          children: <Widget>[
            Positioned.fill(
              child: AnimatedBuilder(
                animation: _controller,
                builder: (_, _) => CustomPaint(
                  painter: CirclePainter(
                    fraction: _animation.value,
                    progressNumber: widget.progressNumber,
                    lastProgressNumber: _lastProgressNumber,
                    maxNumber: widget.maxNumber,
                    backgroundColor: widget.backgroundColor,
                    progressColor: widget.progressColor,
                  ),
                ),
              ),
            ),
            if (widget.children.isNotEmpty)
              Positioned.fill(
                child: Center(
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: widget.children,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
