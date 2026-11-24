import 'dart:convert';
import 'dart:io';

/// Public editorial content. No GitHub token or publishing credentials ship.
abstract final class CalendarNotes {
  static const maxBytes = 64 * 1024;
  static String marker(String day) => '<!-- inspire-calendar-date: $day -->';
  static String imageMarker(String digest) =>
      '<!-- inspire-calendar-image-sha256: $digest -->';
  static Uri url(String day) => Uri.https(
    'raw.githubusercontent.com',
    '/Ferryyer/gpu-queue/main/calendar/notes/$day.md',
  );

  static String? parse(List<int> bytes, String day, {String? imageSha256}) {
    if (bytes.length > maxBytes) return null;
    try {
      final text = utf8.decode(bytes);
      if (!text.startsWith('${marker(day)}\n')) return null;
      var body = text.substring(marker(day).length + 1);
      final binding = RegExp(
        r'^<!-- inspire-calendar-image-sha256: ([a-f0-9]{64}) -->\n',
      ).firstMatch(body);
      // A matching date or source URL cannot identify a same-day revision.
      if (imageSha256 != null && binding?.group(1) != imageSha256) return null;
      if (binding != null) body = body.substring(binding.end);
      body = body.trim();
      if (body.isEmpty || body.contains('<') || body.contains('!['))
        return null;
      return body;
    } on FormatException {
      return null;
    }
  }

  static Future<String?> fetch(String day) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      return await (() async {
        final request = await client.getUrl(url(day));
        request.followRedirects = false;
        final response = await request.close();
        if (response.statusCode != 200 || response.contentLength > maxBytes)
          return null;
        final bytes = <int>[];
        await for (final chunk in response) {
          bytes.addAll(chunk);
          if (bytes.length > maxBytes) return null;
        }
        // Preserve the publisher's image binding for validation by the caller.
        return parse(bytes, day) == null ? null : utf8.decode(bytes);
      })().timeout(const Duration(seconds: 15));
    } on Exception {
      return null;
    } finally {
      client.close(force: true);
    }
  }
}
