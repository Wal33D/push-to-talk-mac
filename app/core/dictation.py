"""Dictation command and text post-processing helpers."""

from __future__ import annotations

import re


class DictationProcessor:
    """Processes dictation commands like 'new line', 'period', etc."""

    # Voice commands mapped to their replacements
    COMMANDS = {
        # Punctuation
        "period": ".",
        "full stop": ".",
        "comma": ",",
        "question mark": "?",
        "exclamation mark": "!",
        "exclamation point": "!",
        "colon": ":",
        "semicolon": ";",
        "hyphen": "-",
        "dash": " - ",
        "open quote": '"',
        "close quote": '"',
        "open paren": "(",
        "close paren": ")",
        "open bracket": "[",
        "close bracket": "]",
        "ellipsis": "...",
        # Whitespace
        "new line": "\n",
        "newline": "\n",
        "new paragraph": "\n\n",
        "tab": "\t",
        "space": " ",
        # Special
        "ampersand": "&",
        "at sign": "@",
        "hashtag": "#",
        "hash": "#",
        "dollar sign": "$",
        "percent sign": "%",
        "percent": "%",
        "asterisk": "*",
        "star": "*",
        "plus sign": "+",
        "plus": "+",
        "minus sign": "-",
        "minus": "-",
        "equals sign": "=",
        "equals": "=",
        "slash": "/",
        "forward slash": "/",
        "backslash": "\\",
        "back slash": "\\",
        "underscore": "_",
        "pipe": "|",
        "tilde": "~",
        "caret": "^",
        "greater than": ">",
        "less than": "<",
        # Common programming
        "arrow": "->",
        "fat arrow": "=>",
        "double colon": "::",
        "triple dot": "...",
        # Formatting
        "all caps": "",  # Placeholder - handled specially
        "capitalize": "",  # Placeholder - handled specially
        # Common words/phrases
        "smiley face": ":)",
        "smiley": ":)",
        "frown face": ":(",
        "frowny face": ":(",
        "wink": ";)",
        "heart": "<3",
        # Markdown formatting (spoken wrappers)
        "bold start": "**",
        "bold end": "**",
        "italic start": "*",
        "italic end": "*",
        "code start": "`",
        "code end": "`",
        "strike start": "~~",
        "strike end": "~~",
        "link start": "[",
        "link end": "]",
        "bullet point": "- ",
        "numbered": "1. ",
        # Quick phrases (common responses)
        "sounds good": "Sounds good!",
        "thank you": "Thank you!",
        "no problem": "No problem!",
        "on my way": "On my way!",
        "be right back": "Be right back.",
        "one moment": "One moment please.",
        "let me check": "Let me check on that.",
        "good morning": "Good morning!",
        "good afternoon": "Good afternoon!",
        "good evening": "Good evening!",
        "have a good day": "Have a good day!",
        "talk to you later": "Talk to you later!",
    }

    # Special commands that control the app (processed separately)
    CONTROL_COMMANDS = {
        "scratch that": "SCRATCH",
        "delete that": "SCRATCH",
        "undo that": "SCRATCH",
        "never mind": "SCRATCH",
        "cancel that": "CANCEL",
        "repeat that": "REPEAT",
        "say that again": "REPEAT",
    }

    # Commands that should remove preceding space
    NO_SPACE_BEFORE = {".", ",", "?", "!", ":", ";", ")", "]", '"'}

    # Common text corrections
    TEXT_CORRECTIONS = {
        # "I" corrections
        r"\bi\b": "I",  # Standalone "i" -> "I"
        r"\bi\'m\b": "I'm",
        r"\bi\'ll\b": "I'll",
        r"\bi\'ve\b": "I've",
        r"\bi\'d\b": "I'd",
        r"\bim\b": "I'm",  # Common speech-to-text error
        r"\bill\b": "I'll",  # Common speech-to-text error
        r"\bive\b": "I've",  # Common speech-to-text error
        # Note: "id" -> "I'd" removed as "id" is a valid word (user id, etc.)
        # Contractions without apostrophes
        r"\bdont\b": "don't",
        r"\bwont\b": "won't",
        r"\bcant\b": "can't",
        r"\bwouldnt\b": "wouldn't",
        r"\bcouldnt\b": "couldn't",
        r"\bshouldnt\b": "shouldn't",
        r"\bdidnt\b": "didn't",
        r"\bdoesnt\b": "doesn't",
        r"\bisnt\b": "isn't",
        r"\barent\b": "aren't",
        r"\bwasnt\b": "wasn't",
        r"\bwerent\b": "weren't",
        r"\bhasnt\b": "hasn't",
        r"\bhavent\b": "haven't",
        r"\bhadnt\b": "hadn't",
        r"\bwontnt\b": "won't",  # Rare but happens
        r"\bmustnt\b": "mustn't",
        r"\bneednt\b": "needn't",
        r"\bshant\b": "shan't",
        r"\bmightnt\b": "mightn't",
        # Common word contractions
        r"\bthats\b": "that's",
        r"\bwhats\b": "what's",
        r"\bheres\b": "here's",
        r"\btheres\b": "there's",
        r"\bwheres\b": "where's",
        r"\bwhos\b": "who's",
        r"\bhows\b": "how's",
        r"\bwhens\b": "when's",
        r"\bwhys\b": "why's",
        r"\bits\b": "it's",
        r"\blets\b": "let's",
        r"\byoure\b": "you're",
        r"\btheyre\b": "they're",
        r"\bwere\b(?!\s)": "we're",
        r"\bshes\b": "she's",
        r"\bhes\b": "he's",
        r"\bweve\b": "we've",
        r"\btheyve\b": "they've",
        r"\byouve\b": "you've",
        r"\bwhatll\b": "what'll",
        r"\bwholl\b": "who'll",
        r"\bthatll\b": "that'll",
        r"\bitll\b": "it'll",
        r"\btheyll\b": "they'll",
        # Note: "well" -> "we'll" removed as it's too context-dependent
        r"\byoull\b": "you'll",
        # Note: "shell" -> "she'll" and "hell" -> "he'll" removed as too context-dependent
        # Common speech-to-text phonetic errors
        r"\bgonna\b": "going to",
        r"\bwanna\b": "want to",
        r"\bgotta\b": "got to",
        r"\blemme\b": "let me",
        r"\bgimme\b": "give me",
        r"\bkinda\b": "kind of",
        r"\bsorta\b": "sort of",
        r"\blotta\b": "lot of",
        r"\boutta\b": "out of",
        r"\bcuz\b": "because",
        r"\bcause\b": "because",
        r"\btho\b": "though",
        r"\bthru\b": "through",
        r"\bok\b": "okay",
        # Double word fixes
        r"\bthe the\b": "the",
        r"\ba a\b": "a",
        r"\ban an\b": "an",
        r"\band and\b": "and",
        r"\bto to\b": "to",
        r"\bof of\b": "of",
        r"\bis is\b": "is",
        r"\bit it\b": "it",
        r"\bthat that\b": "that",
    }

    # Filler words to remove (like Wispr Flow's auto-edit)
    # Note: Be conservative - only remove clear fillers, not words that might be intentional
    FILLER_WORDS = [
        # Basic filler sounds with surrounding punctuation (safe to remove)
        # Pattern: ", um," or ", um " -> " "
        r",?\s*\b(um+)\b\s*,?\s*",
        r",?\s*\b(uh+)\b\s*,?\s*",
        r",?\s*\b(er+)\b\s*,?\s*",
        r",?\s*\b(hmm+)\b\s*,?\s*",
        r",?\s*\b(hm+)\b\s*,?\s*",
        # Repeated words (duplicate only, keep one)
        r"\b(like)\s+(?=like\b)",
        r"\b(so)\s+(?=so\b)",
        r"\b(really)\s+(?=really\b)",
        r"\b(very)\s+(?=very\b)",
        r"\b(just)\s+(?=just\b)",
        # Filler phrases that don't add meaning (with surrounding punctuation)
        r",?\s*\b(you know)\b\s*,?\s*",
        r",?\s*\b(i mean)\b\s*,?\s*",
        # Sentence starters that are often just filler (at beginning only)
        r"^(so)\s*,\s+",  # "So, " at start (with comma)
        r"^(well)\s*,\s+",  # "Well, " at start (with comma)
        r"^(okay)\s*,\s+",  # "Okay, " at start (with comma)
    ]

    @classmethod
    def process(cls, text, enabled=True, auto_capitalize=True, smart_punctuation=True):
        """Process text and replace dictation commands."""
        if not enabled and not auto_capitalize and not smart_punctuation:
            return text

        result = text

        if enabled:
            # Sort commands by length (longest first) to avoid partial matches
            sorted_commands = sorted(cls.COMMANDS.keys(), key=len, reverse=True)

            for command in sorted_commands:
                replacement = cls.COMMANDS[command]

                # Case-insensitive replacement
                # Match whole words/phrases only to avoid replacing substrings
                # (e.g. "period" should not mutate "periodic").
                pattern = re.compile(
                    r"(?<!\w)" + re.escape(command) + r"(?!\w)",
                    re.IGNORECASE,
                )
                # For sub(), backslash needs to be escaped in replacement string
                safe_replacement = replacement.replace("\\", "\\\\")
                result = pattern.sub(safe_replacement, result)

            # Clean up spacing around punctuation
            for punct in cls.NO_SPACE_BEFORE:
                result = result.replace(f" {punct}", punct)

            # Remove double spaces
            while "  " in result:
                result = result.replace("  ", " ")

        result = result.strip()

        # Remove filler words (um, uh, like, you know, etc.)
        # Apply multiple passes to catch nested fillers
        # Replace with a space to prevent words from merging
        for _ in range(2):
            for pattern in cls.FILLER_WORDS:
                result = re.sub(pattern, " ", result, flags=re.IGNORECASE | re.MULTILINE)

        # Apply text corrections (contractions, common errors)
        for pattern, replacement in cls.TEXT_CORRECTIONS.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Clean up extra spaces and punctuation issues
        result = re.sub(r"\s+", " ", result).strip()  # Multiple spaces to single
        result = re.sub(r"\s+([.,!?;:])", r"\1", result)  # Remove space before punctuation
        result = re.sub(r",\s*,+", ",", result)  # Remove duplicate/multiple commas
        result = re.sub(r"([.!?;:])\s*([.!?;:])", r"\1", result)  # Remove duplicate sentence-end punctuation
        result = re.sub(r"^[.,;:]\s*", "", result)  # Remove leading punctuation (except ? !)
        result = re.sub(r",\s*([.!?])", r"\1", result)  # Remove comma before sentence end

        # Remove trailing filler that might remain
        result = re.sub(r"\s+(um|uh|er|ah|hmm|hm|mm|eh)\s*[.,]?\s*$", "", result, flags=re.IGNORECASE)

        # Smart punctuation: add period at end if no sentence-ending punctuation
        if smart_punctuation and result:
            # Don't add period if it's a question (detected by question words at start)
            question_starters = [
                "what",
                "where",
                "when",
                "why",
                "who",
                "how",
                "which",
                "whose",
                "is it",
                "are you",
                "do you",
                "does",
                "did",
                "can",
                "could",
                "would",
                "should",
                "will",
                "have you",
                "has",
                "was",
                "were",
            ]
            text_lower = result.lower()
            is_question = any(text_lower.startswith(q) for q in question_starters)

            if result[-1] not in ".?!":
                result += "?" if is_question else "."

        # Auto-capitalize first letter
        if auto_capitalize and result:
            result = result[0].upper() + result[1:]

            # Capitalize after sentence endings (. ! ?)
            result = re.sub(r"([.!?])\s+([a-z])", lambda m: m.group(1) + " " + m.group(2).upper(), result)

            # Capitalize "I" in contractions that may have been lowercased
            result = re.sub(r"\bi'm\b", "I'm", result)
            result = re.sub(r"\bi'll\b", "I'll", result)
            result = re.sub(r"\bi've\b", "I've", result)
            result = re.sub(r"\bi'd\b", "I'd", result)
            result = re.sub(r"\bi\b", "I", result)

        return result

    @classmethod
    def check_control_command(cls, text):
        """Check if text is a control command. Returns command or None."""
        text_lower = text.lower().strip()
        for phrase, command in cls.CONTROL_COMMANDS.items():
            if text_lower == phrase or text_lower.startswith(phrase):
                return command
        return None

