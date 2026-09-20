# UI Theme Tokens V1

## Purpose

LocalAI Desktop had accepted visual behavior but duplicated the same colors and
button geometry across MainWindow QSS, inline button styles, scheduler status
rows and dialog help text.

V1 consolidates those values into one explicit module without redesigning the UI.

## Canonical source

`app/ui_theme.py`

It owns:

- desktop/panel/input/chat backgrounds
- border colors
- primary/muted/side text colors
- accent colors
- sidebar hover/pressed colors
- scheduler health colors
- shared sidebar button dimensions
- canonical MainWindow stylesheet
- canonical inline sidebar button stylesheet
- muted-label helper
- scheduler status-color helper

## Compatibility

The accepted Desktop appearance is intentionally preserved.

`app/main_window.py` keeps the compatibility names:

- `STYLE`
- `SIDE_MENU_BUTTON_INLINE_STYLE`

but both now resolve to values produced by `app.ui_theme`.

This avoids breaking existing code while removing duplicate visual literals.

## Sidebar schedule status

The import-time sidebar patch still exists as documented migration debt, but its
visual state colors now come from the canonical theme module.

No new patch module is introduced.

## Dialogs

Scheduler and Extensions muted/help labels use the shared muted-text token rather
than hardcoded copies.

Further dialogs can migrate incrementally without changing their layouts.

## Rendered UI tests

`tests/test_ui_theme.py` creates real Qt widgets using the offscreen platform,
applies the canonical stylesheet and renders them to an image.

The tests verify that:

- a side-menu button actually renders the accepted panel background;
- a primary button actually renders the accepted accent background;
- canonical schedule colors remain stable;
- muted-label helpers use the same token.

These complement source-structure tests in `test_main_window_import.py`.

## Acceptance

V1 is accepted when:

- existing Desktop appearance remains visually unchanged;
- left/right side-menu controls still share the same visual family;
- scheduler state colors remain unchanged;
- Extensions and Scheduler muted text remains unchanged;
- no new patch module is added;
- rendered offscreen Qt theme tests pass;
- exact-head Windows GitHub CI passes.
