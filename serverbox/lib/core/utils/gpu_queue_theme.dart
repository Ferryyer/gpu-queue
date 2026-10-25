import 'package:flutter/material.dart';

/// Local paper and terracotta styling, with no downloaded font dependency.
ThemeData gpuQueueTheme(ThemeData base) {
  const enabled = bool.fromEnvironment('GPU_QUEUE_STYLE', defaultValue: true);
  if (!enabled) return base;
  final dark = base.brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: const Color(0xFF9B6047),
    brightness: base.brightness,
  ).copyWith(
    surface: Color(dark ? 0xFF272521 : 0xFFF5F3ED),
    onSurface: Color(dark ? 0xFFEAE5DC : 0xFF302E2B),
    onSurfaceVariant: Color(dark ? 0xFFBEB7AA : 0xFF69655E),
    primary: Color(dark ? 0xFFE0A387 : 0xFF8B543E),
    onPrimary: Color(dark ? 0xFF302018 : 0xFFFFFFFF),
  );
  final text = base.textTheme.apply(
    bodyColor: scheme.onSurface,
    displayColor: scheme.onSurface,
  );
  TextStyle? heading(TextStyle? style) => style?.copyWith(
    fontFamily: 'Georgia',
    fontWeight: FontWeight.w500,
  );
  return base.copyWith(
    colorScheme: scheme,
    scaffoldBackgroundColor: scheme.surface,
    cardColor: Color(dark ? 0xFF302D28 : 0xFFFDFCF9),
    textTheme: text.copyWith(
      headlineLarge: heading(text.headlineLarge),
      headlineMedium: heading(text.headlineMedium),
      headlineSmall: heading(text.headlineSmall),
      titleLarge: heading(text.titleLarge),
    ),
    appBarTheme: base.appBarTheme.copyWith(
      backgroundColor: scheme.surface,
      foregroundColor: scheme.onSurface,
    ),
  );
}
