import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/calendar/local_calendar.dart';

void main() {
  late Directory dir;
  setUp(() async { dir = await Directory.systemTemp.createTemp('inspire-calendar-test-'); });
  tearDown(() async { await dir.delete(recursive: true); });

  test('uses Shanghai date across UTC midnight and marks older images stale', () {
    final reading = CalendarReading(bytes: Uint8List(0), modified: DateTime.utc(2026, 10, 27, 16));
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 15, 59)), isTrue);
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 16)), isFalse);
    expect(CalendarReading.day(reading.modified), '2026-10-28');
  });

  test('does not turn missing or truncated files into a calendar', () async {
    final source = LocalCalendar(dir);
    await expectLater(source.read(), throwsA(isA<FileSystemException>()));
    final image = File('${dir.path}/今日单向历.jpg');
    await image.writeAsBytes([0xff, 0xd8, 0, 0]);
    await expectLater(source.read(), throwsA(isA<FileSystemException>()));
  });

  test('notes are optional, independently dated, and file replacements are reread', () async {
    final source = LocalCalendar(dir);
    final image = File('${dir.path}/今日单向历.jpg');
    // Reader tests the JPEG envelope; the image widget performs actual decoding.
    await image.writeAsBytes([0xff, 0xd8, 1, 0xff, 0xd9]);
    expect((await source.read()).notes, isNull);
    final note = File('${dir.path}/今日单向历出处.md');
    await note.writeAsString('# 出处笔记');
    await note.setLastModified(DateTime.utc(2026, 10, 26));
    final reading = await source.read();
    expect(reading.notes, '# 出处笔记');
    expect(CalendarReading.day(reading.notesModified!), '2026-10-26');
    await image.writeAsBytes([0xff, 0xd8, 2, 0xff, 0xd9]);
    expect((await source.read()).bytes[2], 2);
    await note.writeAsBytes([0xff, 0xff]);
    expect((await source.read()).notes, isNull);
  });
}
