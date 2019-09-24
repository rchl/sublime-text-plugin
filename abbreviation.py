import re
import sublime
import sublime_plugin
from . import emmet
from . import preview
from . import marker


# List of scope selectors where abbreviation should automatically
# start abbreviation marking
marker_selectors = [
    "text.html - (entity, punctuation.definition.tag.end)",
    "source.css - meta.selector - meta.property-value - string - punctuation - comment"
]


def is_abbreviation_context(view, pt):
    "Check if given location in view is allowed for abbreviation marking"
    for sel in marker_selectors:
        if view.match_selector(pt, sel):
            return True

    return False


def is_css_value_context(view, pt):
    "Check if given location in view is a CSS property value"
    return view.match_selector(pt, 'meta.property-value | punctuation.terminator.rule')


def is_css_color_start(view, begin, end):
    "Check if given view substring is a hex CSS color"
    return view.substr(sublime.Region(begin, end)) == '#'


def is_abbreviation_bound(view, pt):
    "Check if given point in view is a possible abbreviation start"
    line_range = view.line(pt)
    bound_chars = ' \t>'
    left = line_range.begin() == pt or view.substr(pt - 1) in bound_chars
    right = line_range.end() != pt and view.substr(pt) not in bound_chars
    return left and right


def preview_as_phantom(marker):
    return marker.type == 'stylesheet'


def get_caret(view):
    return view.sel()[0].begin()


def nonpanel(fn):
    def wrapper(self, view):
        if not view.settings().get('is_widget'):
            fn(self, view)
    return wrapper


class AbbreviationMarkerListener(sublime_plugin.EventListener):
    def __init__(self):
        self.last_pos = -1

    def on_close(self, view):
        marker.dispose(view)

    @nonpanel
    def on_activated(self, view):
        self.last_pos = get_caret(view)

    @nonpanel
    def on_selection_modified(self, view):
        self.last_pos = get_caret(view)
        mrk = marker.get(view)

        if mrk:
            # Caret is inside marked abbreviation, display preview
            preview.toggle(view, mrk, self.last_pos, preview_as_phantom(mrk))
        else:
            preview.hide(view)

    @nonpanel
    def on_modified(self, view):
        last_pos = self.last_pos
        caret = get_caret(view)
        mrk = marker.get(view)

        if mrk:
            mrk.validate()
            marker_region = marker.get_region(view)
            if not marker_region or marker_region.empty():
                # User removed marked abbreviation
                marker.dispose(view)
                return

            # Check if modification was made inside marked region
            prev_inside = marker_region.contains(last_pos)
            next_inside = marker_region.contains(caret)

            if prev_inside and next_inside:
                # Modifications made completely inside abbreviation, should be already validated
                pass
            elif prev_inside:
                # Modifications made right after marker
                # To properly track updates, we can't just add a [prev_caret, caret]
                # substring since user may type `[` which will automatically insert `]`
                # as a snippet and we won't be able to properly track it.
                # We should extract abbreviation instead.
                abbr_data = emmet.abbreviation_from_line(view, caret)
                if abbr_data:
                    mrk.update(abbr_data[0], abbr_data[1])
                else:
                    # Unable to extract abbreviation or abbreviation is invalid
                    marker.dispose(view)
            elif next_inside and caret > last_pos:
                # Modifications made right before marker
                mrk.update(last_pos, marker_region.end())
            elif not next_inside:
                # Modifications made outside marker
                marker.dispose(view)
                mrk = None

        if not mrk and caret > last_pos:
            # We’re able to start abbreviation mark
            if is_abbreviation_bound(view, last_pos) and is_abbreviation_context(view, caret):
                # User started abbreviation typing
                marker.from_line(view, caret)
            elif is_css_value_context(view, caret) and is_css_color_start(view, last_pos, caret):
                marker.from_line(view, caret)


    def on_query_context(self, view: sublime.View, key: str, op: str, operand: str, match_all: bool):
        if key == 'emmet_abbreviation':
            # Check if caret is currently inside Emmet abbreviation
            mrk = marker.get(view)
            if mrk:
                for s in view.sel():
                    if mrk.contains(s):
                        return True

            return False

        if key == 'has_emmet_abbreviation_mark':
            return marker.get(view) and True or False

        return None

    def on_query_completions(self, view, prefix, locations):
        mrk = marker.get(view)
        caret = locations[0]

        if mrk and not mrk.contains(caret):
            marker.dispose(view)
            mrk = None

        if not mrk and is_abbreviation_context(view, caret):
            # Try to extract abbreviation from given location
            abbr_data = emmet.abbreviation_from_line(view, caret)
            if abbr_data:
                mrk = marker.create(view, abbr_data[0], abbr_data[1])
                if mrk.valid:
                    marker.attach(view, mrk)
                    preview.toggle(view, mrk, caret, preview_as_phantom(mrk))
                else:
                    mrk.reset()
                    mrk = None

        if mrk and mrk.valid:
            return [
                ['%s\tEmmet' % mrk.abbreviation, mrk.snippet()]
            ]

        return None

    def on_text_command(self, view, command_name, args):
        if command_name == 'commit_completion':
            marker.dispose(view)

    def on_post_text_command(self, view, command_name, args):
        if command_name == 'undo':
            # In case of undo, editor may restore previously marked range.
            # If so, restore marker from it
            r = marker.get_region(view)
            if r:
                marker.clear_region(view)
                mrk = marker.create(view, r.begin(), r.end())
                if mrk.valid:
                    marker.attach(view, mrk)
                    preview.toggle(view, mrk, get_caret(view), preview_as_phantom(mrk))
                else:
                    mrk.reset()


class ExpandAbbreviation(sublime_plugin.TextCommand):
    def run(self, edit, **kw):
        sel = self.view.sel()
        mrk = marker.get(self.view)
        caret = get_caret(self.view)

        if mrk.contains(caret):
            if mrk.valid:
                region = mrk.region
                snippet = emmet.expand(mrk.abbreviation, mrk.options)
                sel.clear()
                sel.add(sublime.Region(region.begin(), region.begin()))
                self.view.replace(edit, region, '')
                self.view.run_command('insert_snippet', {'contents': snippet})

            marker.dispose(self.view)