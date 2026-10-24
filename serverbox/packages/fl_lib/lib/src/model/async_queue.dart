import 'dart:async';
import 'dart:collection';

/// A queue for processing asynchronous tasks sequentially.
///
/// This class allows you to add tasks (synchronous or asynchronous) to a queue
/// and ensures they are executed one after another in the order they were added.
/// Optionally, it can collect and expose the return values of the tasks.
class AsyncQueue<T> {
  /// Whether to collect and expose the return values of processed tasks.
  ///
  /// If true, a [StreamController] is created to emit task results.
  final bool collectRet;

  /// Creates an [AsyncQueue].
  ///
  /// If [collectRet] is true, task return values will be available through
  /// the [returns] stream.
  AsyncQueue({
    this.collectRet = false,
  }) : returns = collectRet ? StreamController<T>() : null;

  /// Internal queue to store tasks waiting to be processed.
  final _queue = Queue<FutureOr<T>>();

  /// StreamController that emits task results if [collectRet] is true,
  /// otherwise null.
  final StreamController<T>? returns;

  /// Since Dart is single-threaded, Mutex is not needed.
  /// Indicates whether the queue is currently being processed.
  bool _isProcessing = false;

  /// Adds a task to the queue and starts processing if not already in progress.
  ///
  /// The task can be either synchronous (T) or asynchronous (Future&lt;T&gt;).
  /// Processing starts automatically after adding a task.
  void addTask(FutureOr<T> task) {
    _queue.add(task);
    _processQueue();
  }

  /// Processes tasks in the queue sequentially.
  ///
  /// This method ensures that tasks are executed one after another.
  /// If [collectRet] is true, task results are emitted to the [returns] stream.
  /// The method automatically stops when the queue is empty and
  /// sets [_isProcessing] to false to allow a new processing cycle.
  Future<void> _processQueue() async {
    if (_isProcessing) return;
    _isProcessing = true;

    while (_queue.isNotEmpty) {
      returns?.add(await _queue.removeFirst());
    }

    _isProcessing = false;
  }
}
