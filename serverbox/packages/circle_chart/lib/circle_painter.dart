import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

class CirclePainter extends CustomPainter {
  final Color? progressColor;
  final Color? backgroundColor;
  final double progressNumber;
  final double lastProgressNumber;
  final int maxNumber;
  final double fraction;
  final Paint _backgroundPaint;
  final Paint _progressPaint;

  CirclePainter({
    required this.progressNumber,
    required this.lastProgressNumber,
    required this.maxNumber,
    required this.fraction,
    this.backgroundColor,
    this.progressColor,
  })  : _backgroundPaint = Paint()
          ..color = backgroundColor ?? Colors.black12
          ..strokeWidth = 10.0
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round,
        _progressPaint = Paint()
          ..color = progressColor ?? Colors.blue
          ..strokeWidth = 10.0
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawArc(
        Offset.zero & size, -math.pi, 2 * math.pi, false, _backgroundPaint);

    final double lastPercent = lastProgressNumber / maxNumber;
    final double expectPercent = progressNumber / maxNumber;
    final double realtimePercent =
        fraction * (expectPercent - lastPercent) + lastPercent;
    final double progressRadians = realtimePercent * (2 * math.pi);

    final double startAngle = -math.pi * 1.5;

    canvas.drawArc(
        Offset.zero & size, startAngle, progressRadians, false, _progressPaint);
  }

  @override
  bool shouldRepaint(covariant CirclePainter oldDelegate) {
    return oldDelegate.fraction != fraction ||
        oldDelegate.progressNumber != progressNumber ||
        oldDelegate.lastProgressNumber != lastProgressNumber ||
        oldDelegate.maxNumber != maxNumber ||
        oldDelegate.backgroundColor != backgroundColor ||
        oldDelegate.progressColor != progressColor;
  }
}
