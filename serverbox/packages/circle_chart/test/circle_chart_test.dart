import 'package:circle_chart/circle_chart.dart';
import 'package:circle_chart/circle_painter.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

/// The fraction of the ring actually painted, read off the painter.
double painted(WidgetTester tester) {
  final paint = tester.widget<CustomPaint>(
    find.descendant(
      of: find.byType(CircleChart),
      matching: find.byType(CustomPaint),
    ),
  );
  final p = paint.painter! as CirclePainter;
  final expect = p.progressNumber / p.maxNumber;
  final last = p.lastProgressNumber / p.maxNumber;
  return p.fraction * (expect - last) + last;
}

Widget harness(double value) => MaterialApp(
      home: Scaffold(
        body: Center(
          child: CircleChart(progressNumber: value, maxNumber: 100),
        ),
      ),
    );

void main() {
  testWidgets('the first frame shows the value, not zero', (tester) async {
    // A rebuild for a reason that has nothing to do with the value — a resized
    // window, a swapped layout — used to sweep from zero, which reads as the
    // value having dropped and recovered.
    await tester.pumpWidget(harness(50));
    expect(painted(tester), closeTo(0.5, 0.001));
  });

  testWidgets('a changed value animates from the old one', (tester) async {
    await tester.pumpWidget(harness(50));
    await tester.pumpWidget(harness(80));
    await tester.pump(const Duration(milliseconds: 1));

    // Just started: still near where it was, not at the new value and not at
    // zero.
    expect(painted(tester), closeTo(0.5, 0.05));

    await tester.pumpAndSettle();
    expect(painted(tester), closeTo(0.8, 0.001));
  });
}
