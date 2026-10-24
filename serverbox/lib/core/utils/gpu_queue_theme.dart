import 'package:material_ui/material_ui.dart';

/// Local paper and terracotta styling, with no downloaded font dependency.
ThemeData gpuQueueTheme(ThemeData base) {
  const enabled = bool.fromEnvironment('GPU_QUEUE_STYLE', defaultValue: true);
  if (!enabled) return base;
  final dark = base.brightness == Brightness.dark;
  final scheme =
      ColorScheme.fromSeed(
        seedColor: const Color(0xFF9B6047),
        brightness: base.brightness,
      ).copyWith(
        surface: Color(dark ? 0xFF272521 : 0xFFF5F3ED),
        onSurface: Color(dark ? 0xFFEAE5DC : 0xFF302E2B),
        onSurfaceVariant: Color(dark ? 0xFFBEB7AA : 0xFF69655E),
        primary: Color(dark ? 0xFFE0A387 : 0xFF8B543E),
        onPrimary: Color(dark ? 0xFF302018 : 0xFFFFFFFF),
        primaryContainer: Color(dark ? 0xFF49392F : 0xFFF0E7DB),
        onPrimaryContainer: Color(dark ? 0xFFF1D7C8 : 0xFF714832),
        secondary: Color(dark ? 0xFF9DC8AD : 0xFF38664D),
        onSecondary: Color(dark ? 0xFF153524 : 0xFFFFFFFF),
        secondaryContainer: Color(dark ? 0xFF293D32 : 0xFFE7EEE3),
        onSecondaryContainer: Color(dark ? 0xFFBBDDC6 : 0xFF315D45),
        surfaceContainerLowest: Color(dark ? 0xFF211F1C : 0xFFFDFCF9),
        surfaceContainerLow: Color(dark ? 0xFF302D28 : 0xFFFDFCF9),
        surfaceContainer: Color(dark ? 0xFF35312B : 0xFFEEECE4),
        surfaceContainerHigh: Color(dark ? 0xFF3B372F : 0xFFE8E4DA),
        surfaceContainerHighest: Color(dark ? 0xFF444036 : 0xFFDFDAD0),
        outline: Color(dark ? 0xFF8F877B : 0xFF8C8579),
        outlineVariant: Color(dark ? 0xFF4A453D : 0xFFE2DED5),
      );
  final text = base.textTheme.apply(
    bodyColor: scheme.onSurface,
    displayColor: scheme.onSurface,
  );
  TextStyle? heading(TextStyle? style) => style?.copyWith(
    fontFamily: base.platform == TargetPlatform.linux
        ? 'DejaVu Serif'
        : 'Georgia',
    fontFamilyFallback: base.platform == TargetPlatform.linux
        ? const ['WenQuanYi Micro Hei', 'Noto Serif CJK SC']
        : const [
            'Songti SC',
            'Noto Serif CJK SC',
            'DejaVu Serif',
            'WenQuanYi Micro Hei',
          ],
    fontWeight: FontWeight.w500,
  );
  return base.copyWith(
    colorScheme: scheme,
    canvasColor: scheme.surface,
    scaffoldBackgroundColor: scheme.surface,
    cardColor: Color(dark ? 0xFF302D28 : 0xFFFDFCF9),
    dividerColor: scheme.outlineVariant,
    textTheme: text.copyWith(
      headlineLarge: heading(text.headlineLarge),
      headlineMedium: heading(text.headlineMedium),
      headlineSmall: heading(text.headlineSmall),
      titleLarge: heading(text.titleLarge),
      titleMedium: text.titleMedium?.copyWith(
        fontSize: 15,
        fontWeight: FontWeight.w600,
        height: 1.5,
      ),
      bodyLarge: text.bodyLarge?.copyWith(fontSize: 15, height: 1.7),
      bodyMedium: text.bodyMedium?.copyWith(fontSize: 14, height: 1.6),
      bodySmall: text.bodySmall?.copyWith(
        fontSize: 12,
        height: 1.6,
        color: scheme.onSurfaceVariant,
      ),
    ),
    appBarTheme: base.appBarTheme.copyWith(
      backgroundColor: scheme.surface,
      foregroundColor: scheme.onSurface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: text.titleMedium?.copyWith(
        fontSize: 18,
        fontWeight: FontWeight.w600,
        color: scheme.onSurface,
      ),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: scheme.surfaceContainerLow,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: scheme.outlineVariant),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(44, 44),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(44, 44),
        foregroundColor: scheme.onSurface,
        backgroundColor: scheme.surfaceContainerLow,
        side: BorderSide(color: scheme.outlineVariant),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    ),
    inputDecorationTheme: base.inputDecorationTheme.copyWith(
      filled: true,
      fillColor: scheme.surfaceContainerLow,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: scheme.outlineVariant),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: scheme.outlineVariant),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: scheme.primary, width: 2),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: scheme.surfaceContainerLow,
      selectedColor: scheme.secondaryContainer,
      side: BorderSide(color: scheme.outlineVariant),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
    ),
    listTileTheme: base.listTileTheme.copyWith(
      selectedColor: scheme.primary,
      selectedTileColor: scheme.primaryContainer,
    ),
    navigationRailTheme: base.navigationRailTheme.copyWith(
      backgroundColor: scheme.surface,
      indicatorColor: scheme.primaryContainer,
    ),
    navigationBarTheme: base.navigationBarTheme.copyWith(
      backgroundColor: scheme.surface,
      indicatorColor: scheme.primaryContainer,
      surfaceTintColor: Colors.transparent,
    ),
    dialogTheme: base.dialogTheme.copyWith(
      backgroundColor: scheme.surfaceContainerLow,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
  );
}
