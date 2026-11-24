import 'dart:io';
import 'dart:typed_data';

import 'package:server_box/core/calendar/notes.dart';

/// App-owned, dated files written atomically by the bundled calendar script.
class LocalCalendar {
  LocalCalendar(this.directory);
  final Directory directory;

  Future<CalendarReading?> readLatest(DateTime now) async {
    if (!await directory.exists()) return null;
    final today = CalendarReading.day(now);
    final dates = <String>{};
    await for (final entry in directory.list(followLinks: false)) {
      final name = entry.uri.pathSegments.last;
      if (entry is File &&
          RegExp(r'^\d{4}-\d{2}-\d{2}\.(jpg|current)$').hasMatch(name) &&
          name.substring(0, 10).compareTo(today) <= 0) {
        dates.add(name.substring(0, 10));
      }
    }
    final sorted = dates.toList()..sort((a, b) => b.compareTo(a));
    for (final date in sorted) {
      try {
        final pointer = File('${directory.path}/$date.current');
        if (await pointer.length() <= 128) {
          final revision = (await pointer.readAsString()).trim();
          if (RegExp('^snapshot-$date\\.[a-zA-Z0-9]+\$').hasMatch(revision)) {
            return await _read(
              date,
              Directory('${directory.path}/$revision'),
              revision,
            );
          }
        }
      } on FileSystemException {
        /* Fall back to a pre-upgrade cache. */
      } on FormatException {
        /* Ignore a malformed pointer. */
      }
      try {
        return await _read(date, directory, null);
      } on FileSystemException {
        continue;
      }
    }
    return null;
  }

  Future<CalendarReading> _read(
    String date,
    Directory folder,
    String? revision,
  ) async {
    final image = File(
      '${folder.path}/${revision == null ? '$date.jpg' : 'image.jpg'}',
    );
    final stat = await image.stat();
    if (stat.type != FileSystemEntityType.file ||
        stat.size < 4 ||
        stat.size > 10 * 1024 * 1024) {
      throw const FileSystemException('单向历图片大小无效');
    }
    final bytes = await image.readAsBytes();
    if (bytes.length < 4 ||
        bytes[0] != 0xff ||
        bytes[1] != 0xd8 ||
        bytes[bytes.length - 2] != 0xff ||
        bytes.last != 0xd9) {
      throw const FileSystemException('单向历图片不是完整的 JPEG');
    }
    String? notes;
    final noteFile = File(
      '${folder.path}/${revision == null ? '$date.md' : 'source.md'}',
    );
    try {
      final noteStat = await noteFile.stat();
      if (noteStat.type == FileSystemEntityType.file &&
          noteStat.size <= 128 * 1024) {
        notes = await noteFile.readAsString();
      }
    } on FileSystemException {
      // Optional provenance cannot hide a valid calendar image.
    } on FormatException {
      // Ignore malformed text rather than breaking the image.
    }
    final imageSource = notes;
    var hasResearchNotes = false;
    final researchFile = notesFile(date, revision);
    try {
      if (await researchFile.length() <= CalendarNotes.maxBytes) {
        final research = CalendarNotes.parse(
          await researchFile.readAsBytes(),
          date,
        );
        if (research != null) {
          notes = research;
          hasResearchNotes = true;
        }
      }
    } on FileSystemException {
      /* A missing note does not hide the image. */
    }
    return CalendarReading(
      bytes: bytes,
      date: date,
      notes: notes,
      imageSource: imageSource,
      hasResearchNotes: hasResearchNotes,
      revision: revision,
    );
  }

  File notesFile(String date, String? revision) => File(
    revision == null
        ? '${directory.path}/$date.notes.md'
        : '${directory.path}/$revision/notes.md',
  );
}

class CalendarReading {
  const CalendarReading({
    required this.bytes,
    required this.date,
    this.notes,
    this.imageSource,
    this.hasResearchNotes = false,
    this.revision,
  });
  final Uint8List bytes;
  final String date;
  final String? notes;
  final String? imageSource;
  final bool hasResearchNotes;
  final String? revision;

  static String day(DateTime time) {
    final date = time.toUtc().add(const Duration(hours: 8));
    return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  }

  bool updatedToday(DateTime now) => date == day(now);
}
