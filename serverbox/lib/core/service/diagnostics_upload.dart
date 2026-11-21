import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/foundation.dart';
import 'package:sentry/sentry.dart' as sentry;
import 'package:server_box/core/service/known_identifiers.dart';
import 'package:server_box/data/model/app/diagnostics_level.dart';
import 'package:server_box/data/res/store.dart';

// Kept only to read old settings and test migrations. No upload SDK is started.
const kDiagnosticsConsentVer = 1;

/// Diagnostics are local-only in Inspire Queue. Old consent, restored backups
/// and build-time DSNs cannot re-enable an outbound sink.
abstract final class DiagnosticsUpload {
  static const dsn = '';
  static bool get availableInBuild => false;
  static DiagnosticsLevel get level => DiagnosticsLevel.none;
  static bool get uploading => false;

  static Future<void> sync() async {
    Diag.install(LocalDiagnosticsSink());
    Stores.setting.diagnosticsLevel.putSync(DiagnosticsLevel.none.name);
    Stores.setting.diagnosticsConsentVer.putSync(0);
  }

  /// Clear legacy upload choices and analytics identifiers on upgrade.
  static Future<void> retireFullLevel() async {
    await sync();
    await PrefStore.shared.remove('openpanel_profile_id');
  }

  /// [scrub], with what this install currently knows to be the user's — or
  /// null, which drops the event.
  ///
  /// Read per event rather than kept: a server added since launch is one whose
  /// name would otherwise still go out. It is a store read on the way to the
  /// network, which is not a hot path — an event is a crash.
  ///
  /// **An event this cannot promise to have scrubbed does not go.** The
  /// records are the whole of what separates a report from a disclosure, so
  /// sending one without them would upload an unaudited string on the single
  /// path where nothing was able to check it. The failure is narrow — an error
  /// raised from an isolate that never opened a store, or while the app is
  /// coming down — and what is given up is one report, while the error is
  /// still written to the on-device log by the sink beside this one.
  ///
  /// An install with *no servers* is not this case. It has nothing to
  /// substitute, and its events go as they are.
  /// Groups a [RangeError] by where it was thrown rather than by its text.
  ///
  /// The message carries the bad value and the bounds, and GlitchTip groups an
  /// event without a fingerprint by its title — so one bug became one issue
  /// per pair of numbers: the terminal buffer's out-of-range read, fixed once,
  /// was more than five hundred issues. Two in-app frames, not one: the first
  /// is the buffer's own `[]` for every caller, and which caller it was is the
  /// bug. [IndexError] is a [RangeError] here too.
  @visibleForTesting
  static sentry.SentryEvent groupByCallSite(sentry.SentryEvent event) {
    if (event.throwable is! RangeError) return event;
    final frames = event.exceptions?.lastOrNull?.stackTrace?.frames;
    if (frames == null) return event;
    // Oldest first, as Sentry orders them: the throw is at the end.
    final sites = frames.reversed
        .where((f) => f.inApp == true)
        .take(2)
        .map((f) => '${f.package}:${f.fileName}:${f.function}')
        .toList();
    if (sites.isEmpty) return event;
    event.fingerprint = ['RangeError', ...sites];
    return event;
  }

  @visibleForTesting
  static sentry.SentryEvent? scrubWithStoredIdentifiers(
    sentry.SentryEvent event,
  ) {
    final Map<String, String> identifiers;
    try {
      identifiers = KnownIdentifiers.of(Stores.server.fetch());
    } catch (e, s) {
      Loggers.app.warning('Could not read what to scrub from a report', e, s);
      return null;
    }
    return scrub(event, identifiers);
  }

  /// Takes the user's own infrastructure back out of an outgoing event.
  ///
  /// **A crumb is written to be published; an exception's message is not.**
  /// Everything this app records by hand goes through [Redact] where it is
  /// made, and `SentrySink.log` drops the log stream for exactly that reason —
  /// but an error's text is written by whoever threw it, which includes
  /// packages and Riverpod. `Spi.toString` used to be `Spi<user@host:port>`,
  /// and Riverpod names a family provider after its argument: one
  /// `UnmountedRefException` uploaded a server's address and login. That
  /// `toString` is fixed, and this is the net under the next one.
  ///
  /// Precise rather than pattern-based — see [KnownIdentifiers] — so it
  /// removes what this install *knows* is the user's and never guesses. Text
  /// nothing here can attribute goes out as written; the class of errors that
  /// quote a hostname is what the levels and the opt-in are for.
  ///
  /// **Three fields of a `SentryEvent` are deliberately not touched**, each
  /// because reaching it would be writing against something that does not
  /// happen here rather than covering a path:
  ///
  /// - `extra` is deprecated in this SDK and nothing in this app writes one.
  /// - `contexts` is filled by [DiagnosticsPlatform], whose entire purpose is
  ///   deciding what may go in it — hardware and OS release, no name, no
  ///   identifier — and by the SDK's own `app`, `runtime` and `culture`. It
  ///   holds typed objects rather than free text.
  /// - `request` is set by an HTTP integration, and the pure-Dart SDK has
  ///   none. Adding `sentry_dio` would change that, and a monitor agent's URL
  ///   is exactly what such an event would carry: cover it then.
  @visibleForTesting
  static sentry.SentryEvent scrub(
    sentry.SentryEvent event,
    Map<String, String> identifiers,
  ) {
    // Nothing sets either: `sendDefaultPii` is false, and the SDK fills
    // `ip_address` and `server_name` only when it is true. Cleared anyway, for
    // the same reason that option is set explicitly rather than left to the
    // default — a later SDK changing its mind would be silent, and a hostname
    // is a name the machine answers to on every network it joins.
    //
    // The address the *receiving* server records from the connection is not
    // reachable from here. That is a setting on the instance (GlitchTip:
    // Organization → Scrub IP Addresses).
    event.user = null;
    event.serverName = null;

    if (identifiers.isEmpty) return event;

    String sub(String text) => KnownIdentifiers.substitute(text, identifiers);

    /// [key], substituted, under a name no entry of [out] has taken.
    ///
    /// **Keys are text too.** Every call site writes a literal one today —
    /// `Diag.crumb` names its fields in code — but nothing about
    /// `Map<String, dynamic>` stops the next one keying by server name, and a
    /// key discloses exactly what a value does.
    ///
    /// Numbered on collision rather than overwritten, which is the reason this
    /// is a function at all: two spellings of one address reduce to the same
    /// token, and a map literal would keep the last of them and silently come
    /// out shorter than it went in.
    String subKey(Map<Object?, Object?> out, String key) {
      final replaced = sub(key);
      if (!out.containsKey(replaced)) return replaced;
      var n = 2;
      while (out.containsKey('$replaced #$n')) {
        n++;
      }
      return '$replaced #$n';
    }

    // Through nested collections, not just the top level. A crumb's `data` is
    // one level of `String` today — `Diag.crumb` takes a `Map<String, String>`
    // — but the field is `Map<String, dynamic>`, and a value put a level down
    // would be a hole nothing would notice. Non-strings are returned as they
    // are, so numbers and booleans keep their type through the round trip, and
    // a key that is not text is left alone: there is nothing in it to match,
    // and rewriting it would change a shape this cannot read.
    Object? subValue(Object? value) {
      switch (value) {
        case String():
          return sub(value);
        case Map():
          final out = <Object?, Object?>{};
          for (final e in value.entries) {
            final key = e.key;
            out[key is String ? subKey(out, key) : key] = subValue(e.value);
          }
          return out;
        case Iterable():
          return value.map(subValue).toList();
        default:
          return value;
      }
    }

    final message = event.message;
    if (message != null) {
      message.formatted = sub(message.formatted);
      final template = message.template;
      if (template != null) message.template = sub(template);
      final params = message.params;
      // Replaced rather than written through, here and below: a list or map
      // handed to the SDK may be const, and assigning the field is not.
      if (params != null) message.params = params.map(subValue).toList();
    }

    for (final e in event.exceptions ?? const <sentry.SentryException>[]) {
      final value = e.value;
      if (value != null) e.value = sub(value);
    }

    for (final crumb in event.breadcrumbs ?? const <sentry.Breadcrumb>[]) {
      final message = crumb.message;
      if (message != null) crumb.message = sub(message);
      final data = crumb.data;
      if (data != null) {
        // Through the same walk as any nested map, then retyped: the field is
        // declared tighter than what that answers, and every key at this level
        // is already a `String`.
        crumb.data = Map<String, dynamic>.from(subValue(data)! as Map);
      }
    }

    final tags = event.tags;
    if (tags != null) {
      final out = <String, String>{};
      for (final e in tags.entries) {
        out[subKey(out, e.key)] = sub(e.value);
      }
      event.tags = out;
    }

    final culprit = event.culprit;
    if (culprit != null) event.culprit = sub(culprit);
    final transaction = event.transaction;
    if (transaction != null) event.transaction = sub(transaction);

    return event;
  }
}

