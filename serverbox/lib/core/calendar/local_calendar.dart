import 'dart:io';
import 'dart:typed_data';

/// Reads the two files produced by the existing daily calendar automation.
/// No network requests, script execution, or writes to the user's desktop.
class LocalCalendar {
  LocalCalendar(this.directory);
  final Directory directory;

  static LocalCalendar? desktop() {
    final home = Platform.environment[Platform.isWindows ? 'USERPROFILE' : 'HOME'];
    return home == null ? null : LocalCalendar(Directory('$home/Desktop'));
  }

  Future<CalendarReading> read() async {
    final image = File('${directory.path}/今日单向历.jpg');
    final stat = await image.stat();
    if (stat.type != FileSystemEntityType.file) {
      throw const FileSystemException('桌面还没有今日单向历.jpg');
    }
    if (stat.size < 4 || stat.size > 10 * 1024 * 1024) {
      throw const FileSystemException('单向历图片大小无效');
    }
    final bytes = await image.readAsBytes();
    if (bytes.length < 4 || bytes[0] != 0xff || bytes[1] != 0xd8 ||
        bytes[bytes.length - 2] != 0xff || bytes.last != 0xd9) {
      throw const FileSystemException('单向历图片不是完整的 JPEG');
    }
    String? notes;
    DateTime? notesModified;
    final noteFile = File('${directory.path}/今日单向历出处.md');
    try {
      final noteStat = await noteFile.stat();
      if (noteStat.type == FileSystemEntityType.file && noteStat.size <= 128 * 1024) {
        notes = await noteFile.readAsString();
        notesModified = noteStat.modified;
      }
    } on FileSystemException {
      // Notes can be replaced independently of the image.
    } on FormatException {
      // A malformed note must not hide a valid calendar image.
    }
    return CalendarReading(bytes: bytes, modified: stat.modified,
      notes: notes, notesModified: notesModified);
  }
}

class CalendarReading {
  const CalendarReading({required this.bytes, required this.modified, this.notes, this.notesModified});
  final Uint8List bytes;
  final DateTime modified;
  final String? notes;
  final DateTime? notesModified;

  // The existing automation uses Asia/Shanghai even while the user travels.
  static String day(DateTime time) {
    final date = time.toUtc().add(const Duration(hours: 8));
    return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  }
  bool updatedToday(DateTime now) => day(modified) == day(now);
}
