import 'dart:async';

Future<int> bench(FutureOr<void> Function() fn, {int times = 10000}) async {
  final sw = Stopwatch()..start();
  for (var i = 0; i < times; i++) {
    await fn();
  }
  sw.stop();
  return sw.elapsedMilliseconds;
}
