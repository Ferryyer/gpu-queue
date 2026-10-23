import 'dart:async';

import 'package:fl_lib/fl_lib.dart';

/// {@template result_design}
/// In common cases, use `try-catch` to handle errors.
/// But we can use [FnRes] to handle errs in golang-like way.
/// {@endtemplate}
typedef FnRes<T> = (T? v, Object? e);

/// {@macro result_design}
extension Resx<T> on FnRes<T> {
  /// Returns `true` if there is no error.
  bool get ok => $2 == null;

  /// Returns `f(v)` if there is no error.
  A? map<A>(A Function(T v) f) {
    final v = $1;
    if (v != null) return f(v);
    return null;
  }

  /// {@template resx_try_catch}
  /// Wrap [fn] with `try-catch`.
  /// - [msg] is the message of the error.
  /// - [onErr] is the callback when an error occurs.
  /// {@endtemplate}
  static Future<FnRes<T>> tryCatch<T>(
    Future<T> Function() fn, {
    String? msg,
    FutureOr<void> Function(Object e, StackTrace s)? onErr,
  }) async {
    try {
      return (await fn(), null);
    } catch (e, s) {
      Loggers.app.warning(msg, e, s);
      await onErr?.call(e, s);
      return (null, e);
    }
  }

  /// Sync version of [tryCatch].
  ///
  /// {@macro resx_try_catch}
  static FnRes<T> tryCatchSync<T>(
    T Function() fn, {
    String? msg,
    void Function(Object e, StackTrace s)? onErr,
  }) {
    try {
      return (fn(), null);
    } catch (e, s) {
      Loggers.app.warning(msg, e, s);
      onErr?.call(e, s);
      return (null, e);
    }
  }
}
