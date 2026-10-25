import 'package:material_ui/material_ui.dart';

/// Approved MF-9 native tokens. System body fonts; only display text is serif.
ThemeData gpuQueueTheme(ThemeData base) {
  const enabled = bool.fromEnvironment('GPU_QUEUE_STYLE', defaultValue: true);
  if (!enabled) return base;
  final dark = base.brightness == Brightness.dark;
  final background = Color(dark ? 0xFF222321 : 0xFFFAF9F6);
  final panel = Color(dark ? 0xFF292A27 : 0xFFFFFFFF);
  final sidebar = Color(dark ? 0xFF1D1E1C : 0xFFF0EEE8);
  final text = Color(dark ? 0xFFECECE7 : 0xFF292722);
  final secondary = Color(dark ? 0xFFABADA5 : 0xFF716D65);
  final divider = Color(dark ? 0xFF41433C : 0xFFE5E1D8);
  final accent = Color(dark ? 0xFFDE947A : 0xFFAE583F);
  final scheme =
      ColorScheme.fromSeed(
        seedColor: accent,
        brightness: base.brightness,
      ).copyWith(
        surface: background,
        surfaceContainerLowest: sidebar,
        surfaceContainerLow: panel,
        surfaceContainer: sidebar,
        surfaceContainerHigh: sidebar,
        surfaceContainerHighest: sidebar,
        onSurface: text,
        onSurfaceVariant: secondary,
        outline: secondary,
        outlineVariant: divider,
        primary: accent,
        onPrimary: Color(dark ? 0xFF222321 : 0xFFFFFFFF),
        primaryContainer: Color(dark ? 0xFF42332E : 0xFFF4E8E2),
        onPrimaryContainer: text,
        secondary: Color(dark ? 0xFF9FC4AB : 0xFF3D7156),
        error: Color(dark ? 0xFFFFA095 : 0xFFB83B32),
      );
  final body = base.textTheme.apply(
    fontFamily: '.AppleSystemUIFont',
    fontFamilyFallback: const ['PingFang SC', 'Noto Sans CJK SC'],
    bodyColor: text,
    displayColor: text,
  );
  TextStyle display(double size) => TextStyle(
    fontFamily: 'Georgia',
    fontFamilyFallback: const ['Songti SC', 'Noto Serif CJK SC'],
    fontSize: size,
    fontWeight: FontWeight.w400,
    color: text,
    height: 1.35,
  );
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(7));
  final button = ButtonStyle(
    minimumSize: const WidgetStatePropertyAll(Size(0, 34)),
    padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 14)),
    shape: WidgetStatePropertyAll(shape),
    textStyle: const WidgetStatePropertyAll(
      TextStyle(fontSize: 13, fontWeight: FontWeight.w400),
    ),
    visualDensity: VisualDensity.standard,
  );
  return base.copyWith(
    colorScheme: scheme,
    scaffoldBackgroundColor: background,
    cardColor: panel,
    dividerColor: divider,
    textTheme: body.copyWith(
      headlineLarge: display(28),
      headlineMedium: display(26),
      headlineSmall: display(26),
      titleLarge: body.titleLarge?.copyWith(
        fontSize: 18,
        fontWeight: FontWeight.w500,
      ),
      titleMedium: body.titleMedium?.copyWith(
        fontSize: 16,
        fontWeight: FontWeight.w500,
      ),
      bodyLarge: body.bodyLarge?.copyWith(fontSize: 14, height: 1.5),
      bodyMedium: body.bodyMedium?.copyWith(fontSize: 14, height: 1.5),
      bodySmall: body.bodySmall?.copyWith(
        fontSize: 12,
        height: 1.5,
        color: secondary,
      ),
      labelLarge: body.labelLarge?.copyWith(
        fontSize: 13,
        fontWeight: FontWeight.w400,
      ),
    ),
    appBarTheme: base.appBarTheme.copyWith(
      backgroundColor: background,
      foregroundColor: text,
      elevation: 0,
      scrolledUnderElevation: 0,
      toolbarHeight: 64,
      titleTextStyle: display(26),
    ),
    dividerTheme: DividerThemeData(color: divider, thickness: 1, space: 1),
    filledButtonTheme: FilledButtonThemeData(style: button),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: button.copyWith(
        side: WidgetStatePropertyAll(BorderSide(color: divider)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(style: button),
    iconButtonTheme: const IconButtonThemeData(
      style: ButtonStyle(iconSize: WidgetStatePropertyAll(18)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      isDense: true,
      filled: true,
      fillColor: panel,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: BorderSide(color: divider),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: BorderSide(color: divider),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: BorderSide(color: accent, width: 2),
      ),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: secondary,
      selectedColor: text,
      selectedTileColor: scheme.primaryContainer,
    ),
  );
}
