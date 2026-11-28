import 'package:fl_lib/fl_lib.dart';
import 'package:material_ui/material_ui.dart';

/// The field a bar becomes while searching, in place of what it held.
///
/// Searching narrows the list already on screen rather than opening a page of
/// results over it. What is being searched is right there, so the list is the
/// result — it narrows as the query is typed, and its rows stay the rows, with
/// everything they can do still on them. A results page answers with a
/// read-only copy and has to be dismissed before anything can be done about
/// what it found.
///
/// Sized by the caller, because the bars this replaces are not all one height.
class InlineSearchField extends StatelessWidget {
  const InlineSearchField({
    super.key,
    required this.controller,
    required this.onChanged,
    required this.onClose,
    this.hint,
    this.onSubmitted,
    this.onKeyEvent,
    this.focusNode,
    this.trailing,
  });

  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  /// Leave the search. The caller is what clears the query — the field only
  /// says the button was pressed.
  final VoidCallback onClose;

  final String? hint;

  /// Handles submission while keeping focus available to the caller.
  /// Without a handler, submission dismisses the keyboard.
  final ValueChanged<String>? onSubmitted;

  /// Return [KeyEventResult.ignored] to allow normal text-field shortcuts.
  final FocusOnKeyEventCallback? onKeyEvent;
  final FocusNode? focusNode;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    // The bar is the field's box; a theme's form-input border would be a
    // second one inside it. Colours come from the theme's search style.
    final style = ComponentStyles.of(context).search;
    return Row(
      children: [
        const SizedBox(width: 13),
        Expanded(
          child: Focus(
            canRequestFocus: false,
            onKeyEvent: onKeyEvent,
            child: TextField(
              controller: controller,
              focusNode: focusNode,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onChanged: onChanged,
              onEditingComplete: onSubmitted == null
                  ? null
                  : controller.clearComposing,
              onSubmitted:
                  onSubmitted ?? (_) => FocusScope.of(context).unfocus(),
              style: style.textColor == null
                  ? null
                  : TextStyle(color: style.textColor),
              decoration: bareInputDecoration(
                isDense: true,
                hintText: hint ?? libL10n.search,
                hintStyle: style.hintColor == null
                    ? null
                    : TextStyle(color: style.hintColor),
              ),
            ),
          ),
        ),
        ?trailing,
        Btn.icon(
          text: libL10n.close,
          icon: Icon(Icons.close, size: 18, color: style.iconColor),
          onTap: onClose,
        ),
        const SizedBox(width: 7),
      ],
    );
  }
}

/// The query behind an [InlineSearchBar], and whether the bar is a field.
///
/// One object because the two are one state: a page holding them apart kept a
/// notifier, a text controller, a pair of start/stop methods and a `dispose`
/// for each — five pieces of the same thing, written out once per page that
/// can be searched.
///
/// `null` and `''` are different: no field at all, and a field with nothing in
/// it yet. Only the first shows what the bar held before.
class InlineSearchController extends ValueNotifier<String?> {
  InlineSearchController() : super(null);

  final text = TextEditingController();

  /// Whether the bar is a field.
  bool get active => value != null;

  /// What to match against, trimmed and folded. Empty while the field is
  /// empty, so a caller can treat "searching for nothing" as "not searching".
  String get needle => value?.trim().toLowerCase() ?? '';

  /// Sets the search text and places the caret at the end.
  void setQuery(String query) {
    text.value = TextEditingValue(
      text: query,
      selection: TextSelection.collapsed(offset: query.length),
    );
    value = query;
  }

  void start() {
    text.clear();
    value = '';
  }

  void end() {
    text.clear();
    value = null;
  }

  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }
}

/// A bar that is [child] until a search starts, and a field while one is on.
///
/// Crossed rather than cut, because the bar is where the eye already is: what
/// replaces it should read as the same strip changing rather than as one
/// control being swapped for another.
class InlineSearchBar extends StatelessWidget {
  const InlineSearchBar({
    super.key,
    required this.controller,
    required this.child,
    this.hint,
    this.onSubmitted,
    this.onKeyEvent,
    this.focusNode,
    this.trailing,
  });

  final InlineSearchController controller;

  /// What the bar holds when nothing is being searched.
  final Widget child;

  final String? hint;
  final ValueChanged<String>? onSubmitted;
  final FocusOnKeyEventCallback? onKeyEvent;
  final FocusNode? focusNode;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) => AnimatedSwitcher(
        duration: Durations.short4,
        child: controller.active
            ? InlineSearchField(
                key: const ValueKey('inline-search-field'),
                controller: controller.text,
                onChanged: (value) => controller.value = value,
                onClose: controller.end,
                hint: hint,
                onSubmitted: onSubmitted,
                onKeyEvent: onKeyEvent,
                focusNode: focusNode,
                trailing: trailing,
              )
            : KeyedSubtree(
                key: const ValueKey('inline-search-rest'),
                child: child,
              ),
      ),
    );
  }
}
