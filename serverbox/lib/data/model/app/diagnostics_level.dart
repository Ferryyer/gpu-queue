/// Legacy names retained for stored settings and backup compatibility.
/// Diagnostics transmission has been removed; every value is local-only.
enum DiagnosticsLevel {
  none,
  basic;

  bool get uploads => false;
  bool get sendsBreadcrumbs => false;

  static DiagnosticsLevel fromName(String? name) {
    if (name == 'full') return DiagnosticsLevel.basic;
    for (final level in DiagnosticsLevel.values) {
      if (level.name == name) return level;
    }
    return DiagnosticsLevel.none;
  }
}

const defaultDiagnosticsLevel = DiagnosticsLevel.none;
