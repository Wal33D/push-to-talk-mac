"""Focused app detection and context for macOS."""

from __future__ import annotations

import logging

LOG = logging.getLogger("vtc")

# App categories by bundle ID prefix/match
_MESSAGING_BUNDLES = {
    "com.tinyspeck.slackmacgap",  # Slack
    "com.apple.MobileSMS",  # Messages
    "ru.keepcoder.Telegram",  # Telegram
    "com.hnc.Discord",  # Discord
    "net.whatsapp.WhatsApp",  # WhatsApp
    "com.microsoft.teams",  # Teams
    "com.facebook.archon",  # Messenger
    "com.skype.skype",  # Skype
    "com.openai.chat",  # ChatGPT
}

_EDITOR_BUNDLES = {
    "com.microsoft.VSCode",
    "com.apple.dt.Xcode",
    "com.sublimetext.4",
    "com.sublimetext.3",
    "com.jetbrains.intellij",
    "com.googlecode.iterm2",
    "com.apple.Terminal",
    "dev.warp.Warp-Stable",
    "com.cursor.Cursor",
    "com.todesktop.230313mzl4w4u92",  # Cursor alt
}

_BROWSER_BUNDLES = {
    "com.apple.Safari",
    "com.google.Chrome",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "com.brave.Browser",
    "company.thebrowser.Browser",  # Arc
}

# Messaging apps where Enter sends by default
_ENTER_SENDS = {
    "com.tinyspeck.slackmacgap",  # Slack
    "com.apple.MobileSMS",  # Messages
    "ru.keepcoder.Telegram",  # Telegram
    "com.hnc.Discord",  # Discord
    "net.whatsapp.WhatsApp",  # WhatsApp
    "com.facebook.archon",  # Messenger
    "com.skype.skype",  # Skype
}

# Apps where we should NOT auto-send (editors, terminals)
_NO_SEND = {
    "com.microsoft.VSCode",
    "com.apple.dt.Xcode",
    "com.sublimetext.4",
    "com.sublimetext.3",
    "com.googlecode.iterm2",
    "com.apple.Terminal",
    "dev.warp.Warp-Stable",
    "com.cursor.Cursor",
    "com.todesktop.230313mzl4w4u92",
}


class FocusedAppContext:
    """Detects the currently focused application via NSWorkspace."""

    @staticmethod
    def get_focused_app():
        """Return {"name": str, "bundle_id": str} for the frontmost app."""
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return {
                "name": app.localizedName() or "Unknown",
                "bundle_id": app.bundleIdentifier() or "",
            }
        except Exception as exc:
            LOG.debug(f"Failed to get focused app: {exc}")
            return {"name": "Unknown", "bundle_id": ""}

    @staticmethod
    def get_app_category(bundle_id):
        """Classify app as messaging/editor/terminal/browser/other."""
        if bundle_id in _MESSAGING_BUNDLES:
            return "messaging"
        if bundle_id in _EDITOR_BUNDLES:
            return "editor"
        if bundle_id in _BROWSER_BUNDLES:
            return "browser"
        # Check for terminal-like bundle IDs
        bid_lower = bundle_id.lower()
        if "terminal" in bid_lower or "iterm" in bid_lower or "warp" in bid_lower:
            return "terminal"
        return "other"

    @staticmethod
    def get_recommended_send_key(bundle_id):
        """Return recommended send behavior for an app.

        Returns:
            "return" — Enter sends (messaging apps)
            None — don't auto-send (editors, terminals)
            "default" — use user's configured send key
        """
        if bundle_id in _ENTER_SENDS:
            return "return"
        if bundle_id in _NO_SEND:
            return None
        return "default"
