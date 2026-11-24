import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:server_box/core/calendar/notes.dart';

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
      if (entry is File &&
          RegExp(r'^\d{4}-\d{2}-\d{2}\.(jpg|json)$').hasMatch(name) &&
          name.substring(0, 10).compareTo(today) <= 0) {
        names.add(name);
      }
    }
    names.sort((a, b) => b.compareTo(a));
    for (final name in names) {
      try {
        return await _read(name);
      } on FileSystemException {
        continue;
      } on FormatException {
        continue;
      }
    }
    return null;
  }

  Future<CalendarReading> _read(String name) async {
    final date = name.substring(0, 10);
    String? source;
    String? digest;
    var imageName = name;
    if (name.endsWith('.json')) {
      final manifest = File('${directory.path}/$name');
      if (await manifest.length() > 4096)
        throw const FormatException('Invalid calendar manifest');
      final data = jsonDecode(await manifest.readAsString());
      if (data is! Map ||
          data['date'] != date ||
          data['sha256'] is! String ||
          !RegExp(r'^[a-f0-9]{64}$').hasMatch(data['sha256'] as String) ||
          data['source'] is! String) {
        throw const FormatException('Invalid calendar manifest');
      }
      digest = data['sha256'] as String;
      source = data['source'] as String;
      final uri = Uri.tryParse(source);
      if (uri == null ||
          uri.scheme != 'https' ||
          uri.host != 'img.owspace.com' ||
          uri.userInfo.isNotEmpty ||
          uri.hasQuery ||
          uri.hasFragment ||
          !RegExp(r'^/Public/uploads/Download/\d{4}/\d{4}\.jpg$')
              .hasMatch(uri.path)) {
        throw const FormatException('Invalid calendar source');
      }
      imageName = '$date.$digest.jpg';
    }
    final image = File('${directory.path}/$imageName');
    final stat = await image.stat();
    if (stat.type != FileSystemEntityType.file ||
        stat.size < 4 ||
        stat.size > 10 * 1024 * 1024) {
      throw const FileSystemException('单向历图片大小无效');
    }
    final bytes = await image.readAsBytes();
    if (digest != null && sha256.convert(bytes).toString() != digest) {
      throw const FormatException('Calendar checksum mismatch');
    }
    if (bytes.length < 4 ||
        bytes[0] != 0xff ||
        bytes[1] != 0xd8 ||
        bytes[bytes.length - 2] != 0xff ||
        bytes.last != 0xd9) {
      throw const FileSystemException('单向历图片不是完整的 JPEG');
    }
    String? notes = source == null
        ? null
        : '# 单向历 · $date\n\n图片来源：[单向空间原图]($source)。\n\n图面日期已在本机核对；作者与作品出处见原图署名。\n';
    final noteFile = File('${directory.path}/$date.md');
    try {
      final noteStat = await noteFile.stat();
      if (source == null &&
          noteStat.type == FileSystemEntityType.file &&
          noteStat.size <= 128 * 1024) {
        notes = await noteFile.readAsString();
      }
    } on FileSystemException {
      // Optional provenance cannot hide a valid calendar image.
    } on FormatException {
      // Ignore malformed text rather than breaking the image.
    }
    var hasResearchNotes = false;
    final researchFile = File('${directory.path}/$date.notes.md');
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
      hasResearchNotes: hasResearchNotes,
    );
  }
}

class CalendarReading {
  const CalendarReading({
    required this.bytes,
    required this.date,
    this.notes,
    this.hasResearchNotes = false,
  });
  final Uint8List bytes;
  final String date;
  final String? notes;
  final bool hasResearchNotes;

  static String day(DateTime time) {
    final date = time.toUtc().add(const Duration(hours: 8));
    return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  }

  bool updatedToday(DateTime now) => date == day(now);
}
