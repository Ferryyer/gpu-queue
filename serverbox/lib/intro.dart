part of 'app.dart';

/// One step of the intro, and the question of whether it applies.
///
/// The predicate travels with the page. It used to be a number keyed into a
/// map, tested in a `where` several methods away — so adding a step meant two
/// edits in two places, and the condition for a step was nowhere near the step
/// it belonged to.
typedef _IntroStep = ({Future<bool> Function() applies, IntroPageBuilder build});

/// The latest revision of the feature pages — see
/// [SettingStore.featureIntroVer]. A page added later names the next number,
/// and this moves to it.
const _kFeatureIntroVer = 2;


final class _IntroPage extends StatelessWidget {
  const _IntroPage(this.pages);

  final List<IntroPageBuilder> pages;

  static final _setting = Stores.setting;

  static const _kIconSize = 23.0;
  static const _kIntroListPad = 17.0;
  static const _kMaxPadTop = 120.0;

  /// Horizontal room for a paragraph, and the gap above and below it.
  static const _kProsePad = EdgeInsets.symmetric(horizontal: 13, vertical: 8);

  /// Every step there is, in the order they are shown.
  ///
  /// A list rather than a map: the order is the list's, and nothing needs a
  /// number to refer to a step by.
  static List<_IntroStep> get _steps => [
    (applies: _isFirstLaunch, build: _buildSshSetup),
    // After the questions: these only say what the app can do.
    (applies: () async => _featureUnseen(1), build: _buildRemoteDesktop),
    (
      applies: () async => LocalServer.isSupported && _featureUnseen(1),
      build: _buildLocalServer,
    ),
  ];

  /// The steps this launch should show.
  static Future<List<IntroPageBuilder>> get builders async {
    final builders = <IntroPageBuilder>[];
    for (final step in _steps) {
      if (await step.applies()) builders.add(step.build);
    }
    return builders;
  }

  // — When a step applies ————————————————————————————————————————————

  /// Nothing has ever completed the intro on this install.
  static Future<bool> _isFirstLaunch() async => _setting.introVer.fetch() == 0;

  /// A feature page introduced in revision [since] that this install has not
  /// been shown. Fresh installs included: the pages describe features, not
  /// changes, and a first launch knows neither.
  static bool _featureUnseen(int since) =>
      _setting.featureIntroVer.fetch() < since;

  // — Widget build ——————————————————————————————————————————————————

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, cons) {
        // Proportional on phones, capped so a tall desktop window doesn't push
        // the title halfway down the screen — it is used twice per page, above
        // and below the title.
        final padTop = (cons.maxHeight * .16).clamp(0.0, _kMaxPadTop);
        return IntroPage(
          key: ValueKey(Localizations.localeOf(context)),
          args: IntroPageArgs(
            pages: pages.map((e) => e(context, padTop)).toList(),
            maxWidth: PageColumns.columnWidth,
            onDone: _onDone,
          ),
        );
      },
    );
  }

  static void _onDone(BuildContext ctx) {
    SqliteStore.transact(() {
      _setting.introVer.putSync(BuildData.build);
      final lastVer = _setting.lastVer;
      if (lastVer.fetch() == 0) lastVer.putSync(BuildData.build);
      _setting.featureIntroVer.putSync(_kFeatureIntroVer);
    });
    Navigator.of(ctx).pushReplacement(
      MaterialPageRoute(builder: (_) => _buildHomeWithWindowFrame()),
    );
  }

  // — Shared pieces —————————————————————————————————————————————————

  /// Keeps the content in the same column the rest of the app reads in, while
  /// the scrollbar stays at the window edge.
  static Widget _introList({required List<Widget> children}) {
    // [IntroPage] is a bare `Scaffold` holding a `PageView`, so a page's
    // viewport starts at the very top of the screen — and a list long enough
    // to scroll draws its title over the clock and the status icons. Bounding
    // the viewport rather than padding the list is what clips it there, which
    // is the difference between a title that stops under the status bar and
    // one that slides past it.
    //
    // `bottom: false` because the page already ends in a `BottomAppBar`, and
    // outside the [LayoutBuilder] so the width the column is centred in is the
    // one left after a landscape cutout.
    return SafeArea(
      bottom: false,
      child: LayoutBuilder(
        builder: (_, cons) {
          final rest = (cons.maxWidth - PageColumns.columnWidth) / 2;
          return ListView(
            padding: EdgeInsets.symmetric(
              horizontal: math.max(rest, _kIntroListPad),
            ),
            children: children,
          );
        },
      ),
    );
  }

  /// A page's title with the breathing room above and below it.
  static List<Widget> _head(String title, double padTop, {Widget? mark}) => [
    SizedBox(height: padTop),
    IntroPage.title(text: title, big: true, mark: mark),
    SizedBox(height: padTop),
  ];

  /// A sentence of explanation, indented to line up with the tiles under it.
  static Widget _prose(String text) =>
      Padding(padding: _kProsePad, child: Text(text, style: UIs.textGrey));

  // — Pages —————————————————————————————————————————————————————————

  static Widget _buildSshSetup(BuildContext ctx, double padTop) => _introList(
    children: [
      ..._head('连接你的服务器', padTop / 2),
      const ClientBundleSetup(),
      _prose('也可以稍后在设置 → 终端 → 导入服务器配置包中完成。'),
      UIs.height77,
    ],
  );

  static Widget _buildRemoteDesktop(BuildContext ctx, double padTop) {
    final l10n = ctx.l10n;

    return _introList(
      children: [
        ..._head(
          l10n.remoteDesktop,
          padTop,
          mark: Feature.remoteDesktop.mark(height: BetaTag.heading),
        ),
        _prose(l10n.remoteDesktopIntro),
        ListTile(
          leading: const Icon(Icons.desktop_windows_outlined, size: _kIconSize),
          title: const Text('RDP · VNC'),
          subtitle: Text(l10n.remoteDesktopIntroProfiles, style: UIs.textGrey),
        ).cardx,
        ListTile(
          leading: const Icon(Icons.touch_app_outlined, size: _kIconSize),
          title: Text(l10n.remoteDesktopGuideTouch),
          subtitle: Text(l10n.remoteDesktopGuideTouchTip, style: UIs.textGrey),
        ).cardx,
        ListTile(
          leading: const Icon(Icons.visibility_outlined, size: _kIconSize),
          title: Text(l10n.remoteDesktopViewOnly),
          subtitle: Text(
            l10n.remoteDesktopGuideViewOnlyTip,
            style: UIs.textGrey,
          ),
        ).cardx,
        UIs.height77,
      ],
    );
  }

  /// The device running the app, as a server — see `Spi.local`.
  ///
  /// Offers to add it here, since that is one tap and needs nothing typed.
  /// Only where [LocalServer.isSupported]: a page about a feature this build
  /// cannot use would be an advertisement.
  static Widget _buildLocalServer(BuildContext ctx, double padTop) {
    final l10n = ctx.l10n;
    // Not read from the servers here: building a page should not depend on
    // them being loaded. The tap finds out, and one already there counts.
    final added = ValueNotifier(false);

    return DisposeWith(
      notifiers: [added],
      child: _introList(
        children: [
          ..._head(l10n.thisDevice, padTop),
          _prose(l10n.localServerIntro),
          added.listenVal(
            (done) => ListTile(
              leading: const Icon(Icons.computer, size: _kIconSize),
              title: Text(l10n.localServerAdd),
              subtitle: Text(Platform.localHostname, style: UIs.textGrey),
              trailing: Icon(done ? Icons.check : Icons.add),
              onTap: done
                  ? null
                  : () async {
                      if (await _addLocalServer(ctx)) added.value = true;
                    },
            ).cardx,
          ),
          _prose(l10n.localServerIntroFooter),
          UIs.height77,
        ],
      ),
    );
  }

  // — Actions ———————————————————————————————————————————————————————

  /// Adds this device as a server, unless one already is. False, after
  /// saying why, when that failed.
  static Future<bool> _addLocalServer(BuildContext ctx) async {
    final container = ProviderScope.containerOf(ctx, listen: false);
    final servers = container.read(serversProvider).servers.values;
    if (servers.any((e) => e.local)) return true;
    final notifier = container.read(serversProvider.notifier);
    try {
      await notifier.addServer(
        Spi(name: Platform.localHostname, id: ShortId.generate(), local: true),
      );
      return true;
    } catch (e, s) {
      Loggers.app.warning('Add this device from the intro', e, s);
      Toast.error(libL10n.fail, body: e.toString());
      return false;
    }
  }

}

@visibleForTesting
Future<List<IntroPageBuilder>> introBuilders() => _IntroPage.builders;
