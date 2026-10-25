import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/widgets.dart';

extension ColorContext on BuildContext {
  _ContextColor get colors => _ContextColor(this);
}

final class _ContextColor {
  final BuildContext context;

  const _ContextColor(this.context);

  Color get bg => UIs.bgColor.resolve(context);

  Color get text => UIs.textColor.resolve(context);
}
