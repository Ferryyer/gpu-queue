[![pub package](https://img.shields.io/pub/v/circle_chart.svg)](https://pub.dartlang.org/packages/circle_chart)

# circle_chart

This is a library for creating an animated circle chart widget and add given other widget under the chart.

## Getting Started

Import the package:

```dart
import 'package:circle_chart/circle_chart.dart';
```
Create a CircleChart widget and use in your build method:

```dart
Widget chart = CircleChart(
  progressNumber: 4,
  maxNumber: 10,
  children: <Widget>[
    const Icon(Icons.arrow_upward),
    const Text('This is kind of circle chart.'),
    Text(
      'This is kind of description',
      style: Theme.of(context).textTheme.headlineSmall,
    ),
  ],
);
```
```dart
Widget build(BuildContext context) {
  return Scaffold(
    appBar: AppBar(
      title: Text(widget.title),
    ),
    body: Center(child: chart),
  );
}
```
