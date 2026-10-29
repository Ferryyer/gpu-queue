import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';

void main() {
  late Directory dir;
  final now = DateTime.utc(2026, 10, 29, 2);
  Future<void> image(String day) => File('${dir.path}/$day.jpg').writeAsBytes([0xff, 0xd8, 1, 0xff, 0xd9]);
  setUp(() async { dir = await Directory.systemTemp.createTemp('inspire-calendar-test-'); });
  tearDown(() async { await dir.delete(recursive: true); });

  test('Shanghai day uses the printed date rather than file modification time', () {
    final reading = CalendarReading(bytes: Uint8List(0), date: '2026-10-28');
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 15, 59)), isTrue);
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 16)), isFalse);
    expect(CalendarReading.day(DateTime.utc(2026, 12, 31, 16)), '2027-01-01');
  });

  test('missing, truncated and future files do not displace the last valid image', () async {
    final source = LocalCalendar(dir);
    expect(await source.readLatest(now), isNull);
    await image('2026-10-28');
    await image('2026-10-30');
    await File('${dir.path}/2026-10-29.jpg').writeAsBytes([0xff, 0xd8, 0, 0]);
    expect((await source.readLatest(now))?.date, '2026-10-28');
    await File('${dir.path}/2026-10-28.jpg').setLastModified(now);
    expect((await source.readLatest(now))?.updatedToday(now), isFalse);
  });

  test('provenance belongs to the image date, never yesterday or malformed text', () async {
    final source = LocalCalendar(dir);
    await image('2026-10-29');
    await File('${dir.path}/2026-10-28.md').writeAsString('old author');
    expect((await source.readLatest(now))?.notes, isNull);
    final note = File('${dir.path}/2026-10-29.md');
    await note.writeAsString('source');
    expect((await source.readLatest(now))?.notes, 'source');
    await note.writeAsBytes([0xff, 0xff]);
    expect((await source.readLatest(now))?.notes, isNull);
  });

  test('first run downloads once, resuming keeps the same bytes, midnight updates', () async {
    final days = <String>[];
    final updater = CalendarUpdater(LocalCalendar(dir), download: (_, day) async {
      days.add(day); await image(day); return true;
    });
    await Future.wait([updater.update(now), updater.update(now)]);
    final reading = updater.reading;
    expect(reading?.date, '2026-10-29');
    await updater.update(now.add(const Duration(hours: 1)));
    await updater.update(now, force: true);
    expect(updater.reading, same(reading));
    expect(days, ['2026-10-29']);
    expect(updater.nextCheck(now), const Duration(hours: 14, minutes: 1));
    await updater.update(DateTime.utc(2026, 10, 29, 16, 1));
    expect(days, ['2026-10-29', '2026-10-30']);
  });

  test('offline preserves cache, backs off on resume, then recovers', () async {
    await image('2026-10-28');
    var calls = 0;
    var online = false;
    final updater = CalendarUpdater(LocalCalendar(dir), download: (_, day) async {
      calls++;
      if (!online) throw const SocketException('offline');
      await image(day); return true;
    });
    await updater.update(now);
    final old = updater.reading;
    expect(old?.date, '2026-10-28');
    await updater.update(now.add(const Duration(minutes: 1)));
    expect(calls, 1);
    expect(updater.reading, same(old));
    expect(updater.nextCheck(now), const Duration(minutes: 30));
    online = true;
    await updater.update(now.add(const Duration(minutes: 30)));
    expect(calls, 2);
    expect(updater.reading?.date, '2026-10-29');
  });

  test('manual retry bypasses backoff and next-day checks cross a year boundary', () async {
    var calls = 0;
    final updater = CalendarUpdater(LocalCalendar(dir), download: (_, _) async { calls++; return false; });
    await updater.update(now);
    await updater.update(now, force: true);
    expect(calls, 2);
    await image('2026-12-31');
    final yearEnd = DateTime.utc(2026, 12, 31, 15, 59);
    await updater.update(yearEnd);
    expect(updater.nextCheck(yearEnd), const Duration(minutes: 2));
  });
}
