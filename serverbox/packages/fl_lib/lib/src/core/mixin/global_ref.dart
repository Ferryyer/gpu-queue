import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Global [WidgetRef] auto set and dispose
mixin GlobalRef<T extends ConsumerStatefulWidget> on ConsumerState<T> {
  /// Returns the [ref] of the global context.
  ///
  /// - Maybe `null` if the global context is not set.
  /// - Using global ref is not recommended as it can lead to unexpected behavior
  /// and makes the code harder to test and maintain.
  static WidgetRef? gRef;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    gRef = ref;
  }

  @override
  void dispose() {
    gRef = null;
    super.dispose();
  }
}
