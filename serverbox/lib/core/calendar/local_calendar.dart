import 'dart:io';
import 'dart:typed_data';

/// App-owned, dated files written atomically by the bundled calendar script.
class LocalCalendar {
  LocalCalendar(this.directory);
  final Directory directory;

  Future<CalendarReading?> readLatest(DateTime now) async {
    if (!await directory.exists()) return null;
    final today = CalendarReading.day(now);
    final names = <String>[];
    await for (final entry in directory.list(followLinks: false)) {
      final name = entry.uri.pathSegments.last;
      if (entry is File && RegExp(r'^\d{4}-\d{2}-\d{2}\.jpg$').hasMatch(name) &&
          name.substring(0, 10).compareTo(today) <= 0) {
        names.add(name);
      }
    }
    names.sort((a, b) => b.compareTo(a));
    for (final name in names) {
      try { return await _read(name); } on FileSystemException { continue; }
    }
    return null;
  }

  Future<CalendarReading> _read(String name) async {
    final image = File('${directory.path}/$name');
    final stat = await image.stat();
    if (stat.type != FileSystemEntityType.file || stat.size < 4 || stat.size > 10 * 1024 * 1024) {
      throw const FileSystemException('单向历图片大小无效');
    }
    final bytes = await image.readAsBytes();
    if (bytes.length < 4 || bytes[0] != 0xff || bytes[1] != 0xd8 ||
        bytes[bytes.length - 2] != 0xff || bytes.last != 0xd9) {
      throw const FileSystemException('单向历图片不是完整的 JPEG');
    }
    final date = name.substring(0, 10);
    String? notes;
    final noteFile = File('${directory.path}/$date.md');
    try {
      final noteStat = await noteFile.stat();
      if (noteStat.type == FileSystemEntityType.file && noteStat.size <= 128 * 1024) {
        notes = await noteFile.readAsString();
      }
    } on FileSystemException {
      // Optional provenance cannot hide a valid calendar image.
    } on FormatException {
      // Ignore malformed text rather than breaking the image.
    }
    return CalendarReading(bytes: bytes, date: date, notes: notes);
  }
}

class CalendarReading {
  const CalendarReading({required this.bytes, required this.date, this.notes});
  final Uint8List bytes;
  final String date;
  final String? notes;

  static String day(DateTime time) {
    final date = time.toUtc().add(const Duration(hours: 8));
    return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  }
  bool updatedToday(DateTime now) => date == day(now);
}
